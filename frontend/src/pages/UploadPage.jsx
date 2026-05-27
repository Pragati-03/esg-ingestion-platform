import { useState, useRef } from "react";
import { uploadFile } from "../api/client";
import { StatusBadge, SourceBadge, Alert, PageHeader } from "../components/ui";

const SOURCE_TYPES = [
  { value: "sap_fuel", label: "SAP Fuel / Procurement", ext: "CSV from SAP ECC/S4HANA" },
  { value: "utility",  label: "Utility Electricity",    ext: "CSV from utility portal" },
  { value: "travel",   label: "Corporate Travel",       ext: "CSV from Concur / Navan" },
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
    setError("");
    setResult(null);
    setUploading(true);
    setProgress(0);

    try {
      const fd = new FormData();
      fd.append("source_type", sourceType);
      fd.append("file", file);
      const res = await uploadFile(fd, setProgress);
      setResult(res.data);
      setFile(null);
      setSourceType("");
    } catch (err) {
      const detail = err.response?.data?.error_message
        || err.response?.data?.file?.[0]
        || err.response?.data?.source_type?.[0]
        || "Upload failed. Check the file format and try again.";
      setError(detail);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <PageHeader
        title="Upload Data"
        description="Import a CSV export from SAP, your utility portal, or your travel expense tool."
      />

      {/* Source type selector */}
      <div className="mb-5">
        <label className="block text-sm font-medium text-slate-700 mb-2">Source type</label>
        <div className="grid grid-cols-1 gap-2">
          {SOURCE_TYPES.map((s) => (
            <button
              key={s.value}
              onClick={() => setSourceType(s.value)}
              className={`flex items-center justify-between px-4 py-3 rounded-lg border text-left transition-all ${
                sourceType === s.value
                  ? "border-slate-800 bg-slate-50 ring-1 ring-slate-800"
                  : "border-slate-200 bg-white hover:border-slate-400"
              }`}
            >
              <div>
                <p className="text-sm font-medium text-slate-800">{s.label}</p>
                <p className="text-xs text-slate-400 mt-0.5">{s.ext}</p>
              </div>
              {sourceType === s.value && (
                <span className="text-slate-800 text-lg">✓</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className={`mb-5 border-2 border-dashed rounded-lg px-6 py-10 text-center cursor-pointer transition-all ${
          dragging
            ? "border-slate-500 bg-slate-50"
            : file
            ? "border-emerald-400 bg-emerald-50"
            : "border-slate-200 hover:border-slate-400 bg-white"
        }`}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.xlsx,.xls"
          className="hidden"
          onChange={(e) => setFile(e.target.files[0])}
        />
        {file ? (
          <>
            <p className="text-sm font-medium text-emerald-700">📄 {file.name}</p>
            <p className="text-xs text-slate-400 mt-1">{(file.size / 1024).toFixed(1)} KB — click to replace</p>
          </>
        ) : (
          <>
            <p className="text-sm text-slate-500">Drop your CSV here, or click to browse</p>
            <p className="text-xs text-slate-400 mt-1">CSV, XLSX · max 50MB</p>
          </>
        )}
      </div>

      {/* Progress bar */}
      {uploading && (
        <div className="mb-4">
          <div className="flex justify-between text-xs text-slate-500 mb-1">
            <span>Uploading and processing…</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-slate-100 rounded-full h-1.5">
            <div
              className="bg-slate-700 h-1.5 rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {error && <div className="mb-4"><Alert type="error" message={error} /></div>}

      <button
        onClick={handleSubmit}
        disabled={uploading || !file || !sourceType}
        className="w-full py-2.5 px-4 bg-slate-800 text-white text-sm font-medium rounded-lg
                   hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
      >
        {uploading ? "Processing…" : "Upload and ingest"}
      </button>

      {/* Result card */}
      {result && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-slate-800">{result.original_filename}</p>
              <p className="text-xs text-slate-400 mt-0.5">
                <SourceBadge type={result.source_type} />
              </p>
            </div>
            <StatusBadge status={result.status} />
          </div>
          <div className="grid grid-cols-3 divide-x divide-slate-100">
            <Metric label="Total rows" value={result.row_count} />
            <Metric label="Flagged" value={result.flagged_count} warn={result.flagged_count > 0} />
            <Metric label="Clean" value={result.row_count - result.flagged_count} />
          </div>
          {result.flagged_count > 0 && (
            <div className="px-4 py-3 bg-amber-50 border-t border-amber-100">
              <p className="text-xs text-amber-700">
                {result.flagged_count} row{result.flagged_count !== 1 ? "s" : ""} need analyst review.
                Go to the <strong>Review Queue</strong> to approve or reject them.
              </p>
            </div>
          )}
          {result.status === "failed" && (
            <div className="px-4 py-3 bg-red-50 border-t border-red-100">
              <p className="text-xs text-red-700">{result.error_message}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, warn }) {
  return (
    <div className="px-4 py-3 text-center">
      <p className={`text-xl font-bold ${warn ? "text-amber-600" : "text-slate-800"}`}>{value}</p>
      <p className="text-xs text-slate-400 mt-0.5">{label}</p>
    </div>
  );
}
