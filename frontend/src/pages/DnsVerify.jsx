import { useState, useEffect, useRef } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { Globe, RefreshCw, X, CheckCircle, AlertCircle, Copy, ChevronDown } from "lucide-react";
import api from "../lib/api";

/**
 * Halaman verifikasi DNS untuk custom domain (/daftar/dns).
 * User tidak bisa skip sampai DNS terverifikasi.
 * - Auto-check tiap 5 detik
 * - Tombol refresh manual dengan cooldown 60 detik
 * - Tombol cancel dengan konfirmasi
 */
export default function DnsVerify() {
  const navigate = useNavigate();
  const location = useLocation();
  const { domain, formData, verifyToken, pkg } = location.state || {};

  const [status, setStatus] = useState("checking"); // checking | connected | failed
  const [cooldown, setCooldown] = useState(0);
  const [showCancel, setShowCancel] = useState(false);
  const [tutorialOpen, setTutorialOpen] = useState(true);
  const intervalRef = useRef(null);
  const cooldownRef = useRef(null);

  useEffect(() => {
    if (!domain) {
      navigate("/daftar", { replace: true });
      return;
    }
    // Auto-check tiap 5 detik
    checkDns();
    intervalRef.current = setInterval(checkDns, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (cooldownRef.current) clearInterval(cooldownRef.current);
    };
  }, [domain]);

  // Cooldown timer
  useEffect(() => {
    if (cooldown > 0) {
      cooldownRef.current = setTimeout(() => setCooldown((c) => c - 1), 1000);
      return () => clearTimeout(cooldownRef.current);
    }
  }, [cooldown]);

  const checkDns = async () => {
    try {
      const res = await api.get("/public/register/check-dns", { params: { domain } });
      if (res.data.connected) {
        setStatus("connected");
        if (intervalRef.current) clearInterval(intervalRef.current);
        // DNS OK → buat tenant sekarang
        try {
          const regRes = await api.post("/public/register", {
            username: formData.username.trim().toLowerCase(),
            store_name: formData.storeName.trim(),
            email: formData.email.trim().toLowerCase(),
            verify_token: verifyToken,
            package: pkg || "demo",
            whatsapp: formData.whatsapp.trim(),
            password: formData.password,
            bot_token: formData.botToken?.trim() || null,
            admin_telegram_id: formData.adminTelegramId?.trim() || null,
            has_domain: true,
            custom_domain: domain,
            subdomain: formData.subdomain || formData.username.trim().toLowerCase(),
          });
          setTimeout(() => {
            navigate("/daftar/sukses", { state: regRes.data });
          }, 1500);
        } catch (err) {
          setStatus("failed");
        }
      } else {
        setStatus("failed");
      }
    } catch {
      setStatus("failed");
    }
  };

  const handleRefresh = () => {
    if (cooldown > 0) return;
    setCooldown(60);
    setStatus("checking");
    checkDns();
  };

  const handleCancel = (confirm) => {
    if (!confirm) {
      setShowCancel(false);
      return;
    }
    // Batalkan → kembali ke pendaftaran
    navigate("/daftar", { replace: true });
  };

  if (!domain) return null;

  const dnsTarget = "16.78.106.9"; // IP VPS — TODO: ambil dari config

  return (
    <div className="min-h-screen bg-slate-950 bg-[radial-gradient(ellipse_at_top,rgba(16,185,129,0.12),transparent_60%)] px-4 py-8">
      <div className="mx-auto max-w-lg">
        <div className="rounded-3xl border border-white/15 bg-white/5 p-6 shadow-2xl backdrop-blur-2xl sm:p-8">
          {/* Header */}
          <div className="mb-6 text-center">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-500/15">
              <Globe size={28} className="text-amber-400" />
            </div>
            <h1 className="mt-4 text-xl font-extrabold text-white">Hubungkan Domain Anda</h1>
            <p className="mt-2 text-sm text-slate-400">
              Domain <span className="font-bold text-white">{domain}</span> belum terhubung ke server kami.
            </p>
          </div>

          {/* Status */}
          {status === "failed" && (
            <div className="mb-4 rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
              <AlertCircle size={16} className="mr-1.5 inline" />
              Kami belum terhubung ke domain anda, pastikan ikuti tutorial di atas dengan benar.
            </div>
          )}
          {status === "connected" && (
            <div className="mb-4 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
              <CheckCircle size={16} className="mr-1.5 inline" />
              Domain terhubung! Menyelesaikan pendaftaran...
            </div>
          )}
          {status === "checking" && (
            <div className="mb-4 flex items-center justify-center gap-2 text-sm text-slate-400">
              <RefreshCw size={16} className="animate-spin" />
              Mengecek koneksi domain...
            </div>
          )}

          {/* Tutorial */}
          <div className="mb-6 rounded-2xl border border-white/10 bg-white/5">
            <button
              onClick={() => setTutorialOpen((o) => !o)}
              className="flex w-full items-center justify-between px-4 py-3 text-sm font-bold text-white"
            >
              📖 Cara setting DNS domain anda
              <ChevronDown size={16} className={`transition-transform ${tutorialOpen ? "rotate-180" : ""}`} />
            </button>
            {tutorialOpen && (
              <div className="space-y-3 border-t border-white/10 px-4 py-4 text-sm text-slate-300">
                <div>
                  <p className="font-semibold text-white">1. Buka DNS management domain anda</p>
                  <p className="mt-1 text-xs text-slate-400">
                    Login ke tempat anda beli domain (misal Niagahoster, Domainesia, Cloudflare, dll),
                    cari menu "DNS Management" atau "Kelola DNS".
                  </p>
                </div>
                <div>
                  <p className="font-semibold text-white">2. Tambah A Record</p>
                  <div className="mt-2 rounded-xl bg-slate-950/50 p-3 font-mono text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Type:</span>
                      <span className="text-white">A</span>
                    </div>
                    <div className="mt-1 flex justify-between">
                      <span className="text-slate-500">Name/Host:</span>
                      <span className="text-white">@</span>
                    </div>
                    <div className="mt-1 flex items-center justify-between">
                      <span className="text-slate-500">Value/IP:</span>
                      <span className="flex items-center gap-1.5 text-white">
                        {dnsTarget}
                        <button
                          onClick={() => navigator.clipboard?.writeText(dnsTarget)}
                          className="text-slate-400 hover:text-white"
                        >
                          <Copy size={13} />
                        </button>
                      </span>
                    </div>
                    <div className="mt-1 flex justify-between">
                      <span className="text-slate-500">TTL:</span>
                      <span className="text-white">Auto / 3600</span>
                    </div>
                  </div>
                </div>
                <div>
                  <p className="font-semibold text-white">3. Tambah juga untuk www (opsional)</p>
                  <div className="mt-2 rounded-xl bg-slate-950/50 p-3 font-mono text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Type:</span>
                      <span className="text-white">A</span>
                    </div>
                    <div className="mt-1 flex justify-between">
                      <span className="text-slate-500">Name/Host:</span>
                      <span className="text-white">www</span>
                    </div>
                    <div className="mt-1 flex justify-between">
                      <span className="text-slate-500">Value/IP:</span>
                      <span className="text-white">{dnsTarget}</span>
                    </div>
                  </div>
                </div>
                <p className="text-xs text-slate-500">
                  ⏳ DNS biasanya butuh 5-30 menit untuk tersebar. Halaman ini mengecek otomatis tiap 5 detik.
                </p>
              </div>
            )}
          </div>

          {/* Tombol */}
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={handleRefresh}
              disabled={cooldown > 0 || status === "connected"}
              className="flex items-center justify-center gap-2 rounded-2xl bg-emerald-500 py-3.5 font-bold text-slate-950 transition-all hover:bg-emerald-400 disabled:opacity-50"
            >
              <RefreshCw size={17} className={status === "checking" ? "animate-spin" : ""} />
              {cooldown > 0 ? `Tunggu ${cooldown}s` : "Refresh"}
            </button>
            <button
              onClick={() => setShowCancel(true)}
              disabled={status === "connected"}
              className="flex items-center justify-center gap-2 rounded-2xl border border-white/15 bg-white/5 py-3.5 font-bold text-slate-300 transition-all hover:bg-white/10 disabled:opacity-50"
            >
              <X size={17} />
              Batal
            </button>
          </div>
          <p className="mt-3 text-center text-xs text-slate-500">
            Sistem mengecek otomatis tiap 5 detik. Tombol refresh ada jeda 60 detik anti-spam.
          </p>
        </div>
      </div>

      {/* Popup konfirmasi batal */}
      {showCancel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-3xl border border-white/15 bg-slate-900/95 p-6 shadow-2xl backdrop-blur-2xl">
            <h2 className="text-lg font-bold text-white">Batalkan Pendaftaran?</h2>
            <p className="mt-2 text-sm text-slate-400">
              Yakin membatalkan seluruh proses pendaftaran? Data yang sudah diisi akan hilang.
            </p>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <button
                onClick={() => handleCancel(false)}
                className="rounded-2xl border border-white/15 bg-white/5 py-3 font-bold text-slate-300 hover:bg-white/10"
              >
                Tidak
              </button>
              <button
                onClick={() => handleCancel(true)}
                className="rounded-2xl bg-rose-500 py-3 font-bold text-white hover:bg-rose-400"
              >
                Ya, Batalkan
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
