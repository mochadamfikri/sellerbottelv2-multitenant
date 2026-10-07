import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { Check, X, Eye, Ban, ExternalLink } from "lucide-react";
import api, { fmtAmount, fmtDate, formatApiErrorDetail } from "../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { StatusBadge } from "../components/StatusBadge";

const FILTERS = [
  { key: "all", label: "Semua" }, { key: "pending", label: "Pending" },
  { key: "approved", label: "Disetujui" }, { key: "rejected", label: "Ditolak" },
  { key: "cancelled", label: "Dibatalkan" },
];

const explorer = (d) => {
  if (!d.tx_hash) return null;
  const map = { SOL: `https://solscan.io/tx/${d.tx_hash}`, POL: `https://polygonscan.com/tx/${d.tx_hash}`, BNB: `https://bscscan.com/tx/${d.tx_hash}`, AVAX: `https://snowtrace.io/tx/${d.tx_hash}` };
  return map[d.network];
};

export default function Deposits() {
  const [filter, setFilter] = useState("pending");
  const [deposits, setDeposits] = useState([]);
  const [proofUrl, setProofUrl] = useState(null);
  const [decision, setDecision] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.get(`/admin/deposits?status=${filter}`).then(({ data }) => setDeposits(data)), [filter]);
  useEffect(() => { load(); }, [load]);

  const viewProof = async (d) => {
    try {
      const res = await api.get(`/admin/deposits/${d._id}/proof`, { responseType: "blob" });
      setProofUrl(URL.createObjectURL(res.data));
    } catch {
      toast.error("Gagal memuat bukti");
    }
  };

  const decide = async () => {
    setBusy(true);
    try {
      await api.post(`/admin/deposits/${decision.dep._id}/${decision.action}`, { note });
      toast.success(decision.action === "approve" ? "Deposit disetujui, saldo pengguna bertambah" : "Deposit ditolak");
      setDecision(null); setNote("");
      load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
    setBusy(false);
  };

  const cancel = async (d) => {
    if (!window.confirm("Batalkan deposit ini? Saldo pengguna akan dikurangi.")) return;
    try {
      await api.post(`/admin/deposits/${d._id}/cancel`);
      toast.success("Deposit dibatalkan");
      load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  return (
    <>
      <div className="flex gap-2 flex-wrap">
        {FILTERS.map((f) => (
          <button key={f.key} data-testid={`filter-deposit-${f.key}`} onClick={() => setFilter(f.key)}
            className={`px-3.5 py-1.5 rounded-lg text-sm border transition-colors ${filter === f.key ? "bg-cyan-500/10 border-cyan-500/40 text-cyan-400" : "border-slate-800 text-slate-400 hover:text-slate-200"}`}>
            {f.label}
          </button>
        ))}
      </div>

      <div data-testid="deposit-list-table" className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-xs text-slate-500 uppercase tracking-wide">
              <th className="px-4 py-3">Pengguna</th><th className="px-4 py-3">Metode</th>
              <th className="px-4 py-3">Jumlah</th><th className="px-4 py-3">Bukti</th>
              <th className="px-4 py-3">Status</th><th className="px-4 py-3">Tanggal</th><th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {deposits.map((d) => (
              <tr key={d._id} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                <td className="px-4 py-3">
                  <p className="text-slate-200">{d.first_name || "-"}</p>
                  <p className="text-xs text-slate-500 font-mono">{d.username ? `@${d.username}` : d.user_tid}</p>
                </td>
                <td className="px-4 py-3 text-slate-300">{d.method === "crypto" ? `${d.coin} / ${d.network}` : d.method === "gopay" ? "GoPay QR" : "Transfer Bank"}
                  {d.auto_verified && <span className="block text-[10px] text-emerald-400">auto on-chain ✓</span>}
                </td>
                <td className="px-4 py-3 font-mono font-semibold">{fmtAmount(d.credited_amount || d.amount, d.currency)}</td>
                <td className="px-4 py-3">
                  {d.tx_hash ? (
                    <a href={explorer(d)} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-cyan-400 hover:underline font-mono text-xs">
                      {d.tx_hash.slice(0, 10)}... <ExternalLink size={11} />
                    </a>
                  ) : (d.proof_file_id || d.proof_storage_path) ? (
                    <button data-testid={`view-proof-btn-${d._id}`} onClick={() => viewProof(d)} className="flex items-center gap-1 text-cyan-400 hover:underline text-xs">
                      <Eye size={13} /> Lihat foto
                    </button>
                  ) : <span className="text-slate-600 text-xs">-</span>}
                </td>
                <td className="px-4 py-3"><StatusBadge status={d.status} /></td>
                <td className="px-4 py-3 text-xs text-slate-500">{fmtDate(d.created_at)}</td>
                <td className="px-4 py-3 text-right">
                  {d.status === "pending" && (
                    <div className="flex gap-1.5 justify-end">
                      <button data-testid={`approve-deposit-btn-${d._id}`} onClick={() => { setDecision({ dep: d, action: "approve" }); setNote(""); }}
                        className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/20"><Check size={15} /></button>
                      <button data-testid={`reject-deposit-btn-${d._id}`} onClick={() => { setDecision({ dep: d, action: "reject" }); setNote(""); }}
                        className="p-2 rounded-lg bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border border-rose-500/20"><X size={15} /></button>
                    </div>
                  )}
                  {d.status === "approved" && (
                    <button data-testid={`cancel-deposit-btn-${d._id}`} onClick={() => cancel(d)} title="Batalkan"
                      className="p-2 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-slate-800"><Ban size={15} /></button>
                  )}
                </td>
              </tr>
            ))}
            {deposits.length === 0 && <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-500">Tidak ada deposit.</td></tr>}
          </tbody>
        </table>
      </div>

      <Dialog open={!!proofUrl} onOpenChange={() => { if (proofUrl) URL.revokeObjectURL(proofUrl); setProofUrl(null); }}>
        <DialogContent className="bg-slate-900 border-slate-800 max-w-lg">
          <DialogHeader><DialogTitle className="text-slate-100 font-heading">Bukti Transfer</DialogTitle></DialogHeader>
          {proofUrl && <img src={proofUrl} alt="Bukti transfer" className="w-full rounded-lg" />}
        </DialogContent>
      </Dialog>

      <Dialog open={!!decision} onOpenChange={() => setDecision(null)}>
        <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-sm">
          <DialogHeader><DialogTitle className="font-heading">{decision?.action === "approve" ? "Setujui Deposit" : "Tolak Deposit"}</DialogTitle></DialogHeader>
          {decision && (
            <div className="space-y-3">
              <p className="text-sm text-slate-300">
                {fmtAmount(decision.dep.amount, decision.dep.currency)} dari {decision.dep.first_name || decision.dep.user_tid}
              </p>
              <textarea data-testid="decision-note-input" placeholder="Catatan (opsional)" rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-cyan-500/60" />
              <button data-testid="confirm-decision-button" onClick={decide} disabled={busy}
                className={`w-full text-white text-sm font-semibold rounded-lg py-2.5 transition-colors disabled:opacity-50 ${decision.action === "approve" ? "bg-emerald-600 hover:bg-emerald-700" : "bg-rose-600 hover:bg-rose-700"}`}>
                {busy ? "Memproses..." : decision.action === "approve" ? "Setujui & Tambah Saldo" : "Tolak Deposit"}
              </button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
