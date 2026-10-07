import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { User, Store, Mail, Phone, Lock, ArrowLeft, Sparkles, Bot, KeyRound, Info, X, Eye, EyeOff, Globe } from "lucide-react";
import api from "../lib/api";
import { toast } from "sonner";

/**
 * Public store registration form (/daftar) — langkah 1.
 * Glassy theme: backdrop-blur, translucent, glowing — ngikutin accent dari panel.
 * Isi data toko → kirim OTP → lanjut ke /daftar/verifikasi.
 */
const USERNAME_HINT = "3-50 karakter: huruf kecil, angka, titik atau strip. Tanpa underscore.";

/** Daftar kode negara — Indonesia default. Format: flag, ISO, nama, dial code */
const COUNTRY_CODES = [
  { iso: "ZA", flag: "🇿🇦", name: "Afrika Selatan", code: "27", placeholder: "821234567" },
  { iso: "US", flag: "🇺🇲", name: "Amerika Serikat", code: "1", placeholder: "2015550123" },
  { iso: "SA", flag: "🇸🇦", name: "Arab Saudi", code: "966", placeholder: "501234567" },
  { iso: "AR", flag: "🇦🇷", name: "Argentina", code: "54", placeholder: "9112345678" },
  { iso: "AU", flag: "🇦🇺", name: "Australia", code: "61", placeholder: "412345678" },
  { iso: "AT", flag: "🇦🇹", name: "Austria", code: "43", placeholder: "664123456" },
  { iso: "BH", flag: "🇧🇭", name: "Bahrain", code: "973", placeholder: "36123456" },
  { iso: "BD", flag: "🇧🇩", name: "Bangladesh", code: "880", placeholder: "1712345678" },
  { iso: "NL", flag: "🇳🇱", name: "Belanda", code: "31", placeholder: "612345678" },
  { iso: "BE", flag: "🇧🇪", name: "Belgia", code: "32", placeholder: "471234567" },
  { iso: "BR", flag: "🇧🇷", name: "Brasil", code: "55", placeholder: "11912345678" },
  { iso: "BN", flag: "🇧🇳", name: "Brunei", code: "673", placeholder: "8123456" },
  { iso: "CZ", flag: "🇨🇿", name: "Ceko", code: "420", placeholder: "601234567" },
  { iso: "CN", flag: "🇨🇳", name: "China", code: "86", placeholder: "13123456789" },
  { iso: "DK", flag: "🇩🇰", name: "Denmark", code: "45", placeholder: "28123456" },
  { iso: "PH", flag: "🇵🇭", name: "Filipina", code: "63", placeholder: "9171234567" },
  { iso: "FI", flag: "🇫🇮", name: "Finlandia", code: "358", placeholder: "401234567" },
  { iso: "HK", flag: "🇭🇰", name: "Hong Kong", code: "852", placeholder: "91234567" },
  { iso: "HU", flag: "🇭🇺", name: "Hungaria", code: "36", placeholder: "201234567" },
  { iso: "IN", flag: "🇮🇳", name: "India", code: "91", placeholder: "9123456789" },
  { iso: "ID", flag: "🇮🇩", name: "Indonesia", code: "62", placeholder: "81234567890" },
  { iso: "GB", flag: "🇬🇧", name: "Inggris", code: "44", placeholder: "7123456789" },
  { iso: "IT", flag: "🇮🇹", name: "Italia", code: "39", placeholder: "3123456789" },
  { iso: "JP", flag: "🇯🇵", name: "Jepang", code: "81", placeholder: "9012345678" },
  { iso: "DE", flag: "🇩🇪", name: "Jerman", code: "49", placeholder: "15123456789" },
  { iso: "KH", flag: "🇰🇭", name: "Kamboja", code: "855", placeholder: "12345678" },
  { iso: "KR", flag: "🇰🇷", name: "Korea Selatan", code: "82", placeholder: "1012345678" },
  { iso: "KW", flag: "🇰🇼", name: "Kuwait", code: "965", placeholder: "51234567" },
  { iso: "LA", flag: "🇱🇦", name: "Laos", code: "856", placeholder: "2012345678" },
  { iso: "MO", flag: "🇲🇴", name: "Macau", code: "853", placeholder: "61234567" },
  { iso: "MY", flag: "🇲🇾", name: "Malaysia", code: "60", placeholder: "123456789" },
  { iso: "MX", flag: "🇲🇽", name: "Meksiko", code: "52", placeholder: "5512345678" },
  { iso: "EG", flag: "🇪🇬", name: "Mesir", code: "20", placeholder: "1012345678" },
  { iso: "MM", flag: "🇲🇲", name: "Myanmar", code: "95", placeholder: "912345678" },
  { iso: "NP", flag: "🇳🇵", name: "Nepal", code: "977", placeholder: "9841234567" },
  { iso: "NG", flag: "🇳🇬", name: "Nigeria", code: "234", placeholder: "8031234567" },
  { iso: "NO", flag: "🇳🇴", name: "Norwegia", code: "47", placeholder: "41234567" },
  { iso: "OM", flag: "🇴🇲", name: "Oman", code: "968", placeholder: "92123456" },
  { iso: "PK", flag: "🇵🇰", name: "Pakistan", code: "92", placeholder: "3012345678" },
  { iso: "PL", flag: "🇵🇱", name: "Polandia", code: "48", placeholder: "512345678" },
  { iso: "PT", flag: "🇵🇹", name: "Portugal", code: "351", placeholder: "912345678" },
  { iso: "FR", flag: "🇫🇷", name: "Prancis", code: "33", placeholder: "612345678" },
  { iso: "QA", flag: "🇶🇦", name: "Qatar", code: "974", placeholder: "33123456" },
  { iso: "RO", flag: "🇷🇴", name: "Rumania", code: "40", placeholder: "712345678" },
  { iso: "RU", flag: "🇷🇺", name: "Rusia", code: "7", placeholder: "9123456789" },
  { iso: "NZ", flag: "🇳🇿", name: "Selandia Baru", code: "64", placeholder: "211234567" },
  { iso: "SG", flag: "🇸🇬", name: "Singapura", code: "65", placeholder: "81234567" },
  { iso: "ES", flag: "🇪🇸", name: "Spanyol", code: "34", placeholder: "612345678" },
  { iso: "LK", flag: "🇱🇰", name: "Sri Lanka", code: "94", placeholder: "771234567" },
  { iso: "SE", flag: "🇸🇪", name: "Swedia", code: "46", placeholder: "701234567" },
  { iso: "CH", flag: "🇨🇭", name: "Swiss", code: "41", placeholder: "781234567" },
  { iso: "TW", flag: "🇹🇼", name: "Taiwan", code: "886", placeholder: "912345678" },
  { iso: "TH", flag: "🇹🇭", name: "Thailand", code: "66", placeholder: "812345678" },
  { iso: "TL", flag: "🇹🇱", name: "Timor Leste", code: "670", placeholder: "77234567" },
  { iso: "TR", flag: "🇹🇷", name: "Turki", code: "90", placeholder: "5321234567" },
  { iso: "AE", flag: "🇦🇪", name: "UEA", code: "971", placeholder: "501234567" },
  { iso: "UA", flag: "🇺🇦", name: "Ukraina", code: "380", placeholder: "671234567" },
  { iso: "VN", flag: "🇻🇳", name: "Vietnam", code: "84", placeholder: "912345678" },
  { iso: "GR", flag: "🇬🇷", name: "Yunani", code: "30", placeholder: "6912345678" },
];

