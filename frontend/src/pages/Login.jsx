import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { formatApiErrorDetail } from "../lib/api";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await login(email, password);
      // Redirect berdasarkan domain
      const host = window.location.hostname.toLowerCase();
      if (host === "idsehub.my.id") {
        navigate("/platform-control");
      } else {
        navigate("/admin");
      }
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || err.message);
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen bg-[#0B0F17] flex items-center justify-center p-4 relative overflow-hidden">
      <div className="absolute inset-0 opacity-[0.04]" style={{ backgroundImage: "linear-gradient(#00F0FF 1px, transparent 1px), linear-gradient(90deg, #00F0FF 1px, transparent 1px)", backgroundSize: "48px 48px" }} />
      <div className="w-full max-w-sm relative">
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-8 shadow-2xl backdrop-blur">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-lg bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center">
              <ShieldCheck className="text-cyan-400" size={20} />
            </div>
            <div>
              <h1 className="font-heading text-xl font-bold text-slate-100 tracking-tight">
                {typeof window !== "undefined" && window.location.hostname.toLowerCase() === "idsehub.my.id"
                  ? "IDSE Hub"
                  : "TokoBot Admin"}
              </h1>
              <p className="text-xs text-slate-500 font-mono uppercase tracking-widest">
                {typeof window !== "undefined" && window.location.hostname.toLowerCase() === "idsehub.my.id"
                  ? "Platform Control"
                  : "Panel Kontrol"}
              </p>
            </div>
          </div>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="text-xs text-slate-400 uppercase tracking-wide font-medium">Email</label>
              <input
                data-testid="admin-email-input"
                type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
                className="mt-1.5 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60 transition-colors"
                placeholder="admin@tokobot.com"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 uppercase tracking-wide font-medium">Password</label>
              <input
                data-testid="admin-password-input"
                type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                className="mt-1.5 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60 transition-colors"
                placeholder="••••••••"
              />
            </div>
            {error && <p data-testid="login-error" className="text-xs text-rose-400 bg-rose-500/10 border border-rose-500/20 rounded-lg px-3 py-2">{error}</p>}
            <button
              data-testid="admin-login-submit"
              type="submit" disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-semibold rounded-lg py-2.5 transition-colors"
            >
              {loading ? "Memproses..." : "Masuk"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
