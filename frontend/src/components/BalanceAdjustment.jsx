import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { fmtIDR, fmtUSD, fmtDate, formatApiErrorDetail } from "../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "./ui/dialog";

const cls = "w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100";
const blank = () => ({ direction: "ADD", currency: "IDR", amount: "", reason: "", request_id: crypto.randomUUID() });
export default function BalanceAdjustment({ user, close, refresh }) {
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const [balances, setBalances] = useState({});
  const target = user?.wallet_target || (user?.customer_id ? `store:${user.customer_id}` : `bot:${user?._id}`);
  const url = `/admin/wallets/${encodeURIComponent(target)}`;
  useEffect(() => {
    if (!user) return;
    setForm(blank()); setHistory([]); setError("");
    setBalances({ IDR: user.balance_idr || 0, USD: user.balance_usd || 0 });
    let alive = true;
    api.get(`${url}/history`).then(({ data }) => { if (alive) setHistory(data); }).catch(() => { if (alive) setError("Riwayat gagal dimuat. Tutup dan buka kembali untuk mencoba lagi."); });
    return () => { alive = false; };
  }, [user, url]);
  const change = (key, value) => setForm({ ...form, [key]: value });
  const save = async (e) => {
    e.preventDefault(); if (busy) return;
    setBusy(true); setError("");
    try {
      const { data } = await api.post(`${url}/adjust`, { ...form, amount: Number(form.amount) });
      setBalances((old) => ({ ...old, [form.currency]: data.balance }));
      setHistory((old) => [data.adjustment, ...old.filter(r => r._id !== data.adjustment._id)]);
      setForm(blank()); toast.success("Saldo dan audit tersimpan"); refresh();
    } catch (err) { setError(formatApiErrorDetail(err.response?.data?.detail) || "Belum ada konfirmasi. Coba ulang tanpa mengubah formulir agar request tetap sama."); }
    finally { setBusy(false); }
  };
  return <Dialog open={!!user} onOpenChange={(open) => { if (!open && !busy) close(); }}><DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto border-slate-800 bg-slate-900 text-slate-100"><DialogHeader><DialogTitle>Adjust Saldo & Riwayat</DialogTitle></DialogHeader>{user && <>
    <div className="text-sm"><b>{user.first_name || user.email || "Pengguna"}</b><p>{user.email || (user.username ? `@${user.username}` : user.telegram_id)}</p><p className="text-slate-400">Sumber: {user.source === "web" ? "WEB" : user.source === "linked" ? "WEB + BOT (wallet Telegram)" : "BOT"}</p><p className="mt-2">Saldo sekarang: <b>{fmtIDR(balances.IDR)}</b> · {fmtUSD(balances.USD)}</p></div>
    <form onSubmit={save} className="space-y-3"><div className="grid grid-cols-2 gap-3"><label className="text-xs">Jenis<select aria-label="Jenis" disabled={busy} className={cls} value={form.direction} onChange={e => change("direction",e.target.value)}><option value="ADD">Tambah Saldo</option><option value="SUBTRACT">Kurangi Saldo</option></select></label><label className="text-xs">Mata uang<select aria-label="Mata uang" disabled={busy} className={cls} value={form.currency} onChange={e => change("currency",e.target.value)}><option>IDR</option><option>USD</option></select></label></div>
    <label className="block text-xs">Jumlah<input required disabled={busy} type="number" min={form.currency === "IDR" ? 1 : 0.01} max={1000000000} step={form.currency === "IDR" ? 1 : 0.01} className={cls} value={form.amount} onChange={e => change("amount",e.target.value)}/></label>
    <label className="block text-xs">Catatan<textarea required disabled={busy} maxLength={500} className={cls} value={form.reason} onChange={e => change("reason",e.target.value)}/></label>
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}<div className="flex gap-2"><button disabled={busy || !(Number(form.amount)>0) || !form.reason.trim()} className="rounded-lg bg-cyan-600 px-4 py-2 disabled:opacity-40">{busy ? "Menyimpan…" : "Konfirmasi"}</button><button type="button" disabled={busy} onClick={close} className="rounded-lg border border-slate-700 px-4 py-2">Tutup</button></div></form>
    <section className="border-t border-slate-700 pt-4"><h3 className="font-semibold">Riwayat penyesuaian manual</h3><p className="mb-3 text-xs text-slate-400">Terpisah dari deposit gateway dan pembelian pelanggan.</p>{!history.length && <p className="text-sm text-slate-500">Belum ada penyesuaian.</p>}{history.map(row => <div key={row._id} className="mb-2 rounded-lg bg-slate-950 p-3 text-sm"><b>{row.amount >= 0 ? "+ " : "− "}{row.currency === "IDR" ? fmtIDR(Math.abs(row.amount)) : fmtUSD(Math.abs(row.amount))}</b><p>Manual Balance Adjustment · {fmtDate(row.created_at)}</p><p className="text-slate-400">Admin: {row.admin_id || "Legacy"} · {row.reason || "Tanpa catatan lama"}</p>{row.balance_before != null && <p className="text-xs text-slate-500">Saldo: {row.balance_before} → {row.balance_after} {row.currency}</p>}</div>)}</section>
  </>}</DialogContent></Dialog>;
}