/** Daftar TLD populer — untuk user yang punya domain sendiri */
const TLD_LIST = [
  ".com", ".net", ".org", ".info", ".biz", ".online", ".store", ".shop", ".site", ".website",
  ".id", ".co.id", ".or.id", ".ac.id", ".sch.id", ".web.id", ".my.id", ".biz.id",
  ".io", ".co", ".me", ".tv", ".cc", ".xyz", ".top", ".club", ".vip", ".app", ".dev",
  ".net.id", ".asia", ".eu", ".us", ".uk", ".co.uk", ".de", ".fr", ".jp", ".cn",
  ".sg", ".my", ".th", ".vn", ".ph", ".in", ".au", ".nz",
];

/** Picker TLD custom — mirip CountryCodePicker */
function TldPicker({ value, onChange, accent }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const filtered = TLD_LIST.filter((t) => t.toLowerCase().includes(search.toLowerCase().replace(/^\./, "")));

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => { setOpen((o) => !o); setSearch(""); }}
        className={`mt-1.5 flex w-full items-center justify-center gap-1 rounded-2xl border border-white/15 bg-white/10 px-3 py-3 text-sm font-semibold text-white backdrop-blur-xl transition-all ${accent.border} hover:bg-white/15`}
      >
        <span>{value}</span>
        <span className="text-xs text-slate-500">▾</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute z-50 mt-2 max-h-64 w-40 overflow-hidden rounded-2xl border border-white/15 bg-slate-900/95 shadow-2xl backdrop-blur-2xl">
            <div className="border-b border-white/10 p-2">
              <input
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Cari..."
                className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500"
              />
            </div>
            <div className="max-h-48 overflow-y-auto py-1">
              {filtered.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => { onChange(t); setOpen(false); }}
                  className={`w-full px-3 py-2 text-left text-sm transition-colors hover:bg-white/10 ${
                    t === value ? "bg-emerald-500/10 text-emerald-300" : "text-slate-200"
                  }`}
                >
                  {t}
                </button>
              ))}
              {filtered.length === 0 && (
                <p className="px-3 py-4 text-center text-xs text-slate-500">Tidak ketemu.</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** Picker pilihan domain — single dropdown */
function DomainChoicePicker({ value, onChange, accent }) {
  const [open, setOpen] = useState(false);
  const options = [
    { id: false, label: "Tidak, saya tidak memiliki domain" },
    { id: true, label: "Ya, saya memiliki domain" },
  ];
  const selected = options.find((o) => o.id === value);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`mt-1.5 flex w-full items-center justify-between rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm backdrop-blur-xl transition-all ${accent.border} hover:bg-white/15 ${
          selected ? "text-white" : "text-slate-500"
        }`}
      >
        <span>{selected ? selected.label : "Pilih salah satu..."}</span>
        <span className="text-xs text-slate-500">▾</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute z-50 mt-2 w-full overflow-hidden rounded-2xl border border-white/15 bg-slate-900/95 shadow-2xl backdrop-blur-2xl">
            {options.map((o) => (
              <button
                key={String(o.id)}
                type="button"
                onClick={() => { onChange(o.id); setOpen(false); }}
                className={`w-full px-4 py-3 text-left text-sm transition-colors hover:bg-white/10 ${
                  o.id === value ? "bg-emerald-500/10 text-emerald-300" : "text-slate-200"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** Dropdown kode negara custom — bendera + ISO + kode di tampilan, nama lengkap di list */
function CountryCodePicker({ value, onChange, accent }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const selected = COUNTRY_CODES.find((c) => c.code === value) || COUNTRY_CODES[0];

  const filtered = COUNTRY_CODES.filter((c) =>
    (c.name + c.iso + c.code).toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => { setOpen((o) => !o); setSearch(""); }}
        className={`mt-1.5 flex w-full items-center gap-1.5 rounded-2xl border border-white/15 bg-white/10 px-3 py-3 text-sm text-white backdrop-blur-xl transition-all ${accent.border} hover:bg-white/15`}
      >
        <span className="text-lg leading-none">{selected.flag}</span>
        <span className="font-semibold">{selected.iso}</span>
        <span className="text-slate-400">+{selected.code}</span>
        <span className="ml-auto text-xs text-slate-500">▾</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute z-50 mt-2 max-h-64 w-64 overflow-hidden rounded-2xl border border-white/15 bg-slate-900/95 shadow-2xl backdrop-blur-2xl">
            <div className="border-b border-white/10 p-2">
              <input
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Cari negara..."
                className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500"
              />
            </div>
            <div className="max-h-48 overflow-y-auto py-1">
              {filtered.map((c) => (
                <button
                  key={c.iso}
                  type="button"
                  onClick={() => { onChange(c.code); setOpen(false); }}
                  className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors hover:bg-white/10 ${
                    c.code === value ? "bg-emerald-500/10" : ""
                  }`}
                >
                  <span className="text-lg leading-none">{c.flag}</span>
                  <span className="flex-1 text-slate-200">{c.name}</span>
                  <span className="text-xs text-slate-500">+{c.code}</span>
                </button>
              ))}
              {filtered.length === 0 && (
                <p className="px-3 py-4 text-center text-xs text-slate-500">Tidak ketemu.</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** Field wrapper — di luar komponen biar nggak remount tiap render */
function Field({ icon: Icon, label, hint, children, noIconPad }) {
  return (
    <div className="group min-w-0">
      <label className="text-sm font-semibold text-slate-200">{label}</label>
      <div className="relative">
        {!noIconPad && (
          <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 transition-colors group-focus-within:text-white">
            <Icon size={17} />
          </span>
        )}
        {children}
      </div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

const ACCENT_STYLES = {
  emerald: {
    text: "text-emerald-400", bg: "bg-emerald-500", bgHover: "hover:bg-emerald-400",
    gradient: "from-emerald-300 to-teal-400", glow: "shadow-emerald-500/30",
    ring: "focus:ring-emerald-400/30", border: "focus:border-emerald-400/60",
    softBg: "bg-emerald-500/10", radial: "rgba(16,185,129,0.15)",
  },
  blue: {
    text: "text-blue-400", bg: "bg-blue-500", bgHover: "hover:bg-blue-400",
    gradient: "from-blue-300 to-indigo-400", glow: "shadow-blue-500/30",
    ring: "focus:ring-blue-400/30", border: "focus:border-blue-400/60",
    softBg: "bg-blue-500/10", radial: "rgba(59,130,246,0.15)",
  },
  amber: {
    text: "text-amber-400", bg: "bg-amber-500", bgHover: "hover:bg-amber-400",
    gradient: "from-amber-300 to-orange-400", glow: "shadow-amber-500/30",
    ring: "focus:ring-amber-400/30", border: "focus:border-amber-400/60",
    softBg: "bg-amber-500/10", radial: "rgba(245,158,11,0.15)",
  },
  rose: {
    text: "text-rose-400", bg: "bg-rose-500", bgHover: "hover:bg-rose-400",
    gradient: "from-rose-300 to-pink-400", glow: "shadow-rose-500/30",
    ring: "focus:ring-rose-400/30", border: "focus:border-rose-400/60",
    softBg: "bg-rose-500/10", radial: "rgba(244,63,94,0.15)",
  },
  violet: {
    text: "text-violet-400", bg: "bg-violet-500", bgHover: "hover:bg-violet-400",
    gradient: "from-violet-300 to-purple-400", glow: "shadow-violet-500/30",
    ring: "focus:ring-violet-400/30", border: "focus:border-violet-400/60",
    softBg: "bg-violet-500/10", radial: "rgba(139,92,246,0.15)",
  },
  cyan: {
    text: "text-cyan-400", bg: "bg-cyan-500", bgHover: "hover:bg-cyan-400",
    gradient: "from-cyan-300 to-sky-400", glow: "shadow-cyan-500/30",
    ring: "focus:ring-cyan-400/30", border: "focus:border-cyan-400/60",
    softBg: "bg-cyan-500/10", radial: "rgba(6,182,212,0.15)",
  },
};

export default function RegisterStore() {
  const navigate = useNavigate();
  // Restore form dari sessionStorage kalau user kembali dari langkah berikutnya
  const [form, setForm] = useState(() => {
    try {
      const saved = sessionStorage.getItem("register_form");
      if (saved) {
        const parsed = JSON.parse(saved);
        return {
          username: "",
          storeName: "",
          email: "",
          countryCode: "62",
          whatsapp: "",
          password: "",
          password2: "",
          botToken: "",
          adminTelegramId: "",
          hasDomain: null,
          customDomain: "",
          tld: ".com",
          ...parsed,
        };
      }
    } catch {}
    return {
      username: "",
      storeName: "",
      email: "",
      countryCode: "62",
      whatsapp: "",
      password: "",
      password2: "",
      botToken: "",
      adminTelegramId: "",
      hasDomain: null,
      customDomain: "",
      tld: ".com",
    };
  });
  const [showToken, setShowToken] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [accent, setAccent] = useState(ACCENT_STYLES.emerald);
  const [siteName, setSiteName] = useState("IDSEConnect");
  const [showInfo, setShowInfo] = useState(false);

  const FIELD_INFO = [
    {
      icon: Mail,
      title: "Alamat Email",
      desc: "Kami kirim kode verifikasi (OTP) ke email ini untuk memastikan kamu pemilik sah akun tersebut. Email juga dipakai untuk notifikasi penting seperti reset password dan info tagihan. Wajib @gmail.com agar pengiriman kode cepat dan tidak masuk spam.",
    },
    {
      icon: User,
      title: "Username",
      desc: "Identitas unik tokomu di platform. Username ini akan menjadi alamat webshop kamu, contoh: username-shop.idseconnect.my.id. Pilih yang mudah diingat karena tidak bisa diubah setelah dibuat.",
    },
    {
      icon: Store,
      title: "Nama Toko",
      desc: "Nama publik yang tampil di webshop dan bot Telegram kamu. Ini yang dilihat pelanggan, jadi pakai nama brand yang menarik. Bisa diubah kapan saja dari pengaturan.",
    },
    {
      icon: Lock,
      title: "Password",
      desc: "Kunci keamanan akun pemilik tokomu. Minimal 12 karakter agar sulit ditebak. Password disimpan dalam bentuk terenkripsi (hash) — bahkan kami pun tidak bisa melihat password aslimu.",
    },
    {
      icon: Phone,
      title: "Nomor WhatsApp",
      desc: "Nomor aktif untuk koordinasi operasional — misalnya kalau ada kendala teknis di tokomu atau info penting dari tim kami. Pilih kode negara dulu, lalu masukkan nomor tanpa angka 0 di depan (khusus Indonesia langsung mulai dari 8). Nomor ini tidak ditampilkan ke pelanggan tanpa izinmu.",
    },
    {
      icon: Bot,
      title: "Token Bot Telegram (Opsional)",
      desc: "Kalau kamu sudah punya bot dari @BotFather, masukkan tokennya di sini agar bot langsung terhubung ke tokomu. Token otomatis disamarkan demi keamanan. Belum punya? Kosongkan saja, bisa ditambahkan nanti dari panel admin.",
    },
    {
      icon: KeyRound,
      title: "User ID Telegram (Opsional)",
      desc: "ID Telegram kamu (bisa dicek via @userinfobot). Dipakai agar kamu otomatis jadi admin di bot tokomu — bisa kelola produk, lihat order, dan atur pengaturan langsung dari Telegram.",
    },
  ];

  useEffect(() => {
    api.get("/public/promo-config")
      .then((r) => {
        const cfg = r.data || {};
        setAccent(ACCENT_STYLES[cfg.accent] || ACCENT_STYLES.emerald);
        if (cfg.site_name) setSiteName(cfg.site_name);
      })
      .catch(() => {});
  }, []);

  const set = (k) => (e) => setForm((c) => ({ ...c, [k]: e.target.value }));

  // Normalisasi subdomain → single DNS label
  // Lestari.Store → lestari-store, LESTARI_STORE → lestari-store
  const normalizeSlug = (v) => {
    return v
      .toLowerCase()
      .replace(/[._\s]+/g, "-")   // . _ spasi → -
      .replace(/[^a-z0-9-]/g, "") // buang selain a-z 0-9 -
      .replace(/-+/g, "-")        // collapse ---
      .replace(/^-+|-+$/g, "");   // trim - di awal/akhir
  };
  const normalizedSlug = normalizeSlug(form.username);

  // Validasi subdomain live
  const subdomainChecks = (() => {
    const v = form.username.trim();
    return [
      { label: "Minimal 3 karakter huruf/angka", ok: normalizedSlug.length >= 3 },
      { label: "Otomatis jadi format web (titik/spasi jadi -)", ok: v.length > 0 },
    ];
  })();
  const subdomainValid = form.hasDomain === false && subdomainChecks.every((c) => c.ok) && normalizedSlug.length >= 3;

  // Nomor WA: buang semua non-digit, buang 0 di depan untuk Indonesia
  const handleWhatsapp = (e) => {
    let v = e.target.value.replace(/\D/g, "");
    if (form.countryCode === "62" && v.startsWith("0")) {
      v = v.slice(1);
    }
    setForm((c) => ({ ...c, whatsapp: v }));
  };

  const handleCountry = (e) => {
    const cc = e.target.value;
    setForm((c) => {
      let wa = c.whatsapp;
      if (cc === "62" && wa.startsWith("0")) wa = wa.slice(1);
      return { ...c, countryCode: cc, whatsapp: wa };
    });
  };

  const goToVerify = async (e) => {
    e.preventDefault();
    setError("");
    if (form.hasDomain === null) {
      setError("Pilih dulu apakah kamu punya domain sendiri.");
      return;
    }
    if (form.hasDomain === true) {
      const d = form.customDomain.trim().toLowerCase().replace(/\.$/, "");
      if (d.length < 2) {
        setError("Masukkan nama domain anda.");
        return;
      }
      // Gabung dengan TLD pilihan
      form._fullDomain = d + form.tld;
    } else {
      if (!subdomainValid) {
        setError("Sub-domain belum memenuhi syarat.");
        return;
      }
    }
    if (form.password !== form.password2) {
      setError("Password dan konfirmasi password tidak sama.");
      return;
    }
    const email = form.email.trim().toLowerCase();
    if (!email.endsWith("@gmail.com")) {
      setError("Wajib menggunakan email @gmail.com.");
      return;
    }
    const waDigits = form.whatsapp.replace(/\D/g, "");
    if (waDigits.length < 8) {
      setError("Nomor WhatsApp tidak valid.");
      return;
    }
    const fullWhatsapp = `+${form.countryCode}${waDigits}`;
    // Siapkan data domain untuk backend
    const domainData = form.hasDomain
      ? { has_domain: true, custom_domain: form._fullDomain || (form.customDomain.trim().toLowerCase() + form.tld) }
      : { has_domain: false, subdomain: form.username.trim().toLowerCase() };
    // Simpan form ke sessionStorage biar nggak hilang kalau user kembali
    try {
      const { _fullDomain, ...toSave } = form;
      sessionStorage.setItem("register_form", JSON.stringify({ ...toSave, whatsapp: form.whatsapp }));
    } catch {}
    setSending(true);
    try {
      await api.post("/public/register/request-code", { email });
      toast.success("Kode OTP dikirim ke email kamu.");
      navigate("/daftar/verifikasi", {
        state: { formData: { ...form, whatsapp: fullWhatsapp, ...domainData } },
      });
    } catch (err) {
      setError(err.response?.data?.detail || "Gagal mengirim kode.");
    } finally {
      setSending(false);
    }
  };

  const inputCls =
    `mt-1.5 w-full rounded-2xl border border-white/15 bg-white/10 px-4 py-3 pl-11 text-sm text-white ` +
    `shadow-inner outline-none backdrop-blur-xl transition-all placeholder:text-slate-500 ` +
    `${accent.border} ${accent.ring} focus:bg-white/15 focus:ring-2`;

  const selectCls =
    `mt-1.5 w-full appearance-none rounded-2xl border border-white/15 bg-white/10 py-3 pl-4 pr-8 text-sm text-white ` +
    `outline-none backdrop-blur-xl transition-all ${accent.border} focus:bg-white/15 [&>option]:bg-slate-900`;

  const selectedCountry = COUNTRY_CODES.find((c) => c.code === form.countryCode) || COUNTRY_CODES[0];

  return (
    <div
      className="min-h-screen px-4 py-8"
      style={{ background: `radial-gradient(ellipse at top, ${accent.radial}, transparent 60%), #020617` }}
    >
      <div className="mx-auto max-w-2xl">
        <Link to="/promo" className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-400 transition-colors hover:text-white">
          <ArrowLeft size={16} /> Kembali
        </Link>

        <div className="rounded-3xl border border-white/15 bg-white/5 p-6 shadow-2xl shadow-black/40 backdrop-blur-2xl sm:p-8">
          <div className="mb-6 text-center">
            <div className="relative mx-auto h-16 w-16">
              <img src="/idse-logo.jpg" alt="IDSE" className="h-16 w-16 rounded-2xl border border-white/20 object-cover shadow-lg" />
              <span className={`absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full ${accent.bg} shadow-lg`}>
                <Sparkles size={12} className="text-slate-950" />
              </span>
            </div>
            <h1 className="mt-3 text-xl font-extrabold tracking-tight text-white">
              {siteName.replace(/connect/i, "")}<span className={`bg-gradient-to-r ${accent.gradient} bg-clip-text text-transparent`}>Connect</span>
            </h1>
            <p className="mt-1 text-lg font-bold text-slate-200">Daftar Toko Gratis</p>
            <p className="mt-1 text-xs text-slate-500">Isi data di bawah, verifikasi email, toko langsung jadi</p>
            <button
              type="button"
              onClick={() => setShowInfo(true)}
              className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-4 py-1.5 text-xs font-semibold text-slate-300 backdrop-blur-xl transition-all hover:bg-white/15 hover:text-white"
            >
              <Info size={13} /> Kenapa kami meminta data ini?
            </button>
          </div>

          {/* Popup penjelasan field */}
          {showInfo && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm" onClick={() => setShowInfo(false)}>
              <div
                className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-3xl border border-white/15 bg-slate-900/95 p-6 shadow-2xl backdrop-blur-2xl"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="mb-4 flex items-start justify-between">
                  <h2 className="text-lg font-bold text-white">Kenapa Kami Meminta Data Ini?</h2>
                  <button
                    onClick={() => setShowInfo(false)}
                    className="rounded-full border border-white/10 p-1.5 text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
                    aria-label="Tutup"
                  >
                    <X size={16} />
                  </button>
                </div>
                <div className="space-y-4">
                  {FIELD_INFO.map(({ icon: Icon, title, desc }) => (
                    <div key={title} className="flex gap-3 rounded-2xl border border-white/10 bg-white/5 p-3.5">
                      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${accent.softBg}`}>
                        <Icon size={16} className={accent.text} />
                      </span>
                      <div>
                        <p className="text-sm font-bold text-white">{title}</p>
                        <p className="mt-1 text-xs leading-relaxed text-slate-400">{desc}</p>
                      </div>
                    </div>
                  ))}
                </div>
                <button
                  onClick={() => setShowInfo(false)}
                  className={`mt-5 w-full rounded-2xl ${accent.bg} ${accent.bgHover} py-3 font-bold text-slate-950 transition-all`}
                >
                  Mengerti, Lanjut Daftar
                </button>
              </div>
            </div>
          )}

          {error && (
            <div className="mb-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300 backdrop-blur-xl">
              {error}
            </div>
          )}

          <form onSubmit={goToVerify} className="space-y-4">
            {/* 1. Alamat Email */}
            <Field icon={Mail} label="Alamat Email" hint="Kode OTP verifikasi akan dikirim ke email ini.">
              <input value={form.email} onChange={set("email")} placeholder="nama@gmail.com" type="email" className={inputCls} required />
            </Field>
            <p className="-mt-2 text-xs italic text-amber-400/80">
              ⚠️ Ingat-ingat alamat email ini ya, dipakai untuk login dan verifikasi akunmu.
            </p>

            {/* 2. WhatsApp — kode negara + nomor */}
            <div>
              <label className="text-sm font-semibold text-slate-200">WhatsApp</label>
              <div className="grid grid-cols-[150px_1fr] gap-2">
                <CountryCodePicker value={form.countryCode} onChange={handleCountry} accent={accent} />
                <div className="relative">
                  <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400">
                    <Phone size={17} />
                  </span>
                  <input
                    value={form.whatsapp}
                    onChange={handleWhatsapp}
                    placeholder={selectedCountry.placeholder}
                    inputMode="numeric"
                    className={inputCls.replace("mt-1.5 ", "")}
                    required
                  />
                </div>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {form.countryCode === "62"
                  ? "Untuk Indonesia langsung ketik mulai dari angka 8 (tanpa 0)."
                  : "Masukkan nomor tanpa kode negara di depan."}
              </p>
            </div>

            {/* 3. Nama Toko */}
            <Field icon={Store} label="Nama Toko" hint="Nama publik toko Anda.">
              <input value={form.storeName} onChange={set("storeName")} placeholder="Nama toko" className={inputCls} required minLength={2} maxLength={200} />
            </Field>

            {/* 4. Apakah punya domain? — single picker */}
            <div>
              <label className="text-sm font-semibold text-slate-200">Apakah anda memiliki domain?</label>
              <DomainChoicePicker
                value={form.hasDomain}
                onChange={(v) => setForm((c) => ({ ...c, hasDomain: v }))}
                accent={accent}
              />
            </div>

            {form.hasDomain !== null && (
              form.hasDomain ? (
                <div className="min-w-0">
                  <label className="text-sm font-semibold text-slate-200">Domain</label>
                  <div className="grid grid-cols-[1fr_90px] gap-2">
                    <div className="relative">
                      <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400">
                        <Globe size={17} />
                      </span>
                      <input
                        value={form.customDomain}
                        onChange={(e) => setForm((c) => ({ ...c, customDomain: e.target.value.toLowerCase().replace(/[^a-z0-9.-]/g, "") }))}
                        placeholder="www.tokomu"
                        className={inputCls}
                        required
                      />
                    </div>
                    <TldPicker value={form.tld} onChange={(t) => setForm((c) => ({ ...c, tld: t }))} accent={accent} />
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    Ketik nama domain tanpa akhiran, lalu pilih akhirannya.
                  </p>
                  {form.customDomain.trim().length >= 2 && (
                    <div className="mt-2 rounded-2xl border border-emerald-400/30 bg-emerald-500/10 p-3">
                      <p className="text-xs text-slate-400">Domain anda nantinya:</p>
                      <p className="mt-0.5 break-all text-sm font-bold text-emerald-300">
                        🌐 {form.customDomain.trim().toLowerCase()}{form.tld}
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="min-w-0">
                  <label className="text-sm font-semibold text-slate-200">Sub-domain</label>
                  <div className="grid grid-cols-[1fr_auto] gap-0">
                    <div className="relative">
                      <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400">
                        <User size={17} />
                      </span>
                      <input
                        value={form.username}
                        onChange={(e) => setForm((c) => ({ ...c, username: e.target.value.toLowerCase().replace(/[^a-z0-9._\s-]/g, "") }))}
                        placeholder="lestari.store"
                        className={`${inputCls} rounded-r-none border-r-0`}
                        required
                        minLength={3}
                        maxLength={50}
                      />
                    </div>
                    <span className="mt-1.5 flex items-center rounded-r-2xl border border-white/15 bg-white/5 px-3 text-xs text-slate-400 backdrop-blur-xl">
                      .idseconnect.my.id
                    </span>
                  </div>
                  {/* Live requirements */}
                  <div className="mt-1.5 space-y-1">
                    {subdomainChecks.map((c, i) => (
                      <p key={i} className={`flex items-center gap-1.5 text-xs ${c.ok ? "text-emerald-400" : "text-slate-500"}`}>
                        <span className={`flex h-3.5 w-3.5 items-center justify-center rounded-full text-[10px] ${c.ok ? "bg-emerald-500/20" : "bg-white/10"}`}>
                          {c.ok ? "✓" : "○"}
                        </span>
                        {c.label}
                      </p>
                    ))}
                  </div>
                  {subdomainValid && (
                    <div className="mt-2 rounded-2xl border border-emerald-400/30 bg-emerald-500/10 p-3">
                      <p className="text-xs text-slate-400">Alamat webshop anda nantinya:</p>
                      <p className="mt-0.5 break-all text-sm font-bold text-emerald-300">
                        🌐 {normalizedSlug}.idseconnect.my.id
                      </p>
                      {form.username.trim().toLowerCase() !== normalizedSlug && (
                        <p className="mt-1 text-[11px] text-amber-400/80">
                          "{form.username.trim()}" otomatis jadi "{normalizedSlug}"
                        </p>
                      )}
                      <p className="mt-1 text-[11px] text-slate-500">
                        Pastikan sudah benar ya, tidak bisa diubah setelah dibuat.
                      </p>
                    </div>
                  )}
                </div>
              )
            )}

            {/* 4. Password | Konfirmasi Password */}
            <div className="grid grid-cols-2 gap-3">
              <Field icon={Lock} label="Password">
                <input value={form.password} onChange={set("password")} placeholder="Minimal 12 karakter" type="password" minLength={12} className={inputCls} required />
              </Field>
              <Field icon={Lock} label="Konfirmasi Password">
                <input value={form.password2} onChange={set("password2")} placeholder="Ulangi password" type="password" minLength={12} className={inputCls} required />
              </Field>
            </div>

            {/* 5. Token Bot | User ID */}
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-xl">
              <p className="mb-3 text-sm font-semibold text-slate-200">
                <Bot size={15} className="mr-1.5 inline" />
                Bot Telegram <span className="font-normal text-slate-500">(opsional, bisa diisi nanti)</span>
              </p>
              <div className="grid grid-cols-2 gap-3">
                <Field icon={KeyRound} label="Token Bot" hint="Dari @BotFather. Otomatis disamarkan.">
                  <div className="relative">
                    <input
                      value={form.botToken}
                      onChange={set("botToken")}
                      placeholder="123456:ABC-DEF..."
                      type={showToken ? "text" : "password"}
                      className={`${inputCls} pr-11`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowToken((s) => !s)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                      aria-label={showToken ? "Sembunyikan token" : "Tampilkan token"}
                    >
                      {showToken ? <EyeOff size={17} /> : <Eye size={17} />}
                    </button>
                  </div>
                </Field>
                <Field icon={User} label="User ID Telegram" hint="Dari @userinfobot, karena akan menjadi owner bot.">
                  <input value={form.adminTelegramId} onChange={set("adminTelegramId")} placeholder="123456789" inputMode="numeric" className={inputCls} />
                </Field>
              </div>
            </div>

            <button type="submit" disabled={sending}
              className={`w-full rounded-2xl ${accent.bg} ${accent.bgHover} py-3.5 font-bold text-slate-950 shadow-lg ${accent.glow} transition-all hover:shadow-xl disabled:opacity-50`}>
              {sending ? "Mengirim kode..." : "Lanjut ke Verifikasi OTP"}
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-slate-400">
            Sudah punya akun?{" "}
            <Link to="/masuk" className={`font-semibold ${accent.text} hover:underline`}>Masuk</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
