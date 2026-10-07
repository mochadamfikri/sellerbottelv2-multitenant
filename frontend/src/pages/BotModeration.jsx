import { useCallback, useEffect, useState } from "react";
import { Ban, Eraser, Search, ShieldOff, Unlock } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";
import FollowupSettings from "../components/FollowupSettings";

const inputClass = "w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";

export default function BotModeration() {
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState("");
  const [blockedOnly, setBlockedOnly] = useState(false);
  const [selected, setSelected] = useState(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleteMessages, setDeleteMessages] = useState(false);
  const [kickChannels, setKickChannels] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/bot-moderation/users", { params: { search, blocked_only: blockedOnly } });
      setUsers(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal memuat pengguna.");
    }
  }, [search, blockedOnly]);

  useEffect(() => {
    const timer = setTimeout(load, 250);
    return () => clearTimeout(timer);
  }, [load]);

  const openUser = async (u) => {
    try {
      const { data } = await api.get("/admin/bot-moderation/users/" + u.telegram_id);
      setSelected(data);
      setReason(data.silent_block_reason || "");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal membuka pengguna.");
    }
  };

  const block = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const { data } = await api.post("/admin/bot-moderation/users/" + selected.telegram_id + "/silent-block", {
        reason,
        delete_tracked_messages: deleteMessages,
        kick_channels: kickChannels,
      });
      toast.success("Silent block aktif. " + data.deletion.deleted + " pesan terlacak dihapus.");
      if (data.channel_results?.some((row) => !row.ok)) toast.error("Sebagian channel gagal mengeluarkan pengguna. Periksa izin bot.");
      await openUser(selected);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal melakukan silent block.");
    } finally { setBusy(false); }
  };

  const unblock = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await api.post("/admin/bot-moderation/users/" + selected.telegram_id + "/unblock");
      toast.success("Silent block dibuka.");
      await openUser(selected);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal membuka blokir.");
    } finally { setBusy(false); }
  };

  const clearMessages = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const { data } = await api.delete("/admin/bot-moderation/users/" + selected.telegram_id + "/messages");
      toast.success(data.deleted + " pesan terlacak dihapus.");
      await openUser(selected);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal menghapus pesan.");
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-5">
      <FollowupSettings/>
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
        <div className="flex flex-col md:flex-row gap-3">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-2.5 text-slate-600" />
            <input className={inputClass + " pl-9"} placeholder="Nama / @username / Telegram ID" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-400 px-2">
            <input type="checkbox" checked={blockedOnly} onChange={(e) => setBlockedOnly(e.target.checked)} />
            Hanya yang diblokir
          </label>
        </div>
        <p className="text-xs text-slate-500 mt-3">Panel ini terpisah dari menu Pengguna. Silent block tidak mengirim pesan atau alasan apa pun ke pengguna.</p>
      </div>

      <div className="grid lg:grid-cols-[1fr_380px] gap-5">
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead><tr className="border-b border-slate-800 text-xs text-slate-500 uppercase"><th className="px-4 py-3">Pengguna</th><th className="px-4 py-3">Telegram ID</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Aksi</th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u._id} className="border-b border-slate-800/60 hover:bg-slate-800/20">
                  <td className="px-4 py-3"><div className="text-slate-200">{u.first_name || "-"}</div><div className="text-xs text-slate-500">{u.username ? "@" + u.username : "—"}</div></td>
                  <td className="px-4 py-3 font-mono text-xs">{u.telegram_id}</td>
                  <td className="px-4 py-3">{u.silent_blocked ? <span className="text-rose-400">Silent blocked</span> : <span className="text-emerald-400">Aktif</span>}</td>
                  <td className="px-4 py-3 text-right"><button onClick={() => openUser(u)} className="text-cyan-400 text-xs">Kelola</button></td>
                </tr>
              ))}
              {!users.length && <tr><td colSpan={4} className="px-4 py-10 text-center text-slate-500">Tidak ada pengguna.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 h-fit">
          {!selected ? <p className="text-sm text-slate-500">Pilih pengguna untuk tindak lanjut bot.</p> : (
            <div className="space-y-4">
              <div><h3 className="font-semibold text-slate-100">{selected.first_name || "-"}</h3><p className="text-xs text-slate-500">{selected.username ? "@" + selected.username : "Tanpa username"} · {selected.telegram_id}</p></div>
              <div className="rounded-lg border border-slate-800 p-3 text-xs text-slate-400">
                Pesan terlacak: <b className="text-slate-200">{selected.tracked_messages}</b><br />
                Status: <b className={selected.silent_blocked ? "text-rose-400" : "text-emerald-400"}>{selected.silent_blocked ? "Silent blocked" : "Aktif"}</b>
              </div>
              <textarea rows={3} className={inputClass} placeholder="Catatan internal (tidak dikirim ke pengguna)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <label className="flex gap-2 text-xs text-slate-400"><input type="checkbox" checked={deleteMessages} onChange={(e) => setDeleteMessages(e.target.checked)}/> Sekaligus hapus pesan terlacak</label>
              <label className="flex gap-2 text-xs text-slate-400"><input type="checkbox" checked={kickChannels} onChange={(e) => setKickChannels(e.target.checked)}/> Sekaligus kick dari channel tindak lanjut</label>
              <p className="text-xs text-slate-500">Tindakan manual tetap bisa dijalankan untuk pengguna yang dikecualikan dari otomatisasi.</p>
              <button onClick={clearMessages} disabled={busy} className="w-full flex items-center justify-center gap-2 border border-amber-500/30 text-amber-400 rounded-lg py-2.5 disabled:opacity-50"><Eraser size={16} /> Hapus Pesan Terlacak</button>
              {selected.silent_blocked
                ? <button onClick={unblock} disabled={busy} className="w-full flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg py-2.5 disabled:opacity-50"><Unlock size={16} /> Buka Silent Block</button>
                : <button onClick={block} disabled={busy} className="w-full flex items-center justify-center gap-2 bg-rose-600 hover:bg-rose-700 text-white rounded-lg py-2.5 disabled:opacity-50"><Ban size={16} /> Jalankan tindak lanjut manual</button>}
              {selected.silent_blocked && kickChannels && <button onClick={block} disabled={busy} className="text-sm text-amber-400">Ulangi kick channel untuk pengguna ini</button>}
              <p className="text-[11px] text-slate-600 flex gap-2"><ShieldOff size={14} className="shrink-0" />Bot hanya dapat menghapus pesan yang ID-nya terlacak dan masih memenuhi batas penghapusan Telegram. Pesan lama yang tidak pernah dicatat backend tidak dapat dipulihkan dari Bot API.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
