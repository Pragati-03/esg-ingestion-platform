export function StatusBadge({ status }) {
  const styles = {
    pending_review: "bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800",
    flagged:        "bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800",
    approved:       "bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800",
    rejected:       "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-700",
    done:           "bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800",
    processing:     "bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-400 border border-blue-200 dark:border-blue-800",
    pending:        "bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800",
    failed:         "bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800",
  };
  const labels = {
    pending_review: "Pending", flagged: "Flagged", approved: "Approved",
    rejected: "Rejected", done: "Done", processing: "Processing",
    pending: "Pending", failed: "Failed",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ${styles[status] || "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400"}`}>
      {labels[status] || status}
    </span>
  );
}

export function SourceBadge({ type }) {
  const styles = {
    sap_fuel: "bg-orange-50 dark:bg-orange-950 text-orange-700 dark:text-orange-400 border border-orange-200 dark:border-orange-800",
    utility:  "bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-400 border border-blue-200 dark:border-blue-800",
    travel:   "bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-400 border border-purple-200 dark:border-purple-800",
  };
  const labels = { sap_fuel: "SAP Fuel", utility: "Utility", travel: "Travel" };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ${styles[type] || "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400"}`}>
      {labels[type] || type}
    </span>
  );
}

export function Spinner({ size = "md" }) {
  const s = { sm: "h-4 w-4", md: "h-6 w-6", lg: "h-8 w-8" }[size];
  return (
    <svg className={`animate-spin ${s} text-slate-300 dark:text-slate-600`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
    </svg>
  );
}

export function EmptyState({ title, description, icon = "inbox" }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="w-12 h-12 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
        <svg className="w-6 h-6 text-slate-400 dark:text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M22 12h-6l-2 3H10l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/>
        </svg>
      </div>
      <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{title}</p>
      {description && <p className="text-xs text-slate-400 dark:text-slate-500 mt-1 max-w-xs">{description}</p>}
    </div>
  );
}

export function StatCard({ label, value, sub, accent }) {
  const borders = {
    default: "border-slate-200 dark:border-slate-700",
    warn:    "border-amber-400 dark:border-amber-600",
    danger:  "border-red-400 dark:border-red-600",
    success: "border-emerald-400 dark:border-emerald-600",
  };
  const dots = {
    default: "bg-slate-300 dark:bg-slate-600",
    warn:    "bg-amber-400 dark:bg-amber-500",
    danger:  "bg-red-400 dark:bg-red-500",
    success: "bg-emerald-400 dark:bg-emerald-500",
  };
  return (
    <div className={`bg-white dark:bg-slate-900 rounded-xl border ${borders[accent] || borders.default} border-l-4 p-5 transition-colors`}>
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-2 h-2 rounded-full ${dots[accent] || dots.default}`}/>
        <p className="text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wide">{label}</p>
      </div>
      <p className="text-3xl font-bold text-slate-800 dark:text-slate-100">{value ?? "—"}</p>
      {sub && <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

export function PageHeader({ title, description, action }) {
  return (
    <div className="flex items-start justify-between mb-7">
      <div>
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">{title}</h1>
        {description && <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Alert({ type = "error", message }) {
  const styles = {
    error:   "bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400",
    success: "bg-emerald-50 dark:bg-emerald-950 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400",
    info:    "bg-blue-50 dark:bg-blue-950 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400",
  };
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm ${styles[type]}`}>{message}</div>
  );
}

export function FilterGroup({ label, options, value, onChange, labelMap = {} }) {
  return (
    <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 rounded-xl p-1">
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-all ${
            value === o
              ? "bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm"
              : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
          }`}
        >
          {labelMap[o] || (o === "all" ? "All" : o.charAt(0).toUpperCase() + o.slice(1))}
        </button>
      ))}
    </div>
  );
}

export function Th({ children }) {
  return (
    <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 dark:text-slate-500 uppercase tracking-wider">
      {children}
    </th>
  );
}
