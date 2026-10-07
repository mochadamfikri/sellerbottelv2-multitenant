import { useCallback, useEffect, useState } from "react";
import api, { fmtDate, formatApiErrorDetail } from "../lib/api";
import { toast } from "sonner";

const cls = "w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-slate-100";
const initial = () => ({ name: "", channel: "", minimum_interval: 5, maximum_interval: 70, count: 30, product_ids: [], request_id: crypto.randomUUID() });
export default function MarketingCampaigns({ products = [] }) {
  const [form, setForm] = useState(initial), [channels, setChannels] = useState([]);
  const [campaigns, setCampaigns] = useState([]), [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null), [allocations, setAllocations] = useState([]);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [messageId, setMessageId] = useState("");
  const path = "/admin/broadcasts/campaigns";
  const load = useCallback(async () => {
    try {
      const [{ data: list }, { data: options }] = await Promise.all([api.get(path), api.get(`${path}/options`)]);
      setCampaigns(list); setChannels(options.channels);
      if (selected) {
        const [{ data: current }, { data: stock }] = await Promise.all([api.get(`${path}/${encodeURIComponent(selected)}`), api.get(`${path}/${encodeURIComponent(selected)}/allocations`)]);
        setDetail(current); setAllocations(stock);
      }
    } catch (err) { setError(formatApiErrorDetail(err.response?.data?.detail) || "Campaign gagal dimuat"); }
  }, [selected]);
  useEffect(() => { load(); const timer = setInterval(load, 15000); return () => clearInterval(timer); }, [load]);
  const run = async (url, body) => {
    setBusy(true); setError("");
    try { const { data } = await api.post(url, body); await load(); return data; }
    catch (err) { setError(formatApiErrorDetail(err.response?.data?.detail) || "Aksi belum terkonfirmasi; muat ulang atau coba lagi"); return null; }
    finally { setBusy(false); }
  };
  const create = async e => {
    e.preventDefault();
    const data = await run(path, { ...form, channel: form.channel || channels[0] || "", minimum_interval: Number(form.minimum_interval), maximum_interval: Number(form.maximum_interval), count: Number(form.count) });
    if (data) { setForm(initial()); setSelected(data._id); toast.success("Campaign tersimpan; pengiriman pertama mengikuti interval acak"); }
  };
  const act = async action => {
    if (action === "stop" && !window.confirm("Stop membatalkan pengiriman berikutnya. Alokasi lama tetap tersedia untuk restore manual. Lanjutkan?")) return;
    const data = await run(`${path}/${encodeURIComponent(selected)}/action`, { action, ...(action === "confirm_sent" ? { message_id: Number(messageId) } : {}) });
    if (data) setDetail(data);
  };
  const restore = async event_id => {
    const data = await run(`${path}/${encodeURIComponent(selected)}/restore`, { event_id });
    if (data) toast.success(`${data.restored} item dikembalikan. Alokasi event belum terkirim perlu Stop dahulu.`);
  };
  const eligible = products.filter(p => p.active !== false && (p.product_kind === "digital" || p.delivery_type === "inventory" || p.inventory_enabled));
  return <section className="space-y-4 rounded-xl border border-cyan-800/60 bg-slate-900/80 p-5">
    <div className="flex items-center justify-between"><div><h2 className="text-lg font-semibold">Campaign Promo Otomatis</h2><p className="text-xs text-slate-400">PROMO IDSE · Terpisah dari penjualan, pendapatan, dan order pelanggan.</p></div><button type="button" disabled={busy} onClick={load} className="text-sm text-cyan-300">Refresh</button></div>
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    <details><summary className="cursor-pointer font-medium text-cyan-300">Buat campaign</summary><form onSubmit={create} className="mt-4 space-y-3"><label className="block text-xs">Nama campaign<input required maxLength={100} className={cls} value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
      <label className="block text-xs">Channel / grup terkonfigurasi<select required className={cls} value={form.channel || channels[0] || ""} onChange={e=>setForm({...form,channel:e.target.value})}>{!channels.length && <option value="">Atur tujuan broadcast di Pengaturan terlebih dahulu</option>}{channels.map(c=><option key={c}>{c}</option>)}</select></label>
      <div className="grid grid-cols-3 gap-3">{[["minimum_interval","Minimum menit",10080],["maximum_interval","Maksimum menit",10080],["count","Jumlah pesan",500]].map(([key,label,max])=><label key={key} className="text-xs">{label}<input required type="number" min={1} max={max} className={cls} value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}</div>
      <label className="block text-xs">Produk / varian (kosong = semua inventory eligible)<select multiple size={Math.min(5,Math.max(2,eligible.length))} className={cls} value={form.product_ids} onChange={e=>setForm({...form,product_ids:Array.from(e.target.selectedOptions,o=>o.value)})}>{eligible.map(p=><option value={p._id} key={p._id}>{p.catalog_name || "Produk"} · {p.name}</option>)}</select></label><button type="button" className="text-xs text-cyan-300" onClick={()=>setForm({...form,product_ids:[]})}>Gunakan semua produk eligible</button>
      <p className="text-xs text-amber-300">Setiap pesan mengalokasikan 1 item inventory sebagai Marketing / By Me, bukan sold. Jasa tanpa inventory tidak dipilih. Interval adalah jeda acak antar pesan dan tetap berjalan saat browser ditutup.</p>
      <button disabled={busy || !channels.length} className="rounded-lg bg-cyan-600 px-4 py-2 disabled:opacity-40">{busy ? "Memproses…" : "Simpan & Aktifkan Campaign"}</button></form></details>
    <div className="space-y-2">{!campaigns.length && <p className="text-sm text-slate-500">Belum ada campaign.</p>}{campaigns.map(c=><button type="button" key={c._id} onClick={()=>{setSelected(c._id);setDetail(null);setMessageId("");}} className={`flex w-full flex-wrap justify-between gap-2 rounded-lg border p-3 text-left text-sm ${selected===c._id ? "border-cyan-500" : "border-slate-800"}`}><b>{c.name}</b><span>{c.status.toUpperCase()} · {c.sent}/{c.count} terkirim · Sisa {c.remaining}</span><span className="w-full text-xs text-slate-400">Berikutnya: {c.next_scheduled_at ? fmtDate(c.next_scheduled_at) : "—"} · {c.channel}</span></button>)}</div>
    {detail && <div className="space-y-3 border-t border-slate-700 pt-4"><h3 className="font-semibold">{detail.name} · Detail & alokasi</h3>{detail.error && <p className="text-sm text-amber-300">{detail.error}</p>}<div className="flex flex-wrap gap-2">{!["stopped","completed"].includes(detail.status) && <>{detail.status === "active" ? <button disabled={busy} onClick={()=>act("pause")} className="rounded-lg border border-slate-600 px-3 py-2">Pause</button> : <button disabled={busy} onClick={()=>act("resume")} className="rounded-lg border border-slate-600 px-3 py-2">Resume</button>}<button disabled={busy} onClick={()=>act("stop")} className="rounded-lg border border-rose-700 px-3 py-2 text-rose-300">Stop</button></>}<button disabled={busy || !allocations.length} onClick={()=>restore(null)} className="rounded-lg border border-cyan-700 px-3 py-2 text-cyan-300 disabled:opacity-40">Restore semua yang eligible ({allocations.length})</button></div>
      {detail.status !== "stopped" && ["unknown","sending"].includes(detail.events?.[detail.cursor]?.status) && <div className="space-y-2 rounded-lg bg-amber-950/30 p-3 text-sm"><p>Hasil pengiriman tidak pasti. Periksa channel. Jika pesan memang ada, masukkan ID pesan Telegram; jika tidak ingin melanjutkan, Stop.</p><input aria-label="ID pesan Telegram yang sudah terkirim" type="number" min={1} className={cls} value={messageId} onChange={e=>setMessageId(e.target.value)}/><button disabled={busy || !messageId} onClick={()=>act("confirm_sent")} className="text-amber-300">Konfirmasi pesan sudah terkirim</button></div>}
      {allocations.map(a=><div key={a._id} className="flex items-center justify-between gap-2 rounded-lg bg-slate-950 p-3 text-sm"><span>{a.product_name} · Marketing / By Me</span><button disabled={busy} onClick={()=>restore(a.marketing.event_id)} className="text-cyan-300">Restore 1</button></div>)}
      <details><summary className="cursor-pointer text-sm">Log event ({detail.events.length})</summary><div className="max-h-72 overflow-auto text-xs">{detail.events.map((e,i)=><div key={e._id} className="border-b border-slate-800 py-2"><b>#{i+1} {e.status.toUpperCase()}</b> · {e.product_name || "Belum dipilih"}<p>Jadwal: {e.scheduled_at ? fmtDate(e.scheduled_at) : "—"} · Terkirim: {e.sent_at ? fmtDate(e.sent_at) : "—"}</p><p>Message ID: {e.telegram_message_id || "—"} · Event/alokasi: {e._id}</p></div>)}</div></details>
    </div>}
  </section>;
}
