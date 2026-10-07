const styles = {
  pending: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  approved: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  rejected: "bg-rose-500/15 text-rose-400 border-rose-500/30",
  cancelled: "bg-slate-500/15 text-slate-400 border-slate-500/30",
};
const labels = { pending: "Pending", approved: "Disetujui", rejected: "Ditolak", cancelled: "Dibatalkan" };

export const StatusBadge = ({ status }) => (
  <span className={`inline-block text-[10px] font-mono uppercase tracking-wide px-2 py-0.5 rounded border ${styles[status] || styles.cancelled}`}>
    {labels[status] || status}
  </span>
);
