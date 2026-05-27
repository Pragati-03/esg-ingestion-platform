import axios from "axios";

const TENANT_SLUG = import.meta.env.VITE_TENANT_SLUG || "demo-tenant";
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: `${BASE_URL}/api/${TENANT_SLUG}`,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

// Uploads
export const uploadFile = (formData, onProgress) =>
  api.post("/uploads/", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (e) => onProgress?.(Math.round((e.loaded * 100) / e.total)),
  });

export const getUploads = (params = {}) =>
  api.get("/uploads/", { params });

export const getUploadDetail = (id) =>
  api.get(`/uploads/${id}/`);

// Records
export const getRecords = (params = {}) =>
  api.get("/records/", { params });

export const getFlaggedRecords = (params = {}) =>
  api.get("/records/flagged/", { params });

export const getRecordDetail = (id) =>
  api.get(`/records/${id}/`);

// Approval workflow
export const approveRecord = (id, data = {}) =>
  api.post(`/records/${id}/approve/`, data);

export const rejectRecord = (id, data) =>
  api.post(`/records/${id}/reject/`, data);

export const bulkApprove = (record_ids, analyst_note = "") =>
  api.post("/records/bulk-approve/", { record_ids, analyst_note });
