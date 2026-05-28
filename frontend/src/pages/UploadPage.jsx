import { useState, useRef } from "react";
import { uploadFile } from "../api/client";
import { StatusBadge, SourceBadge, Alert, PageHeader } from "../components/ui";

const SOURCE_TYPES = [
  { value: "sap_fuel", label: "SAP Fuel / Procurement", desc: "CSV from SAP ECC or S4HANA", scope: "Scope 1" },
  { value: "utility",  label: "Utility Electricity",    desc: "CSV from utility supplier portal", scope: "Scope 2" },
  { value: "travel",   label: "Corporate Travel",       desc: "CSV from Concur or Navan", scope: "Scope 3" },
];

export default function UploadPage() {
  const [sourceType, setSourceType] = useState("");
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const fileRef = useRef();

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  };

  const handleSubmit = async () => {
    if (!sourceType) { setError("Select a source type before uploading."); return; }
    if (!file)       { setError("Select a file to upload."); return; }
    setError(""); setResult(null); setUploading(true); setProgress(0);
    try {
      const fd = new FormData();
      fd.append("source_type", sourceType);
      fd.append("file", file);
      const res = await uploadFile(fd, setProgress);
      setResult(res.data);
      setFile(null);
      setSourceType("");
    } catch (err) {
      setError(
        err.response?.data?.error_message ||
        err.response?.data?.file?.[0] ||
        "Upload failed. Check the file format and try again."
      );
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto">
      <PageHeader title="Upload data" description="Import a CSV export from your source system." />

      <div className="mb-5">
        <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-3">Select source type</p>
        <div className="space-y-2">
          {SOURCE_TYPES.map((s) => (
            <button
              key={s.value}
              onClick={() => setSourceType(s.value)}
              className={`w-full flex items-center justify-between px-4 py-3.5 rounded-xl border text-left transition-all ${
                sourceType === s.value
                  ? "border-emerald-500 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-950 ring-1 ring-emerald-500 dark:ring-emerald-600"
                  : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-600"
              }`}
            >
              <div>
                <p className="text-sm font-medium text-slate-800 dark:text-slate-100">{s.label}</p>
                <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">{s.desc}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0 ml-3">
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 font-medium">{s.scope}</span>
                {sourceType === s.value && (
                  <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center">
                    <svg className="w-3 h-3 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                  </div>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className={`mb-5 border-2 border-dashed rounded-xl px-6 py-10 text-center cursor-pointer transition-all ${
          dragging ? "border-emerald-400 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-950"
          : file ? "border-emerald-400 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-950/50"
          : "border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 bg-white dark:bg-slate-900"
        }`}
      >
        <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={(e) => setFile(e.target.files[0])} />
        {file ? (
          <>
            <div className="w-10 h-10 rounded-xl bg-emerald-100 dark:bg-emerald-900 flex items-center justify-center mx-auto mb-3">
              <svg className="w-5 h-5 text-emerald-600 dark:text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <p className="text-sm font-medium text-emerald-700 dark:text-emerald-400">{file.name}</p>
            <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">{(file.size / 1024).toFixed(1)} KB — click to replace</p>
          </>
        ) : (
          <>
            <div className="w-10 h-10 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mx-auto mb-3">
              <svg className="w-5 h-5 text-slate-400 dark:text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-400">Drop your CSV here, or click to browse</p>
            <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">CSV, XLSX · max 50MB</p>
          </>
        )}
      </div>

      {uploading && (
        <div className="mb-4">
          <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400 mb-2">
            <span>Uploading and processing…</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-1.5">
            <div className="bg-emerald-500 h-1.5 rounded-full transition-all duration-300" style={{ width: `${progress}%` }}/>
          </div>
        </div>
      )}

      {error && <div className="mb-4"><Alert type="error" message={error} /></div>}

      <button
        onClick={handleSubmit}
        disabled={uploading || !file || !sourceType}
        className="w-full py-3 px-4 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-200 dark:disabled:bg-slate-800 disabled:text-slate-400 dark:disabled:text-slate-600 text-white text-sm font-medium rounded-xl disabled:cursor-not-allowed transition-colors"
      >
        {uploading ? "Processing…" : "Upload and ingest"}
      </button>

      {result && (
        <div className="mt-6 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{result.original_filename}</p>
              <div className="mt-1"><SourceBadge type={result.source_type} /></div>
            </div>
            <StatusBadge status={result.status} />
          </div>
          <div className="grid grid-cols-3 divide-x divide-slate-100 dark:divide-slate-800">
            <Metric label="Total rows" value={result.row_count} />
            <Metric label="Flagged" value={result.flagged_count} warn={result.flagged_count > 0} />
            <Metric label="Clean" value={result.row_count - result.flagged_count} />
          </div>
          {result.flagged_count > 0 && (
            <div className="px-5 py-3 bg-amber-50 dark:bg-amber-950/50 border-t border-amber-100 dark:border-amber-900">
              <p className="text-xs text-amber-700 dark:text-amber-400">
                {result.flagged_count} row{result.flagged_count !== 1 ? "s" : ""} need review in the <strong>Review Queue</strong>.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, warn }) {
  return (
    <div className="px-4 py-4 text-center">
      <p className={`text-2xl font-bold ${warn ? "text-amber-600 dark:text-amber-400" : "text-slate-800 dark:text-slate-100"}`}>{value}</p>
      <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">{label}</p>
    </div>
  );
}
