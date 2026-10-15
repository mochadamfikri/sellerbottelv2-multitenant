import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";

const filters = ["all", "PAYMENT_PENDING", "WAITING_OWNER", "DONE", "REJECTED", "PAYMENT_EXPIRED"];
const rupiah = (value) => `Rp${Number(value || 0).toLocaleString("id-ID")}`;

export default function MuseClaims() {
  const [status, setStatus] = useState("all");
  const [claims, setClaims] = useState([]);
  const load = useCallback(() => api.get("/admin/promo-muse/claims", { params: { status } }).then(({ data }) => setClaims(data)), [status]);
  useEffect(() => { load().catch(() => toast.error("Gagal memuat claim Muse.")); }, [load]);
  const action = async (claim, name) => {
    if (!window.confirm(`${name === "done" ? "Selesaikan" : "Tolak"} claim ${claim.claim_id}?`)) return;
    try { await api.post(`/admin/promo-muse/claims/${claim.claim_id}/${name}`); toast.success("Claim diperbarui."); load(); }
    catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Claim tidak dapat diperbarui."); }
  };
  return <div className="space-y-4">
    <div className="flex flex-wrap gap-2">{filters.map((item) => <button key={item} onClick={() => setStatus(item)} className={status === item ? "px-3 py-1.5 rounded-lg border border-cyan-500/40 text-cyan-400 text-xs" : "px-3 py-1.5 rounded-lg border border-slate-800 text-slate-400 text-xs"}>{item === "all" ? "Semua" : item.replaceAll("_", " ")}</button>)}</div>
    <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-x-auto"><table className="w-full min-w-[1300px] text-sm"><thead className="bg-slate-950/70 text-slate-400 text-xs"><tr>{["Claim ID", "Username", "User ID", "Referral", "Harga", "Fee", "Admin", "Kode", "Total", "Pembayaran", "Status", "Dibuat", "Aksi"].map((h) => <th key={h} className="text-left px-3 py-3 font-medium">{h}</th>)}</tr></thead><tbody>{claims.map((claim) => <tr key={claim.claim_id} className="border-t border-slate-800"><td className="px-3 py-3 font-mono text-xs">{claim.claim_id}</td><td className="px-3 py-3">{claim.telegram_username ? `@${claim.telegram_username}` : "-"}</td><td className="px-3 py-3 font-mono">{claim.telegram_user_id}</td><td className="px-3 py-3"><button className="text-cyan-400" onClick={() => navigator.clipboard?.writeText(claim.referral_code || "")}>{claim.referral_code || "-"}</button></td><td className="px-3 py-3">{rupiah(claim.base_price_idr)}</td><td className="px-3 py-3">{rupiah(claim.percentage_fee_idr)}</td><td className="px-3 py-3">{rupiah(claim.admin_fee_idr)}</td><td className="px-3 py-3">{rupiah(claim.unique_code_idr)}</td><td className="px-3 py-3 font-semibold">{rupiah(claim.final_amount_idr)}</td><td className="px-3 py-3">{claim.payment_status}</td><td className="px-3 py-3">{claim.status}</td><td className="px-3 py-3 text-xs">{claim.created_at}</td><td className="px-3 py-3 whitespace-nowrap">{claim.status === "WAITING_OWNER" && <><button className="mr-2 text-emerald-400" onClick={() => action(claim, "done")}>Selesai</button><button className="text-rose-400" onClick={() => action(claim, "reject")}>Reject</button></>}</td></tr>)}{!claims.length && <tr><td colSpan="13" className="px-4 py-10 text-center text-slate-500">Tidak ada claim.</td></tr>}</tbody></table></div>
  </div>;
}
