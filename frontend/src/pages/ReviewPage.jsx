import { useState, useEffect, useCallback } from "react";
import { getFlaggedRecords, approveRecord, rejectRecord, bulkApprove } from "../api/client";
import { StatusBadge, SourceBadge, Spinner, EmptyState, PageHeader, Alert } from "../components/ui";

function fmt(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function ReviewPage() {
  const [records, setRecords] = useState([]);
  const [total, setTotal]     = useState(0);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(new Set());
  const [detail, setDetail]   = useState(null);
  const [sourceFilter, setSourceFilter] = useState("all");
  const [toast, setToast]     = useState(null);
  const [bulkNote, setBulkNote] = useState("");
  const [showBulkModal, setShowBulkModal] = useState(false);

  const showToast = (msg, type = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(() => {
    const params = {};
    if (sourceFilter !== "all") params.source_type = sourceFilter;
    setLoading(true);
    getFlaggedRecords(params)
      .then((r) => { setRecords(r.data.results || []); setTotal(r.data.count || 0); })
      .catch(console.error)
      .finally(() => setLoading(false));
    setSelected(new Set());
  }, [sourceFilter]);

  useEffect(() => { load(); }, [load]);

  const handleApprove = async (id, note = "") => {
    try {
      await approveRecord(id, { analyst_note: note });
      setRecords((r) => r.filter((x) => x.id !== id));
      setTotal((t) => t - 1);
      if (detail?.id === id) setDetail(null);
      showToast("Record approved.");
    } catch {
      showToast("Failed to approve record.", "error");
    }
  };

  const handleReject = async (id, note) => {
    if (!note || note.length < 10) {
      showToast("Rejection reason must be at least 10 characters.", "error");
      return;
    }
    try {
      await rejectRecord(id, { analyst_note: note });
      setRecords((r) => r.filter((x) => x.id !== id));
      setTotal((t) => t - 1);
      if (detail?.id === id) setDetail(null);
      showToast("Record rejected.");
    } catch {
      showToast("Failed to reject record.", "error");
    }
  };

  const handleBulkApprove = async () => {
    try {
      const res = await bulkApprove([...selected], bulkNote);
      showToast(`${res.data.approved_count} records approved.`);
      setShowBulkModal(false);
      setBulkNote("");
      load();
    } catch {
      showToast("Bulk approval failed.", "error");
    }
  };

  const toggleAll = () => {
    if (selected.size === records.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(records.map((r) => r.id)));
    }
  };

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <div>
      <PageHeader
        title="Review Queue"
        description={`${total} flagged record${total !== 1 ? "s" : ""} awaiting analyst review.`}
        action={
          selected.size > 0 && (
            <button
              onClick={() => setShowBulkModal(true)}
              className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 transition-colors"
            >
              Approve {selected.size} selected
            </button>
          )
        }
      />

      {/* Source filter */}
      <div className="flex gap-1 bg-slate-100 rounded-lg p-1 w-fit mb-5">
        {["all", "sap_fuel", "utility", "travel"].map((s) => (
          <button
            key={s}
            onClick={() => setSourceFilter(s)}
            className={`px-3 py-1 text-xs rounded-md font-medium transition-all ${
              sourceFilter === s
                ? "bg-white text-slate-800 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {s === "all" ? "All sources" : { sap_fuel: "SAP Fuel", utility: "Utility", travel: "Travel" }[s]}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-20"><Spinner size="lg" /></div>
      ) : records.length === 0 ? (
        <EmptyState
          title="No flagged records"
          description="All records are clean or have been reviewed."
          icon="✅"
        />
      ) : (
        <div className="rounded-lg border border-slate-200 overflow-hidden bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-4 py-2.5 w-10">
                  <input
                    type="checkbox"
                    checked={selected.size === records.length && records.length > 0}
                    onChange={toggleAll}
                    className="rounded border-slate-300"
                  />
                </th>
                <Th>Source</Th>
                <Th>Description</Th>
                <Th>Date</Th>
                <Th>Quantity</Th>
                <Th>CO₂e (kg)</Th>
                <Th>Flag</Th>
                <Th>Actions</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {records.map((r) => (
                <RecordRow
                  key={r.id}
                  record={r}
                  checked={selected.has(r.id)}
                  onToggle={() => toggle(r.id)}
                  onDetail={() => setDetail(r)}
                  onApprove={() => handleApprove(r.id)}
                  onReject={(note) => handleReject(r.id, note)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail panel */}
      {detail && (
        <RecordDetailPanel
          record={detail}
          onClose={() => setDetail(null)}
          onApprove={(note) => handleApprove(detail.id, note)}
          onReject={(note) => handleReject(detail.id, note)}
        />
      )}

      {/* Bulk approve modal */}
      {showBulkModal && (
        <Modal onClose={() => setShowBulkModal(false)}>
          <p className="font-medium text-slate-800 mb-1">Approve {selected.size} records</p>
          <p className="text-sm text-slate-500 mb-4">
            Only records in <strong>pending review</strong> status will be approved.
            Flagged records are skipped.
          </p>
          <textarea
            placeholder="Optional note for all records…"
            value={bulkNote}
            onChange={(e) => setBulkNote(e.target.value)}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm resize-none h-20 mb-4 focus:outline-none focus:ring-1 focus:ring-slate-400"
          />
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowBulkModal(false)} className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800">Cancel</button>
            <button onClick={handleBulkApprove} className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700">
              Confirm approval
            </button>
          </div>
        </Modal>
      )}

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-6 right-6 px-4 py-3 rounded-lg shadow-lg text-sm font-medium text-white z-50 ${
          toast.type === "error" ? "bg-red-600" : "bg-emerald-600"
        }`}>
          {toast.msg}
        </div>
      )}
    </div>
  );
}

function RecordRow({ record: r, checked, onToggle, onDetail, onApprove, onReject }) {
  const [rejectMode, setRejectMode] = useState(false);
  const [rejectNote, setRejectNote] = useState("");

  return (
    <>
      <tr className="hover:bg-slate-50 transition-colors">
        <td className="px-4 py-3">
          <input type="checkbox" checked={checked} onChange={onToggle} className="rounded border-slate-300" />
        </td>
        <td className="px-4 py-3"><SourceBadge type={r.source_type} /></td>
        <td className="px-4 py-3">
          <button onClick={onDetail} className="text-left">
            <p className="text-slate-800 font-medium truncate max-w-[180px] hover:underline">{r.description || "—"}</p>
            <p className="text-xs text-slate-400">{r.data_source_filename}</p>
          </button>
        </td>
        <td className="px-4 py-3 text-slate-600">{fmt(r.activity_date)}</td>
        <td className="px-4 py-3 text-slate-600">{r.quantity} {r.unit}</td>
        <td className="px-4 py-3 text-slate-600 font-mono text-xs">{Number(r.co2e_kg).toFixed(2)}</td>
        <td className="px-4 py-3">
          <span className="inline-block px-2 py-0.5 bg-red-50 text-red-600 text-xs rounded border border-red-100 max-w-[120px] truncate" title={r.flag_type}>
            {r.flag_type?.replace(/_/g, " ") || "—"}
          </span>
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-1">
            <button
              onClick={onApprove}
              className="px-2.5 py-1 text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200 rounded hover:bg-emerald-100 transition-colors"
            >
              Approve
            </button>
            <button
              onClick={() => setRejectMode(!rejectMode)}
              className="px-2.5 py-1 text-xs font-medium bg-red-50 text-red-700 border border-red-200 rounded hover:bg-red-100 transition-colors"
            >
              Reject
            </button>
          </div>
        </td>
      </tr>
      {rejectMode && (
        <tr className="bg-red-50">
          <td colSpan={8} className="px-4 py-3">
            <div className="flex items-center gap-2">
              <input
                autoFocus
                placeholder="Rejection reason (min 10 chars)…"
                value={rejectNote}
                onChange={(e) => setRejectNote(e.target.value)}
                className="flex-1 border border-red-200 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-red-400 bg-white"
              />
              <button
                onClick={() => { onReject(rejectNote); setRejectMode(false); setRejectNote(""); }}
                className="px-3 py-1.5 bg-red-600 text-white text-xs font-medium rounded hover:bg-red-700"
              >
                Confirm
              </button>
              <button onClick={() => setRejectMode(false)} className="text-xs text-slate-500 hover:text-slate-700">Cancel</button>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function RecordDetailPanel({ record: r, onClose, onApprove, onReject }) {
  const [note, setNote]     = useState("");
  const [rejNote, setRejNote] = useState("");
  const [tab, setTab]       = useState("details");

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-white shadow-xl border-l border-slate-200 h-full overflow-y-auto flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-200 flex items-start justify-between">
          <div>
            <p className="font-medium text-slate-800 text-sm">{r.description || "Record detail"}</p>
            <div className="flex gap-2 mt-1">
              <SourceBadge type={r.source_type} />
              <StatusBadge status={r.status} />
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-200">
          {["details", "raw data", "flag"].map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2.5 text-xs font-medium capitalize transition-colors ${
                tab === t
                  ? "border-b-2 border-slate-800 text-slate-800"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="p-5 flex-1 overflow-y-auto">
          {tab === "details" && (
            <div className="space-y-3 text-sm">
              <DRow label="Activity date">{fmt(r.activity_date)}</DRow>
              <DRow label="Quantity">{r.quantity} {r.unit}</DRow>
              <DRow label="CO₂e"><span className="font-mono">{Number(r.co2e_kg).toFixed(4)} kg</span></DRow>
              <DRow label="GHG Scope">Scope {r.scope}</DRow>
              <DRow label="Emission factor">{r.emission_factor}</DRow>
              <DRow label="Factor source"><span className="text-xs text-slate-400">{r.emission_factor_source}</span></DRow>
              <DRow label="Source file">{r.data_source_filename}</DRow>
            </div>
          )}
          {tab === "raw data" && (
            <div>
              <p className="text-xs text-slate-500 mb-3">Verbatim source row from the original file.</p>
              <div className="bg-slate-50 rounded-lg border border-slate-200 p-3 space-y-1.5">
                {r.raw_data ? Object.entries(r.raw_data).map(([k, v]) => (
                  <div key={k} className="flex gap-3 text-xs">
                    <span className="text-slate-400 font-mono min-w-[140px]">{k}</span>
                    <span className="text-slate-700 font-mono">{String(v) || <em className="text-slate-300">empty</em>}</span>
                  </div>
                )) : <p className="text-xs text-slate-400">No raw data available.</p>}
              </div>
            </div>
          )}
          {tab === "flag" && (
            <div>
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
                <p className="text-xs font-medium text-red-700 mb-1">
                  {r.flag_type?.replace(/_/g, " ").toUpperCase()}
                </p>
                <p className="text-xs text-red-600 whitespace-pre-wrap">{r.flag_reason || "No details."}</p>
              </div>
            </div>
          )}
        </div>

        {/* Action footer */}
        <div className="border-t border-slate-200 p-5 space-y-3">
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Approval note (optional)</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Add a note for the audit trail…"
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm resize-none h-16 focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </div>
          <button
            onClick={() => onApprove(note)}
            className="w-full py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700 transition-colors"
          >
            Approve record
          </button>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Rejection reason (required)</label>
            <textarea
              value={rejNote}
              onChange={(e) => setRejNote(e.target.value)}
              placeholder="Explain why this record is being rejected…"
              className="w-full border border-slate-200 rounded px-3 py-2 text-sm resize-none h-16 focus:outline-none focus:ring-1 focus:ring-red-300"
            />
            <button
              onClick={() => onReject(rejNote)}
              className="w-full mt-2 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 transition-colors"
            >
              Reject record
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Modal({ children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl p-6 max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

function Th({ children }) {
  return <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">{children}</th>;
}

function DRow({ label, children }) {
  return (
    <div className="flex justify-between items-start gap-4">
      <span className="text-slate-500 shrink-0">{label}</span>
      <span className="text-slate-800 text-right">{children}</span>
    </div>
  );
}
