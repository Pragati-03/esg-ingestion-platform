// Shared UI primitives used across all pages

export function StatusBadge({ status }) {
  const styles = {
    pending_review: "bg-amber-50 text-amber-700 border border-amber-200",
    flagged:        "bg-red-50 text-red-700 border border-red-200",
    approved:       "bg-emerald-50 text-emerald-700 border border-emerald-200",
    rejected:       "bg-slate-100 text-slate-500 border border-slate-200",
    done:           "bg-emerald-50 text-emerald-700 border border-emerald-200",
    processing:     "bg-blue-50 text-blue-700 border border-blue-200",
    pending:        "bg-amber-50 text-amber-700 border border-amber-200",
    failed:         "bg-red-50 text-red-700 border border-red-200",
  };
  const labels = {
    pending_review: "Pending",
    flagged:        "Flagged",
    approved:       "Approved",
    rejected:       "Rejected",
    done:           "Done",
    processing:     "Processing",
    pending:        "Pending",
    failed:         "Failed",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[status] || "bg-slate-100 text-slate-600"}`}>
      {labels[status] || status}
    </span>
  );
}

export function SourceBadge({ type }) {
  const styles = {
    sap_fuel: "bg-orange-50 text-orange-700 border border-orange-200",
    utility:  "bg-blue-50 text-blue-700 border border-blue-200",
    travel:   "bg-purple-50 text-purple-700 border border-purple-200",
  };
  const labels = {
    sap_fuel: "SAP Fuel",
    utility:  "Utility",
    travel:   "Travel",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[type] || "bg-slate-100 text-slate-600"}`}>
      {labels[type] || type}
    </span>
  );
}

export function Spinner({ size = "md" }) {
  const s = { sm: "h-4 w-4", md: "h-6 w-6", lg: "h-8 w-8" }[size];
  return (
    <svg className={`animate-spin ${s} text-slate-400`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

export function EmptyState({ title, description, icon = "📭" }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="text-4xl mb-3">{icon}</div>
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {description && <p className="text-xs text-slate-400 mt-1 max-w-xs">{description}</p>}
    </div>
  );
}

export function StatCard({ label, value, sub, accent }) {
  const accents = {
    default: "border-slate-200",
    warn:    "border-amber-300",
    danger:  "border-red-300",
    success: "border-emerald-300",
  };
  return (
    <div className={`bg-white rounded-lg border-l-4 ${accents[accent] || accents.default} border border-slate-100 p-4 shadow-sm`}>
      <p className="text-xs text-slate-500 font-medium uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-slate-800 mt-1">{value ?? "—"}</p>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  );
}

export function PageHeader({ title, description, action }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-800">{title}</h1>
        {description && <p className="text-sm text-slate-500 mt-0.5">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Alert({ type = "error", message }) {
  const styles = {
    error:   "bg-red-50 border-red-200 text-red-700",
    success: "bg-emerald-50 border-emerald-200 text-emerald-700",
    info:    "bg-blue-50 border-blue-200 text-blue-700",
  };
  return (
    <div className={`rounded-lg border px-4 py-3 text-sm ${styles[type]}`}>
      {message}
    </div>
  );
}
