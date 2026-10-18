import { useEffect, useMemo, useState } from "react";
import { Send, RefreshCw, Image as ImageIcon, Megaphone, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";
import BroadcastOptions from "../components/BroadcastOptions";

const cls = "w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";

const centralTopics = [
  { id: "product_update", title: "📦 Info Produk", detail: "Harga, deskripsi, dan stok produk aktif saat ini." },
  { id: "product_restock", title: "🔄 Restock Produk", detail: "Umumkan produk yang baru saja kembali tersedia." },
  { id: "discount", title: "🎉 Diskon Aktif", detail: "Potongan harga dan produk sesuai aturan diskon toko." },
  { id: "coupon", title: "🎟️ Kupon Belanja", detail: "Kode promo, kuota, dan diskon kupon aktif." },
  { id: "deposit_guide", title: "💳 Cara Deposit & Belanja", detail: "Panduan cara bayar QRIS & transfer bank." },
  { id: "announcement", title: "📢 Pengumuman Bebas", detail: "Tulis judul dan pengumuman pembaruan sistem bebas." },
];

export default function Broadcasts() {
  const [activeTab, setActiveTab] = useState("promo"); // "promo" | "templates" | "recap"

  // State Promo / Produk
  const [promoForm, setPromoForm] = useState({
    kind: "message",
    message: "",
    product_ids: [],
    summaries: {},
    target: "chats",
  });
  const [products, setProducts] = useState([]);
  const [search, setSearch] = useState("");
  const [catalogFilter, setCatalogFilter] = useState("");

  // State Template Terpusat
  const [centralForm, setCentralForm] = useState({
    kind: "system_update",
    topic: "product_update",
    reference_id: "",
    title: "",
    message: "",
    target: "chats",
  });
  const [centralOptions, setCentralOptions] = useState({ contests: [], discounts: [], coupons: [], products: [] });

  // State Rekap Harian
  const [recapConfig, setRecapConfig] = useState({ enabled: false, time: "00:05", target: "chats" });
  const [recapPeriod, setRecapPeriod] = useState("30d");

  // Shared state
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);

  const loadData = async () => {
    try {
      const [prodRes, bcastRes, optRes, recapRes] = await Promise.all([
        api.get("/admin/products"),
        api.get("/admin/broadcasts"),
        api.get("/admin/broadcasts/compose/central-options"),
        api.get("/admin/broadcasts/daily-recap/config"),
      ]);
      setProducts(prodRes.data || []);
      setHistory(bcastRes.data || []);
      setCentralOptions(optRes.data || {});
      setRecapConfig(recapRes.data || { enabled: false, time: "00:05", target: "chats" });
    } catch (_) {}
  };

  useEffect(() => {
    loadData();
  }, []);

  const toggleProduct = (product) => {
    const selected = promoForm.product_ids.includes(product._id);
    if (!selected && promoForm.product_ids.length >= 10) {
      toast.error("Maksimal 10 produk per broadcast.");
      return;
    }
    const next = selected
      ? promoForm.product_ids.filter((id) => id !== product._id)
      : [...promoForm.product_ids, product._id];
    const summaries = { ...promoForm.summaries };
    if (!selected && !summaries[product._id]) {
      summaries[product._id] = String(product.description || "")
        .replace(/<[^>]*>/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 180);
    }
    setPromoForm({ ...promoForm, product_ids: next, summaries });
    setPreview(null);
  };

  const centralChoices = useMemo(() => {
    if (centralForm.topic === "discount") return centralOptions.discounts || [];
    if (centralForm.topic === "coupon") return centralOptions.coupons || [];
    if (["product_update", "product_restock"].includes(centralForm.topic)) return centralOptions.products || [];
    return [];
  }, [centralForm.topic, centralOptions]);

  const needsReference = ["discount", "coupon", "product_update", "product_restock"].includes(centralForm.topic);

  const getPayload = () => {
    if (activeTab === "promo") {
      return promoForm;
    }
    if (activeTab === "templates") {
      return centralForm;
    }
    return {
      kind: "daily_recap",
      period: recapPeriod,
      target: recapConfig.target || "chats",
    };
  };

  const handleAction = async (action) => {
    const payload = getPayload();

    if (activeTab === "promo" && !payload.message.trim() && !payload.product_ids.length) {
      toast.error("Tulis pesan pengumuman atau pilih minimal 1 produk.");
      return;
    }
    if (activeTab === "templates") {
      if (needsReference && !payload.reference_id) {
        toast.error("Pilih data produk / diskon yang ingin diumumkan.");
        return;
      }
      if (payload.topic === "announcement" && (!payload.title.trim() || !payload.message.trim())) {
        toast.error("Isi judul dan isi pengumuman sistem.");
        return;
      }
    }

    setBusy(true);
    try {
      const { data } = await api.post(`/admin/broadcasts/compose/${action}`, payload);
      if (action === "preview") {
        setPreview(data);
      }
      if (action === "test") {
        toast.success("Pesan uji coba berhasil dikirim ke akun Telegram admin.");
      }
      if (action === "send") {
        toast.success(`Broadcast berhasil dikirim! Menjangkau ${data.queued_users || 0} pengguna.`);
        setPreview(null);
        await loadData();
      }
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Eksekusi broadcast gagal.");
    } finally {
      setBusy(false);
    }
  };

  const availableProducts = products.filter(
    (p) => p.active !== false && (p.product_kind === "service" || p.stock == null || p.stock > 0)
  );
  const filteredProducts = availableProducts.filter(
    (p) => (!catalogFilter || p.catalog_name === catalogFilter) && p.name?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header Utama */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <Megaphone className="text-cyan-400" size={24} /> Pusat Broadcast Telegram
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Kirim pesan promosi, restock produk, atau pengumuman resmi ke Channel dan Pengguna Bot secara rapi dan otomatis.
          </p>
        </div>
      </div>

      {/* Tabs Menu Simpel */}
      <div className="flex border-b border-slate-800 gap-2">
        <button
          type="button"
          onClick={() => { setActiveTab("promo"); setPreview(null); }}
          className={`px-4 py-2.5 text-xs font-semibold rounded-t-lg transition border-b-2 flex items-center gap-2 ${
            activeTab === "promo"
              ? "border-cyan-400 text-cyan-300 bg-slate-900/80"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Send size={15} /> 1. Broadcast Produk & Promo
        </button>

        <button
          type="button"
          onClick={() => { setActiveTab("templates"); setPreview(null); }}
          className={`px-4 py-2.5 text-xs font-semibold rounded-t-lg transition border-b-2 flex items-center gap-2 ${
            activeTab === "templates"
              ? "border-cyan-400 text-cyan-300 bg-slate-900/80"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Megaphone size={15} /> 2. Pengumuman Otomatis (Template)
        </button>

        <button
          type="button"
          onClick={() => { setActiveTab("recap"); setPreview(null); }}
          className={`px-4 py-2.5 text-xs font-semibold rounded-t-lg transition border-b-2 flex items-center gap-2 ${
            activeTab === "recap"
              ? "border-cyan-400 text-cyan-300 bg-slate-900/80"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <RefreshCw size={15} /> 3. Rekap Penjualan
        </button>
      </div>

      {/* Konten Tab 1: Broadcast Produk & Promo */}
      {activeTab === "promo" && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5 space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">Pesan Pengumuman (Opsional)</label>
            <textarea
              rows={3}
              className={cls}
              placeholder="Tulis pesan atau caption promo di sini..."
              value={promoForm.message}
              onChange={(e) => { setPromoForm({ ...promoForm, message: e.target.value }); setPreview(null); }}
            />
          </div>

          <div>
            <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
              <label className="text-xs font-semibold text-slate-300">
                Pilih Produk untuk Disertakan ({promoForm.product_ids.length}/10 produk terpilih)
              </label>
              <input
                className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1 text-xs text-slate-200 w-48"
                placeholder="Cari nama produk..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <div className="max-h-60 overflow-y-auto rounded-lg border border-slate-800 divide-y divide-slate-800/60 bg-slate-950/40">
              {filteredProducts.map((p) => {
                const isSelected = promoForm.product_ids.includes(p._id);
                return (
                  <label key={p._id} className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-slate-800/40 text-xs">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleProduct(p)}
                      className="rounded border-slate-700 text-cyan-500"
                    />
                    <span className="flex-1 font-medium text-slate-200">{p.name}</span>
                    <span className="text-slate-400 font-mono">
                      {p.price_idr ? `Rp ${Number(p.price_idr).toLocaleString('id-ID')}` : '-'}
                    </span>
                    <span className="text-slate-500 text-[11px]">
                      {p.product_kind === "service" ? "Unlimited" : `Stok ${p.stock ?? 0}`}
                    </span>
                  </label>
                );
              })}
              {!filteredProducts.length && (
                <p className="p-3 text-xs text-slate-500 text-center">Tidak ada produk aktif yang ditemukan.</p>
              )}
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">Target Kirim</label>
            <select
              className={cls}
              value={promoForm.target}
              onChange={(e) => { setPromoForm({ ...promoForm, target: e.target.value }); setPreview(null); }}
            >
              <option value="chats">📢 Channel & Grup Telegram Terhubung</option>
              <option value="users">👤 Seluruh Pengguna Bot Telegram</option>
              <option value="both">🌐 Keduanya (Channel, Grup, dan Semua User)</option>
            </select>
          </div>

          <BroadcastOptions form={promoForm} change={(v) => { setPromoForm(v); setPreview(null); }} />

          <button
            type="button"
            disabled={busy}
            onClick={() => handleAction("preview")}
            className="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg py-3 transition"
          >
            {busy ? "Memproses..." : "👁️ Pratinjau Pesan & Format Tabel"}
          </button>
        </div>
      )}

      {/* Konten Tab 2: Template Pengumuman Terpusat */}
      {activeTab === "templates" && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5 space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-2">Pilih Kategori Informasi yang Ingin Diumumkan</label>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
              {centralTopics.map((top) => {
                const active = centralForm.topic === top.id;
                return (
                  <button
                    key={top.id}
                    type="button"
                    onClick={() => {
                      setCentralForm({ ...centralForm, topic: top.id, reference_id: "", title: "", message: "" });
                      setPreview(null);
                    }}
                    className={`p-3 rounded-lg border text-left transition ${
                      active ? "border-cyan-500 bg-cyan-500/10" : "border-slate-800 bg-slate-950/60 hover:border-slate-700"
                    }`}
                  >
                    <div className="text-xs font-bold text-slate-100">{top.title}</div>
                    <div className="text-[11px] text-slate-400 mt-1">{top.detail}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {needsReference && (
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Pilih Data yang Akan Diumumkan</label>
              <select
                className={cls}
                value={centralForm.reference_id}
                onChange={(e) => { setCentralForm({ ...centralForm, reference_id: e.target.value }); setPreview(null); }}
              >
                <option value="">-- Pilih Salah Satu --</option>
                {centralChoices.map((item) => (
                  <option key={item._id} value={item._id}>{item.name || item.code}</option>
                ))}
              </select>
            </div>
          )}

          {centralForm.topic === "announcement" && (
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Judul Pengumuman</label>
              <input
                className={cls}
                placeholder="Contoh: Pembaruan Layanan & Fitur Baru"
                value={centralForm.title}
                onChange={(e) => { setCentralForm({ ...centralForm, title: e.target.value }); setPreview(null); }}
              />
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              {centralForm.topic === "announcement" ? "Isi Pengumuman Lengkap" : "Catatan Tambahan (Opsional)"}
            </label>
            <textarea
              rows={3}
              className={cls}
              placeholder="Tulis informasi tambahan bila diperlukan..."
              value={centralForm.message}
              onChange={(e) => { setCentralForm({ ...centralForm, message: e.target.value }); setPreview(null); }}
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">Target Kirim</label>
            <select
              className={cls}
              value={centralForm.target}
              onChange={(e) => { setCentralForm({ ...centralForm, target: e.target.value }); setPreview(null); }}
            >
              <option value="chats">📢 Channel & Grup Telegram Terhubung</option>
              <option value="users">👤 Seluruh Pengguna Bot Telegram</option>
              <option value="both">🌐 Keduanya (Channel, Grup, dan Semua User)</option>
            </select>
          </div>

          <BroadcastOptions form={centralForm} change={(v) => { setCentralForm(v); setPreview(null); }} />

          <button
            type="button"
            disabled={busy}
            onClick={() => handleAction("preview")}
            className="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg py-3 transition"
          >
            {busy ? "Memproses..." : "👁️ Pratinjau Pengumuman & Gambar Otomatis"}
          </button>
        </div>
      )}

      {/* Konten Tab 3: Rekap Harian */}
      {activeTab === "recap" && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5 space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-200">Kirim Rekap Penjualan & Produk Terlaris</h3>
            <p className="text-xs text-slate-400 mt-1">
              Mengirim laporan omzet, total pesanan berhasil, dan tabel produk paling laris secara otomatis ke channel laporan.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-300 mb-1">Periode Data</label>
              <select className={cls} value={recapPeriod} onChange={(e) => setRecapPeriod(e.target.value)}>
                <option value="7d">7 Hari Terakhir</option>
                <option value="30d">30 Hari Terakhir</option>
                <option value="all">Sepanjang Waktu</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-slate-300 mb-1">Target Pengiriman</label>
              <select className={cls} value={recapConfig.target} onChange={(e) => setRecapConfig({ ...recapConfig, target: e.target.value })}>
                <option value="chats">Channel Rekap / Pengaturan</option>
                <option value="users">Semua Pengguna</option>
                <option value="both">Semua (Channel & Pengguna)</option>
              </select>
            </div>
          </div>

          <button
            type="button"
            disabled={busy}
            onClick={() => handleAction("preview")}
            className="w-full bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg py-3 transition"
          >
            {busy ? "Memproses..." : "👁️ Pratinjau Laporan Rekap"}
          </button>
        </div>
      )}

      {/* Box Preview Sebelum Kirim */}
      {preview && (
        <div className="rounded-xl border border-cyan-500/40 bg-slate-900/90 p-5 space-y-4 shadow-xl">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-slate-100 text-sm flex items-center gap-2">
              <CheckCircle2 className="text-cyan-400" size={17} /> Pratinjau Pesan yang Akan Diterima
            </h3>
            <span className="text-xs text-slate-400 font-mono">
              Target: {preview.chats?.length || 0} Chat · {preview.user_count || 0} Pengguna
            </span>
          </div>

          {preview.image_data_url && (
            <div>
              <img
                src={preview.image_data_url}
                alt="Gambar Poster Broadcast"
                className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-950"
              />
            </div>
          )}

          <div
            className="rounded-lg bg-slate-950 border border-slate-800 p-4 text-xs font-mono text-slate-200 whitespace-pre-wrap max-h-80 overflow-y-auto"
            dangerouslySetInnerHTML={{ __html: preview.text || "Tidak ada teks" }}
          />

          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => handleAction("test")}
              className="bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg px-4 py-2.5 transition"
            >
              Kirim Tes ke Admin Telegram
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (window.confirm(`Kirim broadcast sekarang ke target terpilih?`)) {
                  handleAction("send");
                }
              }}
              className="bg-cyan-600 hover:bg-cyan-500 text-slate-950 text-xs font-bold rounded-lg px-5 py-2.5 transition shadow-lg shadow-cyan-900/30"
            >
              🚀 Kirim Broadcast Sekarang
            </button>
          </div>
        </div>
      )}

      {/* Riwayat Broadcast */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-sm text-slate-200">Riwayat Pengiriman Broadcast</h3>
          <button type="button" onClick={loadData} className="text-slate-400 hover:text-slate-200" title="Muat ulang">
            <RefreshCw size={15} />
          </button>
        </div>

        <div className="space-y-2 max-h-72 overflow-y-auto">
          {history.map((item) => (
            <div key={item._id} className="border border-slate-800/80 rounded-lg p-3 bg-slate-950/40 text-xs">
              <div className="flex justify-between text-slate-400 mb-1">
                <span className="font-semibold uppercase text-cyan-400">{item.broadcast_type || "Pesan"}</span>
                <span>{item.success || 0} berhasil · {item.failed || 0} gagal</span>
              </div>
              <p className="text-slate-300 line-clamp-2">{String(item.text || "").replace(/<[^>]*>/g, "")}</p>
            </div>
          ))}
          {!history.length && <p className="text-xs text-slate-500 text-center py-2">Belum ada riwayat broadcast.</p>}
        </div>
      </div>
    </div>
  );
}
