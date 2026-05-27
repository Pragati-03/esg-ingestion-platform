import { useState } from "react";
import DashboardPage from "./pages/DashboardPage";
import UploadPage    from "./pages/UploadPage";
import HistoryPage   from "./pages/HistoryPage";
import ReviewPage    from "./pages/ReviewPage";

const NAV = [
  { id: "dashboard", label: "Dashboard",    icon: "◫" },
  { id: "upload",    label: "Upload Data",  icon: "↑" },
  { id: "history",   label: "History",      icon: "≡" },
  { id: "review",    label: "Review Queue", icon: "⚑" },
];

const PAGES = {
  dashboard: DashboardPage,
  upload:    UploadPage,
  history:   HistoryPage,
  review:    ReviewPage,
};

export default function App() {
  const [page, setPage] = useState("dashboard");
  const Page = PAGES[page];

  return (
    <div className="min-h-screen bg-slate-50 flex font-sans">
      {/* Sidebar */}
      <aside className="w-56 bg-white border-r border-slate-200 flex flex-col shrink-0">
        {/* Logo */}
        <div className="px-5 py-5 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-slate-800 flex items-center justify-center">
              <span className="text-white text-xs font-bold">B</span>
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-800 leading-tight">Breathe ESG</p>
              <p className="text-xs text-slate-400">Ingestion Platform</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => setPage(n.id)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all ${
                page === n.id
                  ? "bg-slate-100 text-slate-800 font-medium"
                  : "text-slate-500 hover:bg-slate-50 hover:text-slate-700"
              }`}
            >
              <span className="text-base w-5 text-center">{n.icon}</span>
              {n.label}
              {n.id === "review" && <ReviewBadge />}
            </button>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-slate-100">
          <p className="text-xs text-slate-400">demo-tenant</p>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-8 py-8">
          <Page />
        </div>
      </main>
    </div>
  );
}

// Small badge on Review Queue nav item — shows flagged count
function ReviewBadge() {
  // In a real app this would come from a global state/context
  // For now it's a static indicator
  return (
    <span className="ml-auto text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full font-medium">
      !
    </span>
  );
}
