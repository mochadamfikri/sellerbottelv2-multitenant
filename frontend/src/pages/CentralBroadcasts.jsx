import { useEffect, useMemo, useState } from "react";
import { Megaphone, Image as ImageIcon, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";
import BroadcastOptions from "../components/BroadcastOptions";

const cls = "w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";
const initial = { kind: "system_update", topic: "reseller_guide", reference_id: "", title: "", message: "", target: "chats" };
const topics = [
  { id: "reseller_guide", title: "🤖 Cara Menjadi Reseller", detail: "Token BotFather, User ID, pembayaran, harga, dan komisi." },
  { id: "reseller_contest", title: "🏆 Kontes Reseller", detail: "Hadiah, target omzet, dan periode dari kontes aktif." },
  { id: "discount", title: "🎉 Diskon Aktif", detail: "Potongan dan produk sesuai aturan diskon yang tersimpan." },
  { id: "coupon", title: "🎟️ Kupon Aktif", detail: "Kode, syarat, kuota, dan cara memakai kupon." },
  { id: "product_update", title: "📦 Info Produk", detail: "Harga, deskripsi, dan stok produk aktif." },
  { id: "product_restock", title: "🔄 Restock Produk", detail: "Umumkan produk yang kembali tersedia." },
  { id: "deposit_guide", title: "💳 Cara Deposit & Belanja", detail: "Metode deposit aktif dan langkah checkout." },
  { id: "announcement", title: "📢 Pembaruan Sistem", detail: "Tulis pengumuman bebas untuk fitur atau perubahan lain." },
];

export default function CentralBroadcasts() {
  const [form, setForm] = useState(initial);
  const [options, setOptions] = useState({ contests: [], discounts: [], coupons: [], products: [] });
  const [history, setHistory] = useState([]);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [choices, broadcasts] = await Promise.all([
        api.get("/admin/broadcasts/compose/central-options"),
        api.get("/admin/broadcasts"),
      ]);
      setOptions(choices.data || {});
      setHistory((broadcasts.data || []).filter((item) => item.broadcast_type === "system_update"));
    } catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal memuat Broadcast Terpusat."); }
  };
  useEffect(() => { load(); }, []);

  const choices = useMemo(() => {
    if (form.topic === "reseller_contest") return options.contests || [];
    if (form.topic === "discount") return options.discounts || [];
    if (form.topic === "coupon") return options.coupons || [];
    if (["product_update", "product_restock"].includes(form.topic)) return options.products || [];
    return [];
  }, [form.topic, options]);
  const needsReference = ["reseller_contest", "discount", "coupon", "product_update", "product_restock"].includes(form.topic);
  const change = (next) => { setForm(next); setPreview(null); };

  const run = async (action) => {
    if (needsReference && !form.reference_id) { toast.error("Pilih data yang akan diumumkan."); return; }
    if (form.topic === "announcement" && (!form.title.trim() || !form.message.trim())) {
      toast.error("Isi judul dan pesan pembaruan sistem."); return;
    }
    setBusy(true);
    try {
      const { data } = await api.post(`/admin/broadcasts/compose/${action}`, form);
      if (action === "preview") setPreview(data);
      if (action === "test") toast.success("Pesan tes beserta gambar dikirim ke admin Telegram.");
      if (action === "send") {
        const failed = (data.chat_results || []).filter((row) => !row.ok).length;
        if (failed) toast.error(`${failed} channel/grup gagal menerima broadcast. Periksa riwayat.`);
        else toast.success(`Broadcast dikirim. ${data.queued_users || 0} pengguna masuk antrean.`);
        setPreview(null);
        await load();
      }
    } catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Broadcast gagal."); }
    finally { setBusy(false); }
  };

  const plainPreview = (preview?.text || "").replace(/<[^>]*>/g, "");
  return <div className="space-y-5">
    <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5 space-y-5">
      <div><h2 className="font-heading text-lg font-semibold flex items-center gap-2"><Megaphone size={20} className="text-cyan-400" /> Broadcast Terpusat</h2>
        <p className="text-sm text-slate-400 mt-1">Umumkan fitur dan informasi penting memakai data terbaru dari sistem. Setiap pesan mendapat gambar otomatis.</p></div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{topics.map((topic) => <button key={topic.id} type="button"
        onClick={() => change({ ...form, topic: topic.id, reference_id: "", title: "", message: "" })}
        className={`rounded-lg border p-3 text-left ${form.topic === topic.id ? "border-cyan-500 bg-cyan-500/10" : "border-slate-700 bg-slate-950 hover:border-slate-500"}`}>
        <b className="text-sm">{topic.title}</b><span className="block text-xs text-slate-400 mt-1">{topic.detail}</span>
      </button>)}</div>
      {form.topic === "reseller_guide" && !options.reseller_enabled && <p className="text-sm text-amber-300">Pendaftaran reseller sedang ditutup. Buka dulu di menu Bot Reseller sebelum broadcast panduannya.</p>}
      {needsReference && <div><label className="text-sm text-slate-300">Pilih {form.topic === "reseller_contest" ? "kontes" : form.topic === "discount" ? "diskon" : form.topic === "coupon" ? "kupon" : "produk"}</label>
        <select className={cls} value={form.reference_id} onChange={(event) => change({ ...form, reference_id: event.target.value })}>
          <option value="">-- Pilih --</option>{choices.map((item) => <option key={item._id} value={item._id}>{item.name || item.code}</option>)}
        </select>{!choices.length && <p className="text-xs text-amber-300 mt-1">Belum ada data aktif untuk jenis pengumuman ini.</p>}</div>}
      {form.topic === "announcement" && <div><label className="text-sm text-slate-300">Judul pembaruan</label><input className={cls} maxLength={80} value={form.title} onChange={(event) => change({ ...form, title: event.target.value })} placeholder="Contoh: Fitur Baru IDSE Digital Product" /></div>}
      <div><label className="text-sm text-slate-300">{form.topic === "announcement" ? "Isi pengumuman" : "Catatan tambahan (opsional)"}</label>
        <textarea rows={form.topic === "announcement" ? 5 : 3} maxLength={700} className={cls}
          placeholder={form.topic === "announcement" ? "Jelaskan pembaruan yang ingin diumumkan..." : "Tambahkan pesan khusus bila perlu..."}
          value={form.message} onChange={(event) => change({ ...form, message: event.target.value })} /></div>
      <div><label className="text-sm text-slate-300">Kirim ke</label><select className={cls} value={form.target} onChange={(event) => change({ ...form, target: event.target.value })}>
        <option value="chats">Channel dan grup terhubung</option><option value="users">Semua pengguna bot pusat</option><option value="both">Channel, grup, dan semua pengguna</option>
      </select></div>
      <BroadcastOptions form={form} change={change}/>
      <button disabled={busy} onClick={() => run("preview")} className="w-full rounded-lg bg-slate-700 hover:bg-slate-600 py-3 font-semibold disabled:opacity-50">{busy ? "Memproses..." : "Lihat Pesan dan Gambar"}</button>
    </div>

    {preview && <div className="rounded-xl border border-cyan-500/30 bg-slate-900/80 p-5 space-y-4">
      <h3 className="font-semibold flex items-center gap-2"><ImageIcon size={18} className="text-cyan-400" /> Pratinjau Broadcast</h3>
      {preview.image_data_url && <img src={preview.image_data_url} alt="Poster broadcast otomatis" className="w-full max-w-lg rounded-lg border border-slate-700" />}
      <pre className="whitespace-pre-wrap rounded-lg bg-slate-950 border border-slate-800 p-3 text-sm text-slate-200 max-h-96 overflow-auto">{plainPreview}</pre>
      <p className="text-sm text-slate-400">Tujuan: {preview.chats?.length || 0} channel/grup dan {preview.user_count || 0} pengguna. {preview.chats?.join(", ")}</p>
      {preview.image_data_url && <a href={preview.image_data_url} download="IDSE-broadcast.jpg" className="inline-block text-sm font-semibold text-cyan-400">Unduh gambar broadcast</a>}
      <div className="flex flex-wrap gap-2">
        <button disabled={busy} onClick={() => run("test")} className="rounded-lg bg-slate-700 hover:bg-slate-600 px-4 py-2.5 disabled:opacity-50">Kirim Tes ke Admin</button>
        <button disabled={busy} onClick={() => { if (window.confirm(`Kirim broadcast ke ${preview.chats?.length || 0} channel/grup dan ${preview.user_count || 0} pengguna?`)) run("send"); }} className="rounded-lg bg-cyan-600 hover:bg-cyan-700 px-4 py-2.5 font-semibold disabled:opacity-50">Kirim Broadcast</button>
      </div>
    </div>}

    <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-5">
      <div className="flex justify-between mb-4"><h3 className="font-semibold">Riwayat Broadcast Terpusat</h3><button onClick={load} title="Refresh"><RefreshCw size={16} /></button></div>
      <div className="space-y-2">{history.map((item) => <div key={item._id} className="border border-slate-800 rounded-lg p-3">
        <div className="flex justify-between text-xs text-slate-500"><span>{item.broadcast_topic?.replace(/_/g, " ")} · {item.status}</span><span>{item.success || 0} berhasil · {item.failed || 0} gagal</span></div>
        <p className="text-sm text-slate-200 mt-1 whitespace-pre-wrap line-clamp-3">{String(item.text || "").replace(/<[^>]*>/g, "")}</p>
      </div>)}{!history.length && <p className="text-sm text-slate-500">Belum ada broadcast terpusat.</p>}</div>
    </div>
  </div>;
}
