import { useState, useEffect } from "react";
import { getRecords, getUploads } from "../api/client";
import { StatCard, SourceBadge, StatusBadge, Spinner, EmptyState, PageHeader } from "../components/ui";

function fmt(d) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function DashboardPage() {
  const [stats, setStats]   = useState(null);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getRecords({ limit: 10, offset: 0 }),
      getRecords({ status: "flagged", limit: 1 }),
      getRecords({ status: "approved", limit: 1 }),
      getRecords({ status: "rejected", limit: 1 }),
      getUploads({ status: "failed", limit: 1 }),
    ]).then(([all, flagged, approved, rejected, failed]) => {
      setStats({
        total:    all.data.count,
        flagged:  flagged.data.count,
        approved: approved.data.count,
        rejected: rejected.data.count,
        failed:   failed.data.count,
      });
      setRecent(all.data.results || []);
    }).catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="flex justify-center py-20"><Spinner size="lg" /></div>;
  }

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Overview of ingested records and review status."
      />

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Total records"
          value={stats?.total?.toLocaleString()}
          accent="default"
        />
        <StatCard
          label="Flagged"
          value={stats?.flagged?.toLocaleString()}
          sub="Need analyst review"
          accent={stats?.flagged > 0 ? "warn" : "default"}
        />
        <StatCard
          label="Approved"
          value={stats?.approved?.toLocaleString()}
          accent="success"
        />
        <StatCard
          label="Rejected"
          value={stats?.rejected?.toLocaleString()}
          accent={stats?.rejected > 0 ? "danger" : "default"}
        />
      </div>

      {/* Recent records */}
      <div>
        <h2 className="text-sm font-medium text-slate-700 mb-3">Recent records</h2>
        {recent.length === 0 ? (
          <EmptyState
            title="No records yet"
            description="Upload a CSV file to see records here."
            icon="📊"
          />
        ) : (
          <div className="rounded-lg border border-slate-200 overflow-hidden bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <Th>Description</Th>
                  <Th>Source</Th>
                  <Th>Date</Th>
                  <Th>CO₂e (kg)</Th>
                  <Th>Scope</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {recent.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3">
                      <p className="text-slate-800 truncate max-w-[220px]">{r.description || "—"}</p>
                      <p className="text-xs text-slate-400">{r.data_source_filename}</p>
                    </td>
                    <td className="px-4 py-3"><SourceBadge type={r.source_type} /></td>
                    <td className="px-4 py-3 text-slate-500">{fmt(r.activity_date)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-700">{Number(r.co2e_kg).toFixed(2)}</td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-600">
                        Scope {r.scope}
                      </span>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Th({ children }) {
  return <th className="px-4 py-2.5 text-left text-xs font-medium text-slate-500 uppercase tracking-wide">{children}</th>;
}
