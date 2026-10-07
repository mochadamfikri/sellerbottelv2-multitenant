import { useState, useEffect } from "react";
import { Store, Package, LogOut, Mail, Lock } from "lucide-react";
import api from "../lib/api";
import { toast } from "sonner";

/**
 * Panel admin khusus tenant — terpisah dari panel owner.
 * Login pakai email + password yang dibuat saat pendaftaran.
 * Kelola produk/stok toko sendiri.
 */
export default function TenantPanel() {
  const [token, setToken] = useState(() => localStorage.getItem("tenant_token") || "");
  const [me, setMe] = useState(null);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const authApi = (t) =>
    api.create({ headers: { Authorization: `Bearer ${t}` } });

  const loadMe = async (t) => {
    try {
      const res = await api.get("/public/tenant/me", {
        headers: { Authorization: `Bearer ${t}` },
      });
      setMe(res.data);
      const prod = await api.get("/public/tenant/products", {
        headers: { Authorization: `Bearer ${t}` },
      });
      setProducts(prod.data.products || []);
    } catch {
      setToken("");
      localStorage.removeItem("tenant_token");
      setMe(null);
    }
  };

  useEffect(() => {
    if (token) loadMe(token);
  }, []);

  const login = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await api.post("/public/tenant/login", { email, password });
      const t = res.data.token;
      setToken(t);
      localStorage.setItem("tenant_token", t);
      toast.success(`Selamat datang, ${res.data.tenant_slug}!`);
      loadMe(t);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Login gagal.");
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    setToken("");
    localStorage.removeItem("tenant_token");
    setMe(null);
    setProducts([]);
  };

  if (!token || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
        <div className="w-full max-w-sm rounded-3xl border border-white/15 bg-white/5 p-8 backdrop-blur-2xl">
          <div className="mb-6 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/15">
              <Store size={24} className="text-emerald-400" />
            </div>
            <h1 className="mt-3 text-xl font-bold text-white">Panel Tenant</h1>
            <p className="mt-1 text-sm text-slate-400">Kelola tokomu sendiri</p>
          </div>
          <form onSubmit={login} className="space-y-4">
            <div className="relative">
              <Mail size={17} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="Email" type="email" required
                className="w-full rounded-2xl border border-white/15 bg-white/10 py-3 pl-11 pr-4 text-sm text-white outline-none placeholder:text-slate-500 focus:border-emerald-400/60"
              />
            </div>
            <div className="relative">
              <Lock size={17} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={password} onChange={(e) => setPassword(e.target.value)}
                placeholder="Password" type="password" required
                className="w-full rounded-2xl border border-white/15 bg-white/10 py-3 pl-11 pr-4 text-sm text-white outline-none placeholder:text-slate-500 focus:border-emerald-400/60"
              />
            </div>
            <button
              type="submit" disabled={loading}
              className="w-full rounded-2xl bg-emerald-500 py-3 font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
            >
              {loading ? "Masuk..." : "Masuk"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-6">
      <div className="mx-auto max-w-4xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">🏪 {me.tenant_slug}</h1>
            <p className="text-sm text-slate-400">{me.email}</p>
          </div>
          <button
            onClick={logout}
            className="flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/5"
          >
            <LogOut size={15} /> Keluar
          </button>
        </div>

        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl">
          <h2 className="mb-4 flex items-center gap-2 font-bold text-white">
            <Package size={18} /> Produk ({products.length})
          </h2>
          {products.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              Belum ada produk. Tambahkan produk via bot Telegram tokomu.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {products.map((p) => (
                <div key={p._id} className="rounded-2xl border border-white/10 bg-black/20 p-4">
                  <p className="font-semibold text-white">{p.name || "Tanpa nama"}</p>
                  <p className="mt-1 text-sm text-slate-400">
                    Rp {(p.price_idr || 0).toLocaleString("id-ID")}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    Stok: {p.stock ?? "-"} | {p.active ? "✅ Aktif" : "❌ Nonaktif"}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        <p className="mt-4 text-center text-xs text-slate-600">
          Kelola produk lengkap (tambah/edit/hapus) via bot Telegram tokomu
        </p>
      </div>
    </div>
  );
}
