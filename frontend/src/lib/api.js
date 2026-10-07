import axios from "axios";

const api = axios.create({
  baseURL: process.env.REACT_APP_BACKEND_URL
    ? `${process.env.REACT_APP_BACKEND_URL.replace(/\/$/, "")}/api`
    : "/api",
  withCredentials: true,
});

export function formatApiErrorDetail(detail) {
  if (detail == null) return "Terjadi kesalahan. Coba lagi.";
  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  }

  if (detail && typeof detail.msg === "string") return detail.msg;

  return String(detail);
}

export const fmtUSD = (v) =>
  `$${Number(v || 0).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

export const fmtIDR = (v) =>
  `Rp ${Number(v || 0).toLocaleString("id-ID", {
    maximumFractionDigits: 0,
  })}`;

export const fmtAmount = (v, cur) =>
  cur === "USD" ? fmtUSD(v) : fmtIDR(v);

export const fmtDate = (iso) =>
  iso
    ? new Date(iso).toLocaleString("id-ID", {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "-";

export default api;
