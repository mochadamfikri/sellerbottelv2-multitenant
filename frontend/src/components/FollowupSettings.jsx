import { useEffect, useState } from "react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";

const cls = "w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100";
export default function FollowupSettings() {
  const [config, setConfig] = useState(null);
  const [catalogs, setCatalogs] = useState([]);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");
  const loadHistory = () => api.get("/admin/bot-moderation/followup/history").then(({ data }) => setHistory(data));
  useEffect(() => {
    Promise.all([api.get("/admin/bot-moderation/followup/config"), api.get("/admin/catalogs")]).then(([settings, choices]) => {
      setConfig({ ...settings.data, channel_text: settings.data.channel_ids.join("\n"), user_text: settings.data.exempt_user_ids.join("\n") });
      setCatalogs(choices.data);
    }).catch(() => toast.error("Pengaturan tindak lanjut gagal dimuat."));
    loadHistory().catch(() => {});
  }, []);
  const save = async () => {
    const ids = config.user_text.split(/[\s,]+/).filter(Boolean);
    if (ids.some((id) => !/^\d+$/.test(id))) { toast.error("Pengecualian pengguna harus berupa ID Telegram numerik."); return; }
    setBusy(true);
    try {
      await api.put("/admin/bot-moderation/followup/config", { ...config, channel_ids: config.channel_text.split(/[\n,]+/).map((v) => v.trim()).filter(Boolean), exempt_user_ids: ids.map(Number) });
      toast.success("Pengaturan tindak lanjut disimpan.");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Pengaturan gagal disimpan."); }
    finally { setBusy(false); }
  };
  if (!config) return <p className="text-sm text-slate-500">Memuat pengaturan tindak lanjut…</p>;
  const toggle = (field, value) => setConfig({ ...config, [field]: config[field].includes(value) ? config[field].filter((item) => item !== value) : [...config[field], value] });
  return <section className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
    <h2 className="font-semibold">Tindak lanjut setelah pesanan selesai</h2>
    <select aria-label="Mode tindak lanjut otomatis" className={cls} value={config.mode} onChange={(e) => setConfig({ ...config, mode: e.target.value })}><option value="none">Tidak ada tindak lanjut otomatis (OFF)</option><option value="kick_block">Auto kick dari channel + blokir akses bot (ON)</option></select>
    <p className="text-xs text-slate-400">Berlaku untuk pesanan yang selesai setelah fitur diaktifkan. Sistem menunggu pengiriman dan pesanan lain yang masih berjalan. Pesan berisi produk tidak dihapus. Kick mengeluarkan pengguna dari channel; silent block menghentikan respons bot.</p>
    <label className="block text-sm">Channel untuk kick (satu ID atau @username per baris)<textarea rows={2} className={`${cls} mt-1`} placeholder="-1001234567890" value={config.channel_text} onChange={(e) => setConfig({ ...config, channel_text: e.target.value })}/></label>
    <p className="text-xs text-slate-500">Bot harus menjadi admin channel dengan izin membatasi anggota. Admin channel tidak akan dikeluarkan.</p>
    <details className="rounded-lg border border-slate-700 p-3" open><summary className="cursor-pointer font-semibold">Pengecualian otomatis</summary><p className="my-3 text-xs text-slate-400">Jika salah satu pengecualian cocok, pengguna tidak di-kick atau diblokir otomatis. Pada pesanan campuran, satu produk yang dikecualikan sudah cukup. Admin utama selalu dikecualikan.</p>
      <label className="block text-sm">ID Telegram yang dikecualikan<textarea rows={2} className={`${cls} mt-1`} value={config.user_text} onChange={(e) => setConfig({ ...config, user_text: e.target.value })}/></label>
      <label className="my-3 flex gap-2 text-sm"><input type="checkbox" checked={config.exempt_resellers} onChange={(e) => setConfig({ ...config, exempt_resellers: e.target.checked })}/> Kecualikan pemilik reseller dan pesanan reseller</label>
      <div className="grid gap-3 sm:grid-cols-2"><div><p className="mb-2 text-sm">Katalog yang dikecualikan</p><div className="max-h-40 space-y-2 overflow-auto">{catalogs.map((c) => <label key={c.name} className="flex gap-2 text-sm"><input type="checkbox" checked={config.exempt_catalogs.includes(c.name)} onChange={() => toggle("exempt_catalogs", c.name)}/>{c.name}</label>)}</div></div><div><p className="mb-2 text-sm">Produk yang dikecualikan</p><input className={cls} placeholder="Filter nama produk" value={filter} onChange={(e) => setFilter(e.target.value)}/><div className="mt-2 max-h-40 space-y-2 overflow-auto">{catalogs.flatMap((c) => c.products).filter((p) => p.name.toLowerCase().includes(filter.toLowerCase())).map((p) => <label key={p._id} className="flex gap-2 text-sm"><input type="checkbox" checked={config.exempt_product_ids.includes(p._id)} onChange={() => toggle("exempt_product_ids", p._id)}/>{p.name}</label>)}</div></div></div>
    </details>
    <button disabled={busy} onClick={save} className="rounded-lg bg-cyan-700 px-4 py-2 text-sm disabled:opacity-40">Simpan tindak lanjut & pengecualian</button>
    <details><summary className="cursor-pointer text-sm">Riwayat otomatis ({history.length})</summary><button className="my-3 text-xs text-cyan-400" onClick={() => loadHistory().catch(() => toast.error("Riwayat gagal dimuat."))}>Muat ulang</button><div className="max-h-64 space-y-2 overflow-auto">{history.map((row) => <div key={row._id} className="rounded border border-slate-800 p-2 text-xs"><b>{row.invoice_id || row._id}</b> · {row.telegram_id} · {row.status}<p className="text-slate-400">{row.reason || ""}</p>{(row.channel_results || []).map((result) => <p key={result.channel} className={result.ok ? "text-emerald-400" : "text-amber-400"}>{result.channel}: {result.ok ? "berhasil" : result.error}</p>)}</div>)}</div></details>
  </section>;
}
