import { useState, useEffect } from "react";
import { getUploads } from "../api/client";
import { StatusBadge, SourceBadge, Spinner, EmptyState, PageHeader } from "../components/ui";

const STATUS_FILTERS = ["all", "done", "processing", "failed"];
const SOURCE_FILTERS = ["all", "sap_fuel", "utility", "travel"];

function fmt(dateStr) {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function HistoryPage() {
  const [uploads, setUploads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    const params = {};
    if (statusFilter !== "all") params.status = statusFilter;
    if (sourceFilter !== "all") params.source_type = sourceFilter;
    setLoading(true);
    getUploads(params)
      .then((r) => setUploads(r.data.results || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [statusFilter, sourceFilter]);

  return (
    <div>
      <PageHeader
        title="Ingestion History"
        description="All file uploads and their processing status."
      />

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-5">
        <FilterGroup
          label="Status"
          options={STATUS_FILTERS}
          value={statusFilter}
          onChange={setStatusFilter}
        />
        <FilterGroup
          label="Source"
          options={SOURCE_FILTERS}
          value={sourceFilter}
          onChange={setSourceFilter}
          labelMap={{ sap_fuel: "SAP Fuel", utility: "Utility", travel: "Travel" }}
        />
      </div>

      {loading ? (
        <div className="flex justify-center py-20"><Spinner size="lg" /></div>
      ) : uploads.length === 0 ? (
        <EmptyState
          title="No uploads yet"
          description="Upload a CSV file to get started."
          icon="📂"
        />
      ) : (
        <div className="rounded-lg border border-slate-200 overflow-hidden bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <Th>File</Th>
                <Th>Source</Th>
                <Th>Status</Th>
                <Th>Rows</Th>
                <Th>Flagged</Th>
                <Th>Progress</Th>
                <Th>Uploaded</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {uploads.map((u) => (
                <tr
                  key={u.id}
                  onClick={() => setSelected(selected?.id === u.id ? null : u)}
                  className="hover:bg-slate-50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-800 truncate max-w-[200px]">{u.original_filename}</p>
                    <p className="text-xs text-slate-400">{u.uploaded_by_name || "Unknown"}</p>
                  </td>
                  <td className="px-4 py-3"><SourceBadge type={u.source_type} /></td>
                  <td className="px-4 py-3"><StatusBadge status={u.status} /></td>
                  <td className="px-4 py-3 text-slate-600">{u.row_count ?? "—"}</td>
                  <td className="px-4 py-3">
                    {u.flagged_count > 0
                      ? <span className="text-amber-600 font-medium">{u.flagged_count}</span>
                      : <span className="text-slate-400">0</span>}
                  </td>
                  <td className="px-4 py-3">
                    {u.approval_progress ? (
                      <ApprovalBar progress={u.approval_progress} />
                    ) : "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-xs">{fmt(u.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail drawer */}
      {selected && <UploadDetail upload={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function ApprovalBar({ progress }) {
  const { total, approved, rejected, pending } = progress;
  if (!total) return <span className="text-slate-400 text-xs">—</span>;
  const pct = Math.round((approved / total) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 bg-slate-100 rounded-full h-1.5 overflow-hidden">
        <div className="bg-emerald-500 h-1.5 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-400">{approved}/{total}</span>
    </div>
  );
}

function UploadDetail({ upload, onClose }) {
  const p = upload.approval_progress || {};
  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div
        className="w-full max-w-md bg-white shadow-xl border-l border-slate-200 h-full overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <p className="font-medium text-slate-800 text-sm truncate">{upload.original_filename}</p>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 text-lg">✕</button>
        </div>
        <div className="p-5 space-y-4">
          <Row label="Source type"><SourceBadge type={upload.source_type} /></Row>
          <Row label="Status"><StatusBadge status={upload.status} /></Row>
          <Row label="Uploaded by">{upload.uploaded_by_name || "—"}</Row>
          <Row label="Uploaded at">{fmt(upload.created_at)}</Row>
          <Row label="Completed at">{fmt(upload.completed_at)}</Row>
          <Row label="Total rows">{upload.row_count}</Row>
          <Row label="Flagged rows">
            <span className={upload.flagged_count > 0 ? "text-amber-600 font-medium" : ""}>
              {upload.flagged_count}
            </span>
          </Row>
          {p.total > 0 && (
            <>
              <hr className="border-slate-100" />
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Approval</p>
              <Row label="Approved">{p.approved}</Row>
              <Row label="Rejected">{p.rejected}</Row>
              <Row label="Pending">{p.pending}</Row>
            </>
          )}
          {upload.error_message && (
            <div className="rounded bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
              {upload.error_message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Th({ children }) {
  return <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">{children}</th>;
}

function Row({ label, children }) {
  return (
    <div className="flex justify-between items-center text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-800">{children}</span>
    </div>
  );
}

function FilterGroup({ label, options, value, onChange, labelMap = {} }) {
  return (
    <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          className={`px-3 py-1 text-xs rounded-md font-medium transition-all ${
            value === o
              ? "bg-white text-slate-800 shadow-sm"
              : "text-slate-500 hover:text-slate-700"
          }`}
        >
          {labelMap[o] || (o === "all" ? "All" : o.charAt(0).toUpperCase() + o.slice(1))}
        </button>
      ))}
    </div>
  );
}
