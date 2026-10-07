import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Package, ShoppingCart, BarChart3, LogOut, FolderOpen, Boxes, Users, Megaphone } from "lucide-react";
import api from "../lib/api";
import { toast } from "sonner";
import TenantProducts from "./TenantProducts";
import TenantCatalogs from "./TenantCatalogs";
import TenantInventory from "./TenantInventory";
import TenantOrders from "./TenantOrders";

export default function TenantAdmin() {
  const navigate = useNavigate();
  const [token, setToken] = useState("");
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState("dashboard");
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [stats, setStats] = useState(null);
  const [catalogs, setCatalogs] = useState([]);
  const [inventory, setInventory] = useState([]);
  const [users, setUsers] = useState([]);
  const [broadcasts, setBroadcasts] = useState([]);
  const [broadcastMsg, setBroadcastMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [showCatalogForm, setShowCatalogForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", description: "", active: true });
  const [catalogForm, setCatalogForm] = useState({ name: "", description: "" });

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};

  const doLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await api.post("/public/tenant/login", loginForm);
      if (!data.token) throw new Error("No token in response");
      setToken(data.token);
      // Set default auth header untuk semua request tenant
      api.defaults.headers.common["Authorization"] = `Bearer ${data.token}`;
      setMe({
        tenant_slug: data.tenant_slug,
        email: data.email,
        store_name: data.store_name,
      });
      toast.success("Selamat datang!");
      setTimeout(() => loadTabData("dashboard", data.token), 100);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Login gagal.");
    } finally {
      setLoading(false);
    }
  };

  const loadTabData = async (tabId, tok = token) => {
    const headers = tok ? { Authorization: `Bearer ${tok}` } : {};
    try {
      if (tabId === "dashboard") {
        const { data } = await api.get("/public/tenant/stats", { headers });
        setStats(data);
      } else if (tabId === "products") {
        const { data } = await api.get("/public/tenant/products", { headers });
        setProducts(data.products || []);
      } else if (tabId === "catalogs") {
        const { data } = await api.get("/public/tenant/catalogs", { headers });
        setCatalogs(data.catalogs || []);
      } else if (tabId === "inventory") {
        const { data } = await api.get("/public/tenant/inventory", { headers });
        setInventory(data.inventory || []);
      } else if (tabId === "orders") {
        const { data } = await api.get("/public/tenant/orders", { headers });
        setOrders(data.orders || []);
      } else if (tabId === "users") {
        const { data } = await api.get("/public/tenant/users", { headers });
        setUsers(data.users || []);
      } else if (tabId === "broadcast") {
        const { data } = await api.get("/public/tenant/broadcasts", { headers });
        setBroadcasts(data.broadcasts || []);
      }
    } catch (err) {
      console.error("Load failed:", tabId, err.message);
    }
  };

  const handleTab = (tabId) => {
    setTab(tabId);
    loadTabData(tabId);
  };

  const logout = () => {
    setToken("");
    setMe(null);
    navigate("/");
  };

  // Login form
  if (!me) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
        <div className="w-full max-w-sm rounded-3xl border border-white/15 bg-white/5 p-8 backdrop-blur-2xl">
          <h1 className="text-center text-xl font-extrabold text-white">Panel Tenant</h1>
          <p className="mt-1 text-center text-xs text-slate-500">Kelola tokomu sendiri</p>
          <form onSubmit={doLogin} className="mt-6 space-y-4">
            <input
              type="email" required placeholder="Email"
              value={loginForm.email} onChange={(e) => setLoginForm({ ...loginForm, email: e.target.value })}
              className="w-full rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500"
            />
            <input
              type="password" required placeholder="Password"
              value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })}
              className="w-full rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500"
            />
            <button disabled={loading} className="w-full rounded-2xl bg-emerald-500 py-3 font-bold text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
              {loading ? "Masuk..." : "Masuk"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  const tabs = [
    { id: "dashboard", label: "Dashboard", icon: BarChart3 },
    { id: "products", label: "Produk", icon: Package },
    { id: "catalogs", label: "Katalog", icon: FolderOpen },
    { id: "inventory", label: "Inventory", icon: Boxes },
    { id: "orders", label: "Order", icon: ShoppingCart },
    { id: "users", label: "Pengguna", icon: Users },
    { id: "broadcast", label: "Broadcast", icon: Megaphone },
  ];

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="border-b border-white/10 bg-white/5 px-4 py-3">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          <div>
            <h1 className="font-bold text-white">{me.store_name || "Panel Tenant"}</h1>
            <p className="text-xs text-slate-500">{me.tenant_slug}</p>
          </div>
          <button onClick={logout} className="flex items-center gap-1.5 rounded-xl border border-white/15 px-3 py-2 text-xs text-slate-300 hover:bg-white/10">
            <LogOut size={14} /> Keluar
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-4xl px-4 py-4">
        <div className="flex flex-wrap gap-2">
          {tabs.map((t) => (
            <button
              key={t.id} onClick={() => handleTab(t.id)}
              className={`flex items-center gap-1.5 rounded-2xl px-4 py-2.5 text-sm font-semibold ${tab === t.id ? "bg-emerald-500 text-slate-950" : "bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white"}`}
            >
              <t.icon size={16} /> {t.label}
            </button>
          ))}
        </div>

        {tab === "dashboard" && (
          <div className="mt-4 grid grid-cols-2 gap-3">
            {[
              { label: "Produk", value: stats?.products || 0 },
              { label: "Order", value: stats?.orders || 0 },
              { label: "Katalog", value: stats?.catalogs || 0 },
              { label: "Pengguna", value: stats?.users || 0 },
            ].map((s) => (
              <div key={s.label} className="rounded-2xl border border-white/10 bg-white/5 p-5">
                <p className="text-xs text-slate-500">{s.label}</p>
                <p className="mt-1 text-3xl font-extrabold text-white">{s.value}</p>
              </div>
            ))}
          </div>
        )}

        {tab === "products" && <div className="mt-4"><TenantProducts /></div>}

        {tab === "catalogs" && <div className="mt-4"><TenantCatalogs /></div>}

        {tab === "inventory" && <div className="mt-4"><TenantInventory /></div>}

        {tab === "orders" && <div className="mt-4"><TenantOrders /></div>}

        {tab === "users" && (
          <div className="mt-4">
            <div className="mb-3 rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="text-xs text-slate-500">Total Pengguna</p>
              <p className="text-2xl font-extrabold text-white">{users.length}</p>
            </div>
            <div className="space-y-2">
              {users.map((u, i) => (
                <div key={u._id || i} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-sm font-semibold text-white">{u.name || u.username || `User ${i + 1}`}</p>
                  <p className="text-xs text-slate-500">ID: {u.telegram_id || u._id}</p>
                </div>
              ))}
              {users.length === 0 && <p className="py-8 text-center text-sm text-slate-500">Belum ada pengguna.</p>}
            </div>
          </div>
        )}

        {tab === "broadcast" && (
          <div className="mt-4">
            <form onSubmit={async (e) => { e.preventDefault(); if (!broadcastMsg.trim()) return; try { await api.post("/public/tenant/broadcast", { message: broadcastMsg.trim() }, { headers: authHeaders }); toast.success("Broadcast dikirim."); setBroadcastMsg(""); loadTabData("broadcast"); } catch (err) { toast.error(err.response?.data?.detail || "Gagal."); } }} className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <p className="mb-2 text-sm font-semibold text-white">Kirim Broadcast ke Bot</p>
              <textarea value={broadcastMsg} onChange={(e) => setBroadcastMsg(e.target.value)} placeholder="Tulis pesan..." rows={4} className="w-full rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500" />
              <button className="mt-3 flex items-center gap-1.5 rounded-2xl bg-emerald-500 px-4 py-2.5 text-sm font-bold text-slate-950 hover:bg-emerald-400">
                <Send size={16} /> Kirim
              </button>
            </form>
            <div className="mt-4 space-y-2">
              {broadcasts.map((b, i) => (
                <div key={b._id || i} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <p className="text-sm text-white">{b.message?.substring(0, 100)}</p>
                  <p className="mt-1 text-xs text-slate-500">{b.status}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4">
          <div className="w-full max-w-md rounded-3xl border border-white/15 bg-slate-900/95 p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-bold text-white">{editing ? "Edit" : "Tambah"} Produk</h2>
              <button onClick={() => setShowForm(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <form onSubmit={async (e) => { e.preventDefault(); try { if (editing) { await api.put(`/public/tenant/products/${editing._id}`, form, { headers: authHeaders }); } else { await api.post("/public/tenant/products", form, { headers: authHeaders }); } toast.success("Berhasil."); setShowForm(false); loadTabData("products"); } catch (err) { toast.error(err.response?.data?.detail || "Gagal."); } }} className="space-y-4">
              <input required placeholder="Nama produk" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500" />
              <textarea placeholder="Deskripsi" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} className="w-full rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500" />
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} className="h-4 w-4" /> Aktif
              </label>
              <button className="w-full rounded-2xl bg-emerald-500 py-3 font-bold text-slate-950">Simpan</button>
            </form>
          </div>
        </div>
      )}

      {showCatalogForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4">
          <div className="w-full max-w-md rounded-3xl border border-white/15 bg-slate-900/95 p-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="font-bold text-white">Tambah Katalog</h2>
              <button onClick={() => setShowCatalogForm(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <form onSubmit={async (e) => { e.preventDefault(); try { await api.post("/public/tenant/catalogs", catalogForm, { headers: authHeaders }); toast.success("Berhasil."); setShowCatalogForm(false); loadTabData("catalogs"); } catch (err) { toast.error(err.response?.data?.detail || "Gagal."); } }} className="space-y-4">
              <input required placeholder="Nama katalog" value={catalogForm.name} onChange={(e) => setCatalogForm({ ...catalogForm, name: e.target.value })} className="w-full rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500" />
              <input placeholder="Deskripsi" value={catalogForm.description} onChange={(e) => setCatalogForm({ ...catalogForm, description: e.target.value })} className="w-full rounded-2xl border border-white/15 bg-white/10 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500" />
              <button className="w-full rounded-2xl bg-emerald-500 py-3 font-bold text-slate-950">Simpan</button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
