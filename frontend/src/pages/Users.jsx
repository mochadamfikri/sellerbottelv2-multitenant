import { useCallback, useEffect, useRef, useState } from "react";
import { Wallet, Snowflake, Sun, Search, UserRoundCheck, Globe, Send, Link2, Users, LoaderCircle } from "lucide-react";
import { toast } from "sonner";
import api, { fmtUSD, fmtIDR, fmtDate, formatApiErrorDetail } from "../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";

import BalanceAdjustment from "../components/BalanceAdjustment";

const cls = "w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";

export default function UsersPage() {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("all");
  const [page, setPage] = useState(1);
  const [directory, setDirectory] = useState({ total: 0, pages: 1, source_counts: {} });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const latestRequest = useRef(0);
  const sourceLabels = { telegram: "Telegram", web: "Website", linked: "Web + Telegram" };
  const [adjust, setAdjust] = useState(null);
  const [freeze, setFreeze] = useState(null);
  const [freezeReason, setFreezeReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (term = "") => {
    const request = ++latestRequest.current;
    setLoading(true); setLoadError("");
    try {
      const { data } = await api.get("/admin/user-directory", { params: { search: term.trim(), source, page, page_size: 25 } });
      if (request !== latestRequest.current) return;
      setUsers(data.items); setDirectory(data);
    } catch (err) {
      if (request === latestRequest.current) setLoadError(formatApiErrorDetail(err.response?.data?.detail) || "Gagal memuat pengguna.");
    } finally { if (request === latestRequest.current) setLoading(false); }
  }, [source, page]);

  useEffect(() => {
    const timer = setTimeout(() => load(search), 250);
    return () => { clearTimeout(timer); latestRequest.current += 1; };
  }, [search, load]);

  const doFreeze = async () => {
    setBusy(true);
    try {
      await api.post("/admin/users/" + freeze.telegram_id + "/freeze", { reason: freezeReason });
      toast.success("Pengguna dibekukan");
      setFreeze(null);
      setFreezeReason("");
      await load(search);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  const doJoinGroup = async (u) => {
    try {
      const { data } = await api.post("/admin/users/" + u.telegram_id + "/join-group");
      if (data.ok) toast.success(data.message || "Akun diproses untuk join group.");
      else toast.error(data.message || "Gagal join group.");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal join group.");
    }
  };

  const doUnfreeze = async (u) => {
    try {
      await api.post("/admin/users/" + u.telegram_id + "/unfreeze");
      toast.success("Blokir dibuka");
      await load(search);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  return (
    <div className="space-y-4">
      <div><h2 className="text-xl font-bold text-slate-100">Direktori pengguna</h2><p className="mt-1 text-sm text-slate-400">Akun web dan Telegram dalam satu daftar. Akun tertaut ditampilkan sekali.</p></div>
      <div role="group" aria-label="Filter sumber pengguna" className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[["all","Semua pengguna",Users],["telegram","Telegram saja",Send],["web","Website saja",Globe],["linked","Web + Telegram",Link2]].map(([key,label,Icon]) => <button key={key} aria-pressed={source === key} onClick={() => { setSource(key); setPage(1); }} className={`flex items-center gap-3 rounded-xl border p-4 text-left transition ${source === key ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-300" : "border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-600"}`}><Icon size={21}/><span><span className="block text-xs font-medium">{label}</span><b className="mt-1 block text-xl">{directory.source_counts[key] ?? "—"}</b></span></button>)}</div>
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
        <label className="text-xs text-slate-400">Cari pengguna</label>
        <div className="relative mt-1">
          <Search size={16} className="absolute left-3 top-2.5 text-slate-600" />
          <input
            className={cls + " pl-9"}
            placeholder="Email, nama, @username, atau ID Telegram"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          />
        </div>
        <p className="text-xs text-slate-600 mt-2">Cari berdasarkan email, nama, @username, Telegram ID, atau ID internal.</p>
        <p className="text-xs text-slate-500 mt-1">{directory.total} pengguna cocok · {users.length} ditampilkan pada halaman ini</p>
      </div>

      {loadError && <div role="alert" className="flex items-center justify-between gap-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">{loadError}<button onClick={() => load(search)} className="font-semibold underline">Coba lagi</button></div>}
      {loading && <p role="status" className="flex items-center gap-2 text-sm text-slate-400"><LoaderCircle size={16} className="animate-spin"/> Memuat pengguna…</p>}
      <div aria-busy={loading} className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-xs text-slate-500 uppercase tracking-wide">
              <th className="px-4 py-3">Nama</th>
              <th className="px-4 py-3">Username</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Telegram ID</th>
              <th className="px-4 py-3">USD</th>
              <th className="px-4 py-3">IDR</th>
              <th className="px-4 py-3">Order</th>
              <th className="px-4 py-3">Sumber akun</th>
              <th className="px-4 py-3">Telegram</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Bergabung</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u._id} className="border-b border-slate-800/60 hover:bg-slate-800/20">
                <td className="px-4 py-3 text-slate-200">{u.first_name || "-"}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-400">{u.username ? "@" + u.username : "—"}</td>
                <td className="px-4 py-3 text-xs text-slate-300">{u.email || "—"}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-300">{u.telegram_id || "—"}</td>
                <td className="px-4 py-3 font-mono">{fmtUSD(u.balance_usd)}</td>
                <td className="px-4 py-3 font-mono">{fmtIDR(u.balance_idr)}</td>
                <td className="px-4 py-3 font-mono text-slate-400">{u.order_count || u.purchase_count || 0}</td>
                <td className="px-4 py-3 text-xs text-slate-400">{sourceLabels[u.source] || "Telegram"}</td>
                <td className="px-4 py-3 text-xs text-slate-400">{u.telegram_id ? (u.username ? `Connected · @${u.username}` : "Connected") : "Not connected"}</td>
                <td className="px-4 py-3">
                  {u.frozen
                    ? <span className="text-[10px] uppercase px-2 py-0.5 rounded border bg-red-500/15 text-red-400 border-red-500/30">Dibekukan</span>
                    : <span className="text-[10px] uppercase px-2 py-0.5 rounded border bg-cyan-500/15 text-cyan-400 border-cyan-500/30">Aktif</span>}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">{fmtDate(u.created_at)}</td>
                <td className="px-4 py-3 text-right">
                  <div className="flex justify-end gap-1.5">
                    <button onClick={() => setAdjust(u)} title="Sesuaikan saldo" className="p-2 rounded-lg text-slate-400 hover:text-cyan-400 hover:bg-slate-800"><Wallet size={15} /></button>
                    {u.telegram_account_connected && (
                      <button onClick={() => doJoinGroup(u)} title="Join Group dengan akun Telegram terhubung" className="p-2 rounded-lg text-slate-400 hover:text-violet-400 hover:bg-slate-800"><UserRoundCheck size={15} /></button>
                    )}
                    {u.telegram_id && (u.frozen
                      ? <button onClick={() => doUnfreeze(u)} title="Buka blokir" className="p-2 rounded-lg text-emerald-400 hover:bg-emerald-500/10"><Sun size={15} /></button>
                      : <button onClick={() => { setFreeze(u); setFreezeReason(""); }} title="Bekukan" className="p-2 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800"><Snowflake size={15} /></button>)}
                  </div>
                </td>
              </tr>
            ))}
            {!loading && !users.length && <tr><td colSpan={12} className="px-4 py-10 text-center text-slate-500">Tidak ada pengguna yang cocok.</td></tr>}
          </tbody>
        </table>
      </div>

      <nav aria-label="Halaman pengguna" className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-400"><span>Halaman {directory.page || 1} dari {directory.pages}</span><div className="flex gap-2"><button disabled={loading || (directory.page || 1) <= 1} onClick={() => setPage((directory.page || 1)-1)} className="rounded-lg border border-slate-700 px-4 py-2 disabled:opacity-35">Sebelumnya</button><button disabled={loading || (directory.page || 1) >= directory.pages} onClick={() => setPage((directory.page || 1)+1)} className="rounded-lg border border-slate-700 px-4 py-2 disabled:opacity-35">Berikutnya</button></div></nav>

      <BalanceAdjustment user={adjust} close={() => setAdjust(null)} refresh={() => load(search)} />

      <Dialog open={!!freeze} onOpenChange={() => setFreeze(null)}>
        <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-sm">
          <DialogHeader><DialogTitle>Bekukan Pengguna</DialogTitle></DialogHeader>
          {freeze && (
            <div className="space-y-3">
              <p className="text-sm text-slate-400">{freeze.first_name || "-"} · {freeze.username ? "@" + freeze.username : "—"} · {freeze.telegram_id}</p>
              <textarea rows={3} className={cls} placeholder="Alasan (opsional, dikirim ke pengguna)" value={freezeReason} onChange={(e) => setFreezeReason(e.target.value)} />
              <button onClick={doFreeze} disabled={busy} className="w-full bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white font-semibold rounded-lg py-2.5">{busy ? "Memproses..." : "Bekukan Akun"}</button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
