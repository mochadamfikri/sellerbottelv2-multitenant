import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  Bot, CheckCircle2, MessageCircle, Users, Zap, ArrowRight,
  QrCode, Package, BarChart3, ChevronDown, LayoutDashboard,
} from "lucide-react";
import api from "../lib/api";

/**
 * IDSEConnect promo landing — fully config-driven.
 * All content comes from GET /api/public/promo-config, edited via the
 * platform panel. Falls back to built-in defaults if the API is unreachable.
 */

const ACCENT_STYLES = {
  emerald: {
    text: "text-emerald-400", bg: "bg-emerald-500", bgHover: "hover:bg-emerald-400",
    softBg: "bg-emerald-500/10", softBorder: "border-emerald-500/30",
    gradient: "from-emerald-300 to-teal-400", ring: "focus:ring-emerald-500/20",
    iconBg: "bg-emerald-500/15",
  },
  blue: {
    text: "text-blue-400", bg: "bg-blue-500", bgHover: "hover:bg-blue-400",
    softBg: "bg-blue-500/10", softBorder: "border-blue-500/30",
    gradient: "from-blue-300 to-indigo-400", ring: "focus:ring-blue-500/20",
    iconBg: "bg-blue-500/15",
  },
  amber: {
    text: "text-amber-400", bg: "bg-amber-500", bgHover: "hover:bg-amber-400",
    softBg: "bg-amber-500/10", softBorder: "border-amber-500/30",
    gradient: "from-amber-300 to-orange-400", ring: "focus:ring-amber-500/20",
    iconBg: "bg-amber-500/15",
  },
  rose: {
    text: "text-rose-400", bg: "bg-rose-500", bgHover: "hover:bg-rose-400",
    softBg: "bg-rose-500/10", softBorder: "border-rose-500/30",
    gradient: "from-rose-300 to-pink-400", ring: "focus:ring-rose-500/20",
    iconBg: "bg-rose-500/15",
  },
  violet: {
    text: "text-violet-400", bg: "bg-violet-500", bgHover: "hover:bg-violet-400",
    softBg: "bg-violet-500/10", softBorder: "border-violet-500/30",
    gradient: "from-violet-300 to-purple-400", ring: "focus:ring-violet-500/20",
    iconBg: "bg-violet-500/15",
  },
  cyan: {
    text: "text-cyan-400", bg: "bg-cyan-500", bgHover: "hover:bg-cyan-400",
    softBg: "bg-cyan-500/10", softBorder: "border-cyan-500/30",
    gradient: "from-cyan-300 to-sky-400", ring: "focus:ring-cyan-500/20",
    iconBg: "bg-cyan-500/15",
  },
};

const DEFAULT_FEATURES = [
  { icon: "bot", title: "Bot Telegram Atas Nama Brand Kamu", desc: "Pakai bot buatanmu sendiri dari @BotFather. Sapaan, banner, dan tombol menu bisa disesuaikan dengan identitas tokomu." },
  { icon: "qr", title: "Pembayaran QRIS Otomatis", desc: "Pelanggan scan QRIS dari e-wallet atau m-banking apa pun. Sistem mendeteksi pembayaran sendiri tanpa perlu kirim bukti transfer." },
  { icon: "zap", title: "Pengiriman Produk Seketika", desc: "Akun, lisensi, voucher, atau kode produk langsung dikirim bot begitu pembayaran terkonfirmasi. Nggak pakai nunggu." },
  { icon: "package", title: "Katalog & Stok Terpusat", desc: "Atur kategori, harga, deskripsi, dan upload stok massal dari satu tempat. Stok habis terpantau jelas." },
  { icon: "users", title: "Jaringan Reseller", desc: "Buka peluang reseller ikut menjual produkmu, atau ambil produk dari marketplace buat memperkaya etalase." },
  { icon: "chart", title: "Laporan & Broadcast", desc: "Pantau omset harian lewat grafik, lihat statistik pelanggan, dan kirim broadcast promo ke semua pengguna bot sekaligus." },
];

const ICONS = { bot: Bot, qr: QrCode, zap: Zap, package: Package, users: Users, chart: BarChart3 };

