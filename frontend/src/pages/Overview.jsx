import { useEffect, useState } from "react";
import { DollarSign, ShoppingBag, Coins, Clock, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import api, { fmtUSD, fmtIDR, fmtAmount, fmtDate, formatApiErrorDetail } from "../lib/api";
import { StatusBadge } from "../components/StatusBadge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";

const StatCard = ({ icon: Icon, label, usd, idr, value, accent, testId }) => (
  <div data-testid={testId} className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 relative overflow-hidden">
    <div className={"absolute top-0 left-0 w-full h-0.5 " + accent} />
    <div className="flex items-center gap-2 text-slate-400 text-xs uppercase tracking-widest mb-3"><Icon size={14} /> {label}</div>
    {value !== undefined
      ? <p className="font-mono text-3xl font-bold">{value}</p>
      : <>
        <p className="font-mono text-2xl font-bold">{fmtUSD(usd)}</p>
        <p className="font-mono text-sm text-slate-400 mt-1">{fmtIDR(idr)}</p>
      </>}
  </div>
);

export default function Overview() {
  const [stats, setStats] = useState(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [resetting, setResetting] = useState(false);

  const load = () => api.get("/admin/stats").then(({ data }) => setStats(data));

  useEffect(() => { load().catch(() => {}); }, []);

  const resetStats = async () => {
    if (!password) {
      toast.error("Password admin wajib diisi.");
      return;
    }
    setResetting(true);
    try {
      await api.post("/admin/stats/reset", { password });
      toast.success("Statistik transaksi berhasil di-reset.");
      setPassword("");
      setResetOpen(false);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Reset statistik gagal.");
    } finally {
      setResetting(false);
    }
  };

  if (!stats) return <p className="text-slate-500 text-sm">Memuat...</p>;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm text-slate-400">Ringkasan operasional toko</p>
          {stats.stats_reset_at && <p className="text-xs text-slate-600 mt-1">Statistik transaksi dihitung sejak {fmtDate(stats.stats_reset_at)}</p>}
        </div>
        <button
          onClick={() => setResetOpen(true)}
          className="inline-flex items-center gap-2 rounded-lg border border-rose-500/20 bg-rose-500/5 px-3 py-2 text-xs font-semibold text-rose-400 hover:bg-rose-500/10"
        >
          <RotateCcw size={14} /> Reset Statistik
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard icon={DollarSign} label="Total Deposit" usd={stats.total_deposit_usd} idr={stats.total_deposit_idr} accent="bg-cyan-400" testId="stat-total-deposit" />
        <StatCard icon={ShoppingBag} label="Total Penjualan" usd={stats.total_sales_usd} idr={stats.total_sales_idr} accent="bg-emerald-400" testId="stat-total-sales" />
        <StatCard icon={Coins} label="Saldo Beredar" usd={stats.circulating_usd} idr={stats.circulating_idr} accent="bg-amber-400" testId="stat-circulating-balance" />
        <StatCard icon={Clock} label="Deposit Pending" value={stats.pending_deposits} accent="bg-rose-400" testId="stat-pending-deposits" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <h2 className="font-heading font-semibold text-slate-200 mb-4">Deposit Terbaru</h2>
          {stats.recent_deposits.length === 0 ? (
            <p className="text-sm text-slate-500">Belum ada deposit pada periode statistik saat ini.</p>
          ) : (
            <div className="space-y-2.5">
              {stats.recent_deposits.map((d) => (
                <div key={d._id} className="flex items-center justify-between text-sm bg-slate-950/60 rounded-lg px-3 py-2.5 border border-slate-800/60">
                  <div>
                    <p className="text-slate-200">{d.first_name || d.username || d.user_tid} <span className="text-slate-500 font-mono text-xs">({d.method === "crypto" ? (d.coin + "/" + d.network) : d.method === "gopay" ? "QRIS" : "Bank"})</span></p>
                    <p className="text-xs text-slate-500">{fmtDate(d.created_at)}</p>
                  </div>
                  <div className="text-right">
                    <p className="font-mono font-semibold">{fmtAmount(d.credited_amount || d.amount, d.currency)}</p>
                    <StatusBadge status={d.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
          <h2 className="font-heading font-semibold text-slate-200">Status Sistem</h2>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between"><span className="text-slate-400">Kurs USD→IDR</span><span className="font-mono text-cyan-400">{fmtIDR(stats.rate)}</span></div>
            <div className="flex justify-between"><span className="text-slate-400">Mode Kurs</span><span className="font-mono">{stats.rate_mode === "auto" ? "Otomatis" : "Manual"}</span></div>
            <div className="flex justify-between"><span className="text-slate-400">Total Pengguna</span><span className="font-mono">{stats.users_count}</span></div>
            <div className="flex justify-between"><span className="text-slate-400">Total Produk</span><span className="font-mono">{stats.products_count}</span></div>
          </div>
        </div>
      </div>

      <Dialog open={resetOpen} onOpenChange={(v) => { setResetOpen(v); if (!v) setPassword(""); }}>
        <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-sm">
          <DialogHeader><DialogTitle>Reset Seluruh Statistik</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-slate-400">Reset ini tidak menghapus user, product, saldo, atau riwayat. Dashboard transaksi mulai menghitung dari waktu reset.</p>
            <div>
              <label className="text-xs text-slate-400">Password Admin</label>
              <input type="password" autoFocus className="mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") resetStats(); }} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button onClick={() => { setResetOpen(false); setPassword(""); }} className="rounded-lg border border-slate-800 text-slate-300 py-2.5">Cancel</button>
              <button onClick={resetStats} disabled={resetting || !password} className="rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-semibold py-2.5 disabled:opacity-50">{resetting ? "Memproses..." : "Yes, Reset"}</button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
