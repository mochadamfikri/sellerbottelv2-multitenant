import { useEffect, useState } from "react";
import { Send, RefreshCw, Image as ImageIcon } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";
import BroadcastOptions from "../components/BroadcastOptions";
import MarketingCampaigns from "../components/MarketingCampaigns";

const cls = "w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";
const initial = { kind: "message", period: "30d", message: "", product_ids: [], summaries: {}, target: "chats" };
const broadcastTypes = [
  { value: "message", title: "Pesan & Produk", detail: "Tulis pesan dan pilih hingga 10 produk dalam satu gambar." },
  { value: "best_sellers", title: "Produk Terlaris", detail: "Kirim peringkat produk, total unit terjual, dan total penjualan." },
  { value: "daily_recap", title: "Rekap Harian", detail: "Kirim total penjualan, unit terjual, dan produk terlaris kemarin." },
];

export default function Broadcasts() {
  const [form, setForm] = useState(() => { try { return { ...initial, ...JSON.parse(localStorage.getItem("broadcast_draft") || "{}") }; } catch (_) { return initial; } });
  const [products, setProducts] = useState([]);
  const [history, setHistory] = useState([]);
  const [stockEvents, setStockEvents] = useState([]);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [catalogFilter, setCatalogFilter] = useState("");
  const [recapConfig, setRecapConfig] = useState({ enabled: false, time: "00:05", target: "chats" });
  const [savingConfig, setSavingConfig] = useState(false);

  const load = () => {
    api.get("/admin/products").then(({ data }) => setProducts(data || [])).catch(() => {});
    api.get("/admin/broadcasts").then(({ data }) => setHistory(data || [])).catch(() => {});
    api.get("/admin/broadcasts/stock-events").then(({ data }) => setStockEvents(data || [])).catch(() => {});
    api.get("/admin/broadcasts/daily-recap/config").then(({ data }) => setRecapConfig(data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);
  useEffect(() => { localStorage.setItem("broadcast_draft", JSON.stringify(form)); }, [form]);

  const change = (value) => { setForm(value); setPreview(null); };
  const toggleProduct = (product) => {
    const selected = form.product_ids.includes(product._id);
    if (!selected && form.product_ids.length >= 10) {
      toast.error("Maksimal 10 produk dalam satu gambar.");
      return;
    }
    const next = selected ? form.product_ids.filter((id) => id !== product._id) : [...form.product_ids, product._id];
    const summaries = { ...form.summaries };
    if (!selected && !summaries[product._id]) summaries[product._id] = String(product.description || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 180);
    change({ ...form, product_ids: next, summaries });
  };

  const run = async (action) => {
    if (form.kind === "message" && !form.message.trim() && !form.product_ids.length) {
      toast.error("Tulis pesan atau pilih produk.");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post(`/admin/broadcasts/compose/${action}`, form);
      if (action === "preview") setPreview(data);
      if (action === "test") toast.success("Pesan tes dikirim ke admin Telegram.");
      if (action === "send") {
        const failedChats = (data.chat_results || []).filter((row) => !row.ok);
        if (failedChats.length) toast.error(`${failedChats.length} channel/grup gagal menerima pesan. Periksa riwayat dan izin bot.`);
        else toast.success(`Broadcast dikirim. ${data.queued_users || 0} pengguna masuk antrean.`);
        setForm(initial);
        setPreview(null);
        load();
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Broadcast gagal.");
    } finally {
      setBusy(false);
    }
  };

  const available = products.filter((product) => product.active !== false &&
    (product.product_kind === "service" || product.stock == null || product.stock > 0));
  const filtered = available.filter((product) => (!catalogFilter || product.catalog_name === catalogFilter) && product.name?.toLowerCase().includes(search.toLowerCase()));
  const plainPreview = (preview?.text || "").replace(/<[^>]*>/g, "");
  const saveConfig = async () => {
    setSavingConfig(true);
    try {
      const { data } = await api.put("/admin/broadcasts/daily-recap/config", recapConfig);
      setRecapConfig(data);
      toast.success("Jadwal rekap harian disimpan.");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Jadwal gagal disimpan.");
    } finally { setSavingConfig(false); }
  };

  return (
    <div className="space-y-5">
      <MarketingCampaigns products={products}/>
      <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5 space-y-5">
        <div>
          <h2 className="font-heading text-lg font-semibold flex items-center gap-2"><Send size={19} className="text-cyan-400" /> Broadcast</h2>
          <p className="text-sm text-slate-400 mt-1">Pilih isi pesan, lihat pratinjau, lalu tentukan penerimanya.</p>
        </div>
        <div>
          <p className="text-sm text-slate-300 mb-2">Pilih jenis broadcast</p>
          <div className="grid gap-3 sm:grid-cols-3">
            {broadcastTypes.map((type) => <button key={type.value} type="button" onClick={() => change({ ...form, kind: type.value })}
              aria-pressed={form.kind === type.value}
              className={`rounded-xl border p-4 text-left transition-colors ${form.kind === type.value ? "border-cyan-500 bg-cyan-500/10" : "border-slate-700 bg-slate-950 hover:border-slate-500"}`}>
              <span className="block font-semibold text-slate-100">{type.title}</span>
              <span className="block mt-1 text-xs text-slate-400">{type.detail}</span>
            </button>)}
          </div>
          <p className="text-xs text-slate-500 mt-2">Draft tersimpan di browser ini. Pilih teks saja atau gambar otomatis, lalu periksa tujuan sebelum mengirim.</p>
        </div>
        {form.kind === "best_sellers" && <div>
          <label className="text-sm text-slate-300">Periode penjualan</label>
          <select className={cls} value={form.period} onChange={(event) => change({ ...form, period: event.target.value })}>
            <option value="7d">7 hari terakhir</option><option value="30d">30 hari terakhir</option><option value="all">Sepanjang waktu</option>
          </select>
          <p className="text-xs text-slate-500 mt-1">Menampilkan hingga 5 produk terlaris beserta unit terjual dan total penjualan.</p>
        </div>}
        {form.kind === "daily_recap" && <p className="text-sm text-slate-400">Rekap penjualan harian untuk kemarin (WIB): total penjualan, jumlah unit terjual, dan produk terlaris.</p>}
        {form.kind === "message" && <>
        <div>
          <label className="text-sm text-slate-300">Pesan utama</label>
          <textarea rows={4} maxLength={1000} className={cls} placeholder="Tulis pesan untuk pembeli (opsional jika memilih produk)..." value={form.message} onChange={(event) => change({ ...form, message: event.target.value })} />
        </div>
        <div>
          <div className="flex items-center justify-between gap-3 mb-2">
            <label className="text-sm text-slate-300">Pilih produk ({form.product_ids.length}/10)</label>
            <input className={`${cls} max-w-xs`} placeholder="Cari produk..." value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
          <select aria-label="Filter katalog broadcast" className={`${cls} mb-2`} value={catalogFilter} onChange={(e) => setCatalogFilter(e.target.value)}><option value="">Semua katalog</option>{[...new Set(products.map((p) => p.catalog_name).filter(Boolean))].sort().map((name) => <option key={name}>{name}</option>)}</select>
          <div className="max-h-64 overflow-auto rounded-lg border border-slate-800 divide-y divide-slate-800">
            {filtered.map((product) => (
              <label key={product._id} className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-slate-800/50">
                <input type="checkbox" checked={form.product_ids.includes(product._id)} onChange={() => toggleProduct(product)} />
                <span className="flex-1 text-sm text-slate-200">{product.name}</span>
                <span className="text-xs text-slate-500">{product.product_kind === "service" ? "Unlimited" : `Stok ${product.stock}`}</span>
              </label>
            ))}
            {!filtered.length && <p className="p-3 text-sm text-slate-500">Tidak ada produk aktif dengan stok tersedia.</p>}
          </div>
        </div>
        {!!form.product_ids.length && (
          <div className="space-y-3">
            <p className="text-xs text-slate-400">Ringkasan otomatis dari deskripsi produk. Kamu bisa menyuntingnya untuk gambar dan pesan.</p>
            {form.product_ids.map((id) => {
              const product = products.find((item) => item._id === id);
              return <div key={id}>
                <label className="text-xs text-cyan-300">{product?.name || "Produk"}</label>
                <textarea rows={2} maxLength={180} className={cls} value={form.summaries[id] || ""} onChange={(event) => change({ ...form, summaries: { ...form.summaries, [id]: event.target.value } })} />
              </div>;
            })}
          </div>
        )}
        </>}
        <div>
          <label className="text-sm text-slate-300">Kirim ke</label>
          <select className={cls} value={form.target} onChange={(event) => change({ ...form, target: event.target.value })}>
            <option value="chats">Channel dan grup terhubung</option>
            <option value="users">Semua pengguna bot</option>
            <option value="both">Channel, grup, dan semua pengguna</option>
          </select>
        </div>
        <BroadcastOptions form={form} change={change}/>
        <button type="button" disabled={busy} onClick={() => run("preview")} className="w-full rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-50 py-3 font-semibold">{busy ? "Memproses..." : "Lihat Pratinjau"}</button>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5 space-y-4">
        <div>
          <h3 className="font-semibold">Jadwal Rekap Harian</h3>
          <p className="text-sm text-slate-400 mt-1">Pilih kirim manual saja atau kirim otomatis setiap hari. Rekap memakai waktu WIB dan menghitung pesanan yang selesai dikirim.</p>
        </div>
        <div><label className="text-sm text-slate-300">Cara kirim rekap</label><select className={cls} value={recapConfig.enabled ? "auto" : "manual"} onChange={(event) => setRecapConfig({ ...recapConfig, enabled: event.target.value === "auto" })}>
          <option value="manual">Hanya manual</option><option value="auto">Otomatis setiap hari</option>
        </select></div>
        {recapConfig.enabled ? <div className="grid gap-3 sm:grid-cols-2">
          <div><label className="text-sm text-slate-300">Jam kirim (WIB)</label><input type="time" className={cls} value={recapConfig.time} onChange={(event) => setRecapConfig({ ...recapConfig, time: event.target.value })} /></div>
          <div><label className="text-sm text-slate-300">Kirim otomatis ke</label><select className={cls} value={recapConfig.target} onChange={(event) => setRecapConfig({ ...recapConfig, target: event.target.value })}>
            <option value="chats">Channel dan grup terhubung</option><option value="users">Semua pengguna bot</option><option value="both">Channel, grup, dan semua pengguna</option>
          </select></div>
        </div> : <p className="text-sm text-slate-400">Untuk mengirim, pilih “Rekap penjualan harian” di atas, pilih penerima, lalu lihat pratinjau.</p>}
        <button type="button" disabled={savingConfig} onClick={saveConfig} className="rounded-lg bg-slate-700 hover:bg-slate-600 px-4 py-2.5 text-sm disabled:opacity-50">{savingConfig ? "Menyimpan..." : "Simpan Pengaturan"}</button>
      </div>

      {preview && <div className="rounded-xl border border-cyan-500/30 bg-slate-900/80 p-5 space-y-4">
        <h3 className="font-semibold flex items-center gap-2"><ImageIcon size={18} className="text-cyan-400" /> Pratinjau sebelum kirim</h3>
        {preview.image_data_url && <img src={preview.image_data_url} alt="Pratinjau gabungan produk" className="w-full max-w-lg rounded-lg border border-slate-700" />}
        <pre className="whitespace-pre-wrap rounded-lg bg-slate-950 border border-slate-800 p-3 text-sm text-slate-200 max-h-72 overflow-auto">{plainPreview}</pre>
        <p className="text-sm text-slate-400">Tujuan: {preview.chats?.length || 0} channel/grup dan {preview.user_count || 0} pengguna. {preview.chats?.join(", ")}</p>
        {preview.image_data_url && <a href={preview.image_data_url} download="IDSE-broadcast.jpg" className="inline-block text-sm font-semibold text-cyan-400">Unduh gambar broadcast</a>}
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => run("test")} className="rounded-lg bg-slate-700 hover:bg-slate-600 px-4 py-2.5 disabled:opacity-50">Kirim Tes ke Admin</button>
          <button type="button" disabled={busy} onClick={() => {
            if (window.confirm(`Kirim ke ${preview.chats?.length || 0} channel/grup dan ${preview.user_count || 0} pengguna?`)) run("send");
          }} className="rounded-lg bg-cyan-600 hover:bg-cyan-700 px-4 py-2.5 font-semibold disabled:opacity-50">Kirim Broadcast</button>
        </div>
      </div>}

      <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5">
        <div className="flex justify-between mb-4"><h3 className="font-semibold">Riwayat Broadcast</h3><button type="button" onClick={load} title="Refresh"><RefreshCw size={16} /></button></div>
        <div className="space-y-2">
          {history.map((item) => <div key={item._id} className="border border-slate-800 rounded-lg p-3">
            <div className="flex justify-between text-xs text-slate-500"><span>{item.status}</span><span>{item.success || 0} berhasil · {item.failed || 0} gagal</span></div>
            <p className="text-sm text-slate-200 mt-1 whitespace-pre-wrap line-clamp-3">{String(item.text || "").replace(/<[^>]*>/g, "")}</p>
            {(item.chat_results || []).map((row) => <p key={row.chat_id} className={`mt-1 text-xs ${row.ok ? "text-emerald-400" : "text-amber-400"}`}>{row.chat_id}: {row.ok ? "terkirim" : row.error || "gagal"}</p>)}
            {item.status === "running" && <button className="mt-2 text-xs text-rose-400" onClick={async () => { try { await api.post(`/admin/broadcasts/compose/jobs/${item._id}/cancel`); load(); } catch (_) { toast.error("Antrean sudah selesai atau tidak dapat dibatalkan."); } }}>Hentikan sisa antrean</button>}
          </div>)}
          {!history.length && <p className="text-sm text-slate-500">Belum ada broadcast.</p>}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5">
        <div className="flex justify-between mb-4"><h3 className="font-semibold">Notifikasi Stok</h3><button type="button" onClick={load} title="Refresh"><RefreshCw size={16} /></button></div>
        <div className="space-y-2">
          {stockEvents.map((event) => <div key={event._id} className="border border-slate-800 rounded-lg p-3 flex items-center justify-between gap-3">
            <div className="text-sm text-slate-200">
              <span className="font-semibold">{event.event_type === "restocked" ? "Restock" : "Stok habis"}</span>
              <span className="text-slate-400"> · {event.from_count} → {event.to_count} · {event.status}</span>
              <p className="text-xs text-slate-500">{event.product_name || event.product_id} · {event.delivered?.length || 0}/{event.targets?.length || 0} tujuan terkirim</p>
            </div>
            {event.status === "pending" && <button type="button" disabled={busy} className="rounded-lg bg-slate-700 px-3 py-1.5 text-xs disabled:opacity-50" onClick={async () => {
              setBusy(true);
              try {
                await api.post(`/admin/broadcasts/stock-events/${event._id}/retry`);
                toast.success("Pengiriman ulang diproses.");
                load();
              } catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal mencoba ulang."); }
              finally { setBusy(false); }
            }}>Coba Lagi</button>}
          </div>)}
          {!stockEvents.length && <p className="text-sm text-slate-500">Belum ada perubahan stok yang perlu diumumkan.</p>}
        </div>
      </div>
    </div>
  );
}