const DEFAULT_STEPS = [
  { n: "01", title: "Daftar & Verifikasi Akun", desc: "Isi formulir pendaftaran toko, verifikasi email, dan akunmu langsung aktif. Gratis untuk mulai." },
  { n: "02", title: "Sambungkan Bot & Isi Produk", desc: "Masukkan token bot dari @BotFather, atur sapaan toko, lalu tambahkan produk dan stok digital yang mau dijual." },
  { n: "03", title: "Sebar Link, Biarkan Bot Bekerja", desc: "Bagikan link bot ke pelanggan. Mereka pesan, bayar via QRIS, dan bot mengirim produk otomatis 24/7." },
];

const DEFAULT_FAQS = [
  { q: "Apa itu IDSEConnect?", a: "IDSEConnect adalah platform untuk membangun toko produk digital berbasis bot Telegram. Kamu bisa mengelola katalog, stok otomatis, pembayaran QRIS, sampai tampilan bot — semuanya dari satu dashboard." },
  { q: "Bagaimana pelanggan membayar?", a: "Pelanggan menerima invoice QRIS yang bisa dibayar lewat GoPay, OVO, Dana, ShopeePay, LinkAja, dan m-banking. Pembayaran terverifikasi otomatis tanpa upload bukti." },
  { q: "Apakah botnya pakai nama toko saya sendiri?", a: "Ya. Kamu membuat bot sendiri lewat @BotFather, jadi toko berjalan penuh atas nama dan brand kamu." },
  { q: "Berapa lama sampai toko saya aktif?", a: "Pendaftaran hanya butuh beberapa menit. Setelah verifikasi email, kamu langsung bisa sambungkan bot dan isi produk." },
];

