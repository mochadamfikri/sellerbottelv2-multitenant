import { useState, useRef, useEffect } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { ShieldCheck, ArrowLeft, MailCheck } from "lucide-react";
import api from "../lib/api";
import { toast } from "sonner";

/**
 * Halaman verifikasi OTP (/daftar/verifikasi)
 * Tema: Glassy OTP ala video referensi — 6 kotak kaca, glowing.
 * Menerima data form dari /daftar via location.state, validasi OTP,
 * lalu selesaikan pendaftaran dan redirect ke /daftar/sukses.
 */
function GlassyOtpInput({ value, onChange, disabled, shakeKey }) {
  const refs = useRef([]);
  const digits = (value || "").padEnd(6, " ").slice(0, 6).split("");

  const focusBox = (i) => refs.current[i]?.focus();

  const handleChange = (i, e) => {
    const v = e.target.value.replace(/\D/g, "").slice(-1);
    const next = digits.map((d, j) => (j === i ? v || " " : d)).join("").trim();
    onChange(next);
    if (v && i < 5) setTimeout(() => focusBox(i + 1), 10);
  };

  const handleKeyDown = (i, e) => {
    if (e.key === "Backspace" && !digits[i].trim() && i > 0) {
      e.preventDefault();
      const next = digits.map((d, j) => (j === i - 1 ? " " : d)).join("").trim();
      onChange(next);
      setTimeout(() => focusBox(i - 1), 10);
    }
  };

  const handlePaste = (e) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (pasted) {
      onChange(pasted);
      setTimeout(() => focusBox(Math.min(pasted.length, 5)), 10);
    }
  };

  useEffect(() => {
    setTimeout(() => focusBox(0), 300);
  }, []);

  return (
    <>
      <style>{`
        @keyframes otp-pop-in {
          0% { opacity: 0; transform: translateY(12px) scale(0.9); }
          60% { transform: translateY(-2px) scale(1.03); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes otp-glow-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.35); }
          50% { box-shadow: 0 0 20px 4px rgba(52, 211, 153, 0.25); }
        }
        @keyframes otp-shake {
          0%, 100% { transform: translateX(0); }
          20%, 60% { transform: translateX(-6px); }
          40%, 80% { transform: translateX(6px); }
        }
        .otp-box { animation: otp-pop-in 0.45s cubic-bezier(0.22, 1, 0.36, 1) backwards; }
        .otp-box:focus { animation: otp-glow-pulse 1.6s ease-in-out infinite; }
        .otp-error .otp-box { animation: otp-shake 0.4s ease; border-color: rgba(244, 63, 94, 0.6) !important; }
      `}</style>
      <div className={`flex justify-center gap-2.5 sm:gap-3 ${shakeKey ? "otp-error" : ""}`} onPaste={handlePaste} key={shakeKey}>
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => (refs.current[i] = el)}
            value={d.trim()}
            onChange={(e) => handleChange(i, e)}
            onKeyDown={(e) => handleKeyDown(i, e)}
            onFocus={(e) => e.target.select()}
            inputMode="numeric"
            autoComplete={i === 0 ? "one-time-code" : "off"}
            maxLength={1}
            disabled={disabled}
            style={{ animationDelay: `${i * 60}ms` }}
            className="otp-box h-14 w-12 rounded-2xl border border-white/20 bg-white/10 text-center text-2xl font-bold text-white shadow-lg shadow-black/30 outline-none backdrop-blur-xl transition-all placeholder:text-slate-500 focus:border-emerald-400/60 focus:bg-white/15 focus:ring-2 focus:ring-emerald-400/30 disabled:opacity-40 sm:h-16 sm:w-14"
          />
        ))}
      </div>
    </>
  );
}

export default function VerifyOtp() {
  const navigate = useNavigate();
  const location = useLocation();
  const formData = location.state?.formData;

  const [code, setCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [resending, setResending] = useState(false);
  const [error, setError] = useState("");
  const [shakeKey, setShakeKey] = useState(0);

  useEffect(() => {
    if (!formData?.email) {
      navigate("/daftar", { replace: true });
    }
  }, [formData, navigate]);

  if (!formData?.email) return null;

  const verify = async (e) => {
    e?.preventDefault();
    if (code.trim().length !== 6) {
      setError("Kode OTP harus 6 digit.");
      return;
    }
    setError("");
    setVerifying(true);
    try {
      const res = await api.post("/public/register/verify-code", {
        email: formData.email.trim().toLowerCase(),
        code: code.trim(),
      });
      toast.success("Email terverifikasi!");
      navigate("/daftar/paket", {
        state: { formData: { ...formData }, verifyToken: res.data.verify_token },
      });
    } catch (err) {
      setError(err.response?.data?.detail || "Kode salah atau kadaluarsa.");
      setShakeKey((k) => k + 1);
    } finally {
      setVerifying(false);
    }
  };

  const resend = async () => {
    setResending(true);
    setError("");
    try {
      await api.post("/public/register/request-code", { email: formData.email.trim().toLowerCase() });
      toast.success("Kode baru dikirim ke email kamu.");
      setCode("");
    } catch (err) {
      setError(err.response?.data?.detail || "Gagal mengirim ulang kode.");
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 bg-[radial-gradient(ellipse_at_top,rgba(16,185,129,0.15),transparent_60%)] px-4 py-8">
      <div className="w-full max-w-md">
        <Link to="/daftar" className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-white">
          <ArrowLeft size={16} /> Kembali
        </Link>

        <div className="rounded-3xl border border-white/15 bg-white/5 p-8 shadow-2xl shadow-black/40 backdrop-blur-2xl">
          <div className="mb-6 text-center">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-emerald-400/30 bg-emerald-500/15 shadow-lg shadow-emerald-500/20 backdrop-blur-xl">
              <MailCheck size={28} className="text-emerald-400" />
            </div>
            <h1 className="mt-4 text-xl font-extrabold tracking-tight text-white">
              Verifikasi Email
            </h1>
            <p className="mt-2 text-sm text-slate-400">
              Masukkan 6 digit kode yang dikirim ke
              <br />
              <span className="font-semibold text-slate-200">{formData.email}</span>
            </p>
          </div>

          {error && (
            <div className="mb-5 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
              {error}
            </div>
          )}

          <form onSubmit={verify}>
            <GlassyOtpInput value={code} onChange={setCode} disabled={verifying} shakeKey={shakeKey} />

            <button
              type="submit"
              disabled={verifying || code.trim().length !== 6}
              className="mt-8 w-full rounded-2xl bg-emerald-500 py-3.5 font-bold text-slate-950 shadow-lg shadow-emerald-500/30 transition-all hover:bg-emerald-400 hover:shadow-emerald-400/40 disabled:opacity-40"
            >
              {verifying ? "Memverifikasi..." : "Verifikasi & Buat Toko"}
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-slate-400">
            Tidak terima kode?{" "}
            <button onClick={resend} disabled={resending} className="font-semibold text-emerald-400 hover:underline disabled:opacity-40">
              {resending ? "Mengirim..." : "Kirim ulang"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
