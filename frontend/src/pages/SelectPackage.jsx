import { useState, useEffect } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { ArrowLeft, Check, Sparkles, Zap, Crown } from "lucide-react";
import api from "../lib/api";
import { toast } from "sonner";

/**
 * Halaman pilih paket (/daftar/paket) — langkah 3.
 * Referensi: "Pricing Cards V4 — 3 Pricing Cards with Toggle".
 * Toggle Bulanan/Tahunan + 3 kartu glassmorphism.
 */
export default function SelectPackage() {
  const navigate = useNavigate();
  const location = useLocation();
  const formData = location.state?.formData;
  const verifyToken = location.state?.verifyToken;

  const [billing, setBilling] = useState("monthly"); // monthly | yearly
  const [selected, setSelected] = useState("pro");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!formData?.email || !verifyToken) {
      navigate("/daftar", { replace: true });
    }
  }, [formData, verifyToken, navigate]);

  if (!formData?.email || !verifyToken) return null;

  const PACKAGES = [
    {
      id: "demo",
      name: "Demo",
      icon: Sparkles,
      monthly: { price: "Gratis", period: "14 hari" },
      yearly: { price: "Gratis", period: "14 hari" },
      features: ["1 bot Telegram", "50 produk", "Webshop standar", "Support komunitas"],
      highlight: false,
      plan: "demo",
    },
    {
      id: "pro",
      name: "Pro",
      icon: Zap,
      monthly: { price: "Rp 49rb", period: "/bulan" },
      yearly: { price: "Rp 499rb", period: "/tahun" },
      save: billing === "yearly" ? "Hemat 15%" : null,
      features: ["1 bot Telegram", "500 produk", "Webshop custom", "Broadcast banner", "Wajib join channel", "Support prioritas"],
      highlight: true,
      plan: billing === "yearly" ? "yearly" : "monthly",
    },
    {
      id: "lifetime",
      name: "Lifetime",
      icon: Crown,
      monthly: { price: "Rp 1,5jt", period: "sekali bayar" },
      yearly: { price: "Rp 1,5jt", period: "sekali bayar" },
      features: ["5 bot Telegram", "Unlimited produk", "Semua fitur Pro", "Update selamanya", "Support VIP"],
      highlight: false,
      plan: "lifetime",
    },
  ];

  const submit = async () => {
    const pkg = PACKAGES.find((p) => p.id === selected);
    setError("");
    setSubmitting(true);
    try {
      // Kalau punya custom domain → wajib verifikasi DNS dulu
      if (formData.has_domain && formData.custom_domain) {
        navigate("/daftar/dns", {
          state: {
            domain: formData.custom_domain,
            formData: { ...formData },
            verifyToken,
            pkg: pkg.plan,
          },
        });
        return;
      }
      const res = await api.post("/public/register", {
        username: formData.username.trim().toLowerCase(),
        store_name: formData.storeName.trim(),
        email: formData.email.trim().toLowerCase(),
        verify_token: verifyToken,
        package: pkg.plan,
        whatsapp: formData.whatsapp.trim(),
        password: formData.password,
        bot_token: formData.botToken?.trim() || null,
        admin_telegram_id: formData.adminTelegramId?.trim() || null,
        has_domain: !!formData.has_domain,
        custom_domain: formData.custom_domain || null,
        subdomain: formData.subdomain || formData.username.trim().toLowerCase(),
      });
      toast.success("Toko berhasil dibuat! Selamat datang.");
      navigate("/daftar/sukses", { state: res.data });
    } catch (err) {
      setError(err.response?.data?.detail || "Pendaftaran gagal.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 bg-[radial-gradient(ellipse_at_top,rgba(16,185,129,0.12),transparent_60%)] px-4 py-8">
      <div className="mx-auto max-w-4xl">
        <Link to="/daftar" className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-white">
          <ArrowLeft size={16} /> Kembali
        </Link>

        <div className="mb-6 text-center">
          <h1 className="text-2xl font-extrabold tracking-tight text-white">Pilih Paket Tokomu</h1>
          <p className="mt-2 text-sm text-slate-400">
            Email <span className="font-semibold text-slate-200">{formData.email}</span> sudah terverifikasi.
          </p>

          {/* Toggle Bulanan / Tahunan */}
          <div className="mt-5 inline-flex rounded-full border border-white/15 bg-white/5 p-1 backdrop-blur-xl">
            {[
              { id: "monthly", label: "Bulanan" },
              { id: "yearly", label: "Tahunan" },
            ].map((opt) => (
              <button
                key={opt.id}
                onClick={() => setBilling(opt.id)}
                className={`rounded-full px-6 py-2 text-sm font-bold transition-all ${
                  billing === opt.id
                    ? "bg-emerald-500 text-slate-950 shadow-lg shadow-emerald-500/30"
                    : "text-slate-400 hover:text-white"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div className="mx-auto mb-6 max-w-md rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        <div className="grid gap-5 md:grid-cols-3">
          {PACKAGES.map((pkg, idx) => {
            const Icon = pkg.icon;
            const active = selected === pkg.id;
            const pricing = pkg[billing];
            return (
              <button
                key={pkg.id}
                onClick={() => setSelected(pkg.id)}
                style={{ animationDelay: `${idx * 80}ms` }}
                className={`relative rounded-3xl border p-6 text-left backdrop-blur-2xl transition-all duration-300 ${
                  pkg.highlight ? "md:-my-3 md:py-9" : ""
                } ${
                  active
                    ? "border-emerald-400/60 bg-emerald-500/10 shadow-xl shadow-emerald-500/20 scale-[1.02]"
                    : "border-white/15 bg-white/5 hover:border-white/30 hover:bg-white/10 hover:scale-[1.01]"
                }`}
              >
                {pkg.highlight && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-emerald-500 px-4 py-1 text-xs font-bold text-slate-950 shadow-lg">
                    Paling Populer
                  </span>
                )}
                {pkg.save && (
                  <span className="absolute right-4 top-4 rounded-full bg-amber-500/20 px-2.5 py-0.5 text-xs font-bold text-amber-300">
                    {pkg.save}
                  </span>
                )}
                <div className={`flex h-12 w-12 items-center justify-center rounded-2xl border transition-all ${
                  active ? "border-emerald-400/40 bg-emerald-500/20" : "border-white/10 bg-white/10"
                }`}>
                  <Icon size={22} className={active ? "text-emerald-400" : "text-slate-300"} />
                </div>
                <h3 className="mt-4 text-lg font-bold text-white">{pkg.name}</h3>
                <p className="mt-2">
                  <span className="bg-gradient-to-r from-emerald-300 to-teal-400 bg-clip-text text-3xl font-extrabold text-transparent">
                    {pricing.price}
                  </span>
                  <span className="ml-1 text-sm text-slate-400">{pricing.period}</span>
                </p>
                <ul className="mt-5 space-y-2.5">
                  {pkg.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-slate-300">
                      <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${active ? "bg-emerald-500/25" : "bg-white/10"}`}>
                        <Check size={11} className={active ? "text-emerald-400" : "text-slate-400"} />
                      </span>
                      {f}
                    </li>
                  ))}
                </ul>
                <div className={`mt-6 flex items-center justify-center gap-2 rounded-2xl py-2.5 text-sm font-bold transition-all ${
                  active ? "bg-emerald-500 text-slate-950" : "border border-white/15 text-slate-300"
                }`}>
                  {active && <Check size={15} />}
                  {active ? "Dipilih" : "Pilih Paket"}
                </div>
              </button>
            );
          })}
        </div>

        <div className="mx-auto mt-8 max-w-md">
          <button
            onClick={submit}
            disabled={submitting}
            className="w-full rounded-2xl bg-emerald-500 py-3.5 font-bold text-slate-950 shadow-lg shadow-emerald-500/30 transition-all hover:bg-emerald-400 hover:shadow-emerald-400/40 disabled:opacity-50"
          >
            {submitting ? "Membuat toko..." : `Buat Toko — Paket ${PACKAGES.find((p) => p.id === selected)?.name}`}
          </button>
          <p className="mt-3 text-center text-xs text-slate-500">
            Bisa upgrade/downgrade kapan saja dari panel tenant.
          </p>
        </div>
      </div>
    </div>
  );
}