function FaqItem({ q, a, accent }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between px-5 py-4 text-left">
        <span className="font-semibold text-white">{q}</span>
        <ChevronDown size={18} className={`shrink-0 ${accent.text} transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <p className="px-5 pb-5 text-sm leading-relaxed text-slate-400">{a}</p>}
    </div>
  );
}

function PromoButton({ button, accent, primary }) {
  const styles = {
    primary: `${accent.bg} ${accent.bgHover} font-bold text-slate-950 shadow-lg`,
    secondary: "border border-white/15 bg-white/5 font-semibold text-white hover:bg-white/10",
    outline: "border border-white/10 font-semibold text-slate-300 hover:bg-white/5",
  };
  const cls = `flex items-center justify-center gap-2 rounded-xl px-6 py-3.5 ${styles[button.style] || styles.outline}`;
  const url = button.url || "#";
  const isInternal = url.startsWith("/");
  const content = (<>{button.label} {primary && <ArrowRight size={17} />}</>);
  return isInternal
    ? <Link to={url} className={cls}>{content}</Link>
    : <a href={url} target="_blank" rel="noreferrer" className={cls}>{content}</a>;
}

export default function PromoLanding() {
  const [cfg, setCfg] = useState(null);

  useEffect(() => {
    api.get("/public/promo-config").then((r) => setCfg(r.data)).catch(() => setCfg({}));
  }, []);

  const accent = ACCENT_STYLES[cfg?.accent] || ACCENT_STYLES.emerald;
  const hero = cfg?.hero || {};
  const buttons = (cfg?.buttons || []).filter((b) => b.visible);
  const sections = cfg?.sections || {};
  const siteName = cfg?.site_name || "IDSEConnect";
  const [brandMain, brandAccent] = siteName.includes("Connect")
    ? [siteName.replace("Connect", ""), "Connect"]
    : [siteName, ""];

  if (cfg === null) {
    return <div className="grid min-h-screen place-items-center bg-slate-950 text-slate-500">Memuat...</div>;
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <header className="sticky top-0 z-20 border-b border-white/10 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2.5">
            <img src="/idse-logo.jpg" alt="IDSE" className="h-9 w-9 rounded-xl object-cover" />
            <span className="text-lg font-extrabold tracking-tight text-white">
              {brandMain}<span className={accent.text}>{brandAccent}</span>
            </span>
          </div>
          <div className="flex items-center gap-2 sm:gap-4">
            <Link to="/masuk" className="hidden text-sm font-semibold text-slate-300 hover:text-white sm:block">Masuk</Link>
            <Link to="/daftar" className={`inline-flex items-center gap-1.5 rounded-xl ${accent.bg} ${accent.bgHover} px-3 py-2 text-sm font-bold text-slate-950 sm:px-5`}>
              Daftar Toko <ArrowRight size={15} />
            </Link>
          </div>
        </div>
      </header>

      {hero.visible !== false && (
        <section className="mx-auto max-w-6xl px-4 pb-14 pt-10 sm:pt-16">
          <div className="grid items-center gap-10 lg:grid-cols-2">
            <div className="text-center lg:text-left">
              <span className={`inline-flex items-center gap-2 rounded-full border ${accent.softBorder} ${accent.softBg} px-4 py-1.5 text-xs font-bold tracking-widest ${accent.text}`}>
                <span className={`h-2 w-2 animate-pulse rounded-full ${accent.bg}`} />
                {hero.badge || "PLATFORM TOKO DIGITAL OTOMATIS"}
              </span>
              <h1 className="mt-5 text-4xl font-extrabold leading-tight tracking-tight text-white sm:text-5xl">
                {hero.title || "Jualan Produk Digital di Telegram."}{" "}
                <span className={`bg-gradient-to-r ${accent.gradient} bg-clip-text text-transparent`}>
                  {hero.title_accent || "Jalan Sendiri 24/7."}
                </span>
              </h1>
              <p className="mx-auto mt-4 max-w-xl text-slate-400 lg:mx-0">
                {hero.subtitle || ""}
              </p>
              {buttons.length > 0 && (
                <div className="mx-auto mt-7 grid max-w-md gap-3 sm:grid-cols-2 lg:mx-0">
                  {buttons.map((b, i) => (
                    <PromoButton key={b.id} button={b} accent={accent} primary={i === 0} />
                  ))}
                </div>
              )}
              {(cfg?.highlights || []).length > 0 && (
                <ul className="mx-auto mt-7 flex max-w-md flex-wrap justify-center gap-x-5 gap-y-2 text-sm text-slate-400 lg:mx-0 lg:justify-start">
                  {(cfg.highlights || []).map((f) => (
                    <li key={f} className="flex items-center gap-1.5">
                      <CheckCircle2 size={15} className={accent.text} /> {f}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {sections.simulation !== false && (
              <div className="mx-auto w-full max-w-sm">
                <div className="rounded-3xl border border-white/10 bg-slate-900 p-5 shadow-2xl">
                  <p className="mb-4 text-center text-xs font-bold tracking-widest text-slate-500">SIMULASI TRANSAKSI REAL-TIME</p>
                  <div className="space-y-3">
                    <div className="rounded-2xl bg-slate-800 p-4">
                      <p className="flex items-center gap-2 text-sm font-bold text-white">
                        <Bot size={16} className={accent.text} /> Selamat datang di tokoku! 👋
                      </p>
                      <p className="mt-1 text-xs text-slate-400">Produk digital premium, proses instan &amp; aman.</p>
                    </div>
                    <div className={`ml-8 rounded-2xl rounded-tr-sm ${accent.softBg} p-3 text-right text-sm ${accent.text}`}>
                      Saya pesan 1 akun premium ✨
                    </div>
                    <div className="rounded-2xl bg-slate-800 p-4">
                      <p className="text-sm font-bold text-white">Pesanan dikonfirmasi 🧾</p>
                      <p className="font-mono text-xs text-slate-400">Invoice #IDSE-2481 • Rp 35.000</p>
                      <div className="mt-2 flex items-center gap-2 rounded-xl bg-white p-2.5">
                        <QrCode size={28} className="text-slate-900" />
                        <p className="text-[11px] font-semibold text-slate-700">QRIS aktif — scan via e-wallet / m-banking</p>
                      </div>
                    </div>
                    <div className={`flex items-center gap-2 rounded-2xl border ${accent.softBorder} ${accent.softBg} p-3.5`}>
                      <Zap size={18} className={`shrink-0 ${accent.text}`} />
                      <p className={`text-xs font-semibold ${accent.text}`}>Pembayaran terverifikasi! Detail akun terkirim ke chat kamu.</p>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {sections.features !== false && (
        <section className="border-t border-white/5 bg-slate-900/50">
          <div className="mx-auto max-w-6xl px-4 py-14">
            <p className={`text-center text-xs font-bold tracking-widest ${accent.text}`}>FITUR UNGGULAN</p>
            <h2 className="mx-auto mt-3 max-w-2xl text-center text-3xl font-extrabold tracking-tight text-white">
              {cfg?.features_title || "Semua Kebutuhan Tokomu, Dalam Satu Dashboard"}
            </h2>
            <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {DEFAULT_FEATURES.map(({ icon, title, desc }) => {
                const Icon = ICONS[icon] || Bot;
                return (
                  <div key={title} className="rounded-2xl border border-white/10 bg-slate-950 p-6">
                    <span className={`grid h-11 w-11 place-items-center rounded-xl ${accent.iconBg} ${accent.text}`}>
                      <Icon size={22} />
                    </span>
                    <h3 className="mt-4 font-bold text-white">{title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-slate-400">{desc}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {sections.steps !== false && (
        <section className="mx-auto max-w-6xl px-4 py-14">
          <p className={`text-center text-xs font-bold tracking-widest ${accent.text}`}>LANGKAH MUDAH</p>
          <h2 className="mx-auto mt-3 max-w-2xl text-center text-3xl font-extrabold tracking-tight text-white">
            {cfg?.steps_title || "Dari Daftar Sampai Pesanan Pertama"}
          </h2>
          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {DEFAULT_STEPS.map((s) => (
              <div key={s.n} className="rounded-2xl border border-white/10 bg-white/5 p-6">
                <span className={`text-4xl font-extrabold ${accent.text} opacity-30`}>{s.n}</span>
                <h3 className="mt-2 font-bold text-white">{s.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-400">{s.desc}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {sections.faq !== false && (
        <section className="border-t border-white/5 bg-slate-900/50">
          <div className="mx-auto max-w-3xl px-4 py-14">
            <p className={`text-center text-xs font-bold tracking-widest ${accent.text}`}>PERTANYAAN UMUM</p>
            <h2 className="mt-3 text-center text-3xl font-extrabold tracking-tight text-white">
              {cfg?.faq_title || "Sering Ditanyakan"}
            </h2>
            <div className="mt-8 space-y-3">
              {DEFAULT_FAQS.map((f) => <FaqItem key={f.q} q={f.q} a={f.a} accent={accent} />)}
            </div>
          </div>
        </section>
      )}

      {sections.final_cta !== false && (
        <section className="mx-auto max-w-6xl px-4 py-16 text-center">
          <div className={`rounded-3xl border ${accent.softBorder} ${accent.softBg} px-6 py-12`}>
            <p className={`text-xs font-bold tracking-widest ${accent.text}`}>{cfg?.final_cta?.badge || "SIAP MEMULAI?"}</p>
            <h2 className="mx-auto mt-3 max-w-xl text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
              {cfg?.final_cta?.title || "Biarkan Bot Melayani Pelangganmu, Kapan Pun."}
            </h2>
            <p className="mx-auto mt-3 max-w-lg text-slate-400">{cfg?.final_cta?.subtitle || ""}</p>
            <Link to="/daftar" className={`mt-7 inline-flex items-center gap-2 rounded-xl ${accent.bg} ${accent.bgHover} px-8 py-4 font-bold text-slate-950 shadow-lg`}>
              {cfg?.final_cta?.button_label || "Buat Toko Gratis Sekarang"} <ArrowRight size={18} />
            </Link>
          </div>
        </section>
      )}

      <footer className="border-t border-white/5 py-8 text-center">
        <div className="flex items-center justify-center gap-2">
          <img src="/idse-logo.jpg" alt="IDSE" className="h-7 w-7 rounded-lg object-cover" />
          <span className="font-bold text-white">{brandMain}<span className={accent.text}>{brandAccent}</span></span>
        </div>
        <p className="mt-2 text-xs text-slate-500">© 2026 {siteName} — Platform Bot Toko Digital</p>
      </footer>
    </div>
  );
}
