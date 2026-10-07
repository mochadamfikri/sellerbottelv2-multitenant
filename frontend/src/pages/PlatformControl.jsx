import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Database, LoaderCircle, Plus, RefreshCw, ServerCrash, Users } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail, fmtDate } from "../lib/api";
import { createAndProvisionTenant } from "../lib/platformControl";
import DatabaseBrowser from "./DatabaseBrowser";

const initialForm = { name: "", slug: "", plan: "demo" };
const plans = ["demo", "monthly", "yearly", "lifetime"];

function statusClasses(status) {
  return {
    active: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
    provisioning: "bg-amber-500/10 text-amber-300 border-amber-500/30",
    suspended: "bg-rose-500/10 text-rose-300 border-rose-500/30",
    disabled: "bg-slate-500/10 text-slate-300 border-slate-500/30",
    failed: "bg-rose-500/10 text-rose-300 border-rose-500/30",
  }[status] || "bg-slate-500/10 text-slate-300 border-slate-500/30";
}

export default function PlatformControl() {
  const [tenants, setTenants] = useState([]);
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState(null);
  // Bot configuration panel (per tenant)
  const [managing, setManaging] = useState(null); // tenant object being configured
  const [botForm, setBotForm] = useState({ token: "", brandName: "", adminIds: "", resellerEnabled: false });
  const [botFeedback, setBotFeedback] = useState(null);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState(null);
  const [savingBot, setSavingBot] = useState(false);
  const [provisioning, setProvisioning] = useState(null);
  const [domains, setDomains] = useState([]);
  const [domainForm, setDomainForm] = useState({ domain: "", purpose: "storefront" });
  const [savingDomain, setSavingDomain] = useState(false);
  const [activeTab, setActiveTab] = useState("tenants");

  const loadDomains = useCallback(async (tenantId) => {
    try {
      const response = await api.get("/v2/platform/domains", { params: { tenant_id: tenantId } });
      setDomains(response.data || []);
    } catch { setDomains([]); }
  }, []);

  const loadTenants = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get("/v2/platform/tenants");
      setTenants(response.data || []);
    } catch (error) {
      const message = formatApiErrorDetail(error.response?.data?.detail);
      setFeedback({ type: "error", message: `Tenant tidak dapat dimuat: ${message}` });
    } finally {
      setLoading(false);
    }
  }, []);

  const deleteTenant = async (tenant) => {
    if (!window.confirm(`Hapus tenant "${tenant.name}" (${tenant.slug})?\n\nSemua data toko, database, dan domainnya akan dihapus permanen. Tidak bisa dibatalkan!`)) {
      return;
    }
    try {
      await api.delete(`/v2/platform/tenants/${tenant.id}`);
      toast.success(`Tenant ${tenant.slug} dihapus.`);
      await loadTenants();
    } catch (error) {
      toast.error(`Gagal hapus: ${formatApiErrorDetail(error.response?.data?.detail)}`);
    }
  };

  useEffect(() => { loadTenants(); }, [loadTenants]);

  // Poll bot provisioning status while it is in-flight so "Kelola Bot"
  // shows the live state (provisioning -> running) without a page reload.
  useEffect(() => {
    if (!managing || provisioning?.status !== "provisioning") return undefined;
    const timer = setInterval(async () => {
      try {
        const response = await api.get(`/v2/platform/tenants/${managing.id}/bot-config`);
        const prov = response.data?.bot_provisioning;
        if (prov) setProvisioning(prov);
        else {
          clearInterval(timer);
          setProvisioning(null);
        }
      } catch {
        // Keep last known state; next tick retries.
      }
    }, 10000);
    return () => clearInterval(timer);
  }, [managing, provisioning?.status]);

  const updateField = (field, value) => setForm((current) => ({ ...current, [field]: value }));

  const openBotManager = async (tenant) => {
    setManaging(tenant);
    setBotForm({ token: "", brandName: "", adminIds: "", resellerEnabled: false });
    setBotFeedback(null);
    setValidation(null);
    setProvisioning(null);
    setDomains([]);
    setDomainForm({ domain: "", purpose: "storefront" });
    loadDomains(tenant.id);
    try {
      const response = await api.get(`/v2/platform/tenants/${tenant.id}/bot-config`);
      const prov = response.data?.bot_provisioning;
      if (prov) setProvisioning(prov);
    } catch (error) {
      // 404 = no bot yet, that's fine.
    }
  };

  const saveDomain = async (event) => {
    event.preventDefault();
    const domain = domainForm.domain.trim().toLowerCase();
    if (!domain) return;
    setSavingDomain(true);
    try {
      await api.post("/v2/platform/domains", {
        domain,
        tenant_id: managing.id,
        purpose: domainForm.purpose,
        origin: "owner_subdomain",
      });
      setDomainForm({ domain: "", purpose: "storefront" });
      loadDomains(managing.id);
      toast.success("Domain terdaftar.");
    } catch (error) {
      toast.error(`Gagal: ${formatApiErrorDetail(error.response?.data?.detail)}`);
    } finally {
      setSavingDomain(false);
    }
  };

  const removeDomain = async (domain) => {
    try {
      await api.delete(`/v2/platform/domains/${encodeURIComponent(domain)}`);
      loadDomains(managing.id);
      toast.success("Domain dihapus.");
    } catch (error) {
      toast.error(`Gagal: ${formatApiErrorDetail(error.response?.data?.detail)}`);
    }
  };

  const closeBotManager = () => {
    setManaging(null);
    setBotFeedback(null);
    setValidation(null);
  };

  const updateBotField = (field, value) => setBotForm((current) => ({ ...current, [field]: value }));

  const validateToken = async () => {
    const token = botForm.token.trim();
    if (!token) {
      setBotFeedback({ type: "error", message: "Isi token bot dulu untuk divalidasi." });
      return;
    }
    setValidating(true);
    setValidation(null);
    setBotFeedback(null);
    try {
      const response = await api.post(`/v2/platform/tenants/${managing.id}/bot/validate`, { telegram_token: token });
      setValidation(response.data);
    } catch (error) {
      const message = formatApiErrorDetail(error.response?.data?.detail);
      setBotFeedback({ type: "error", message: `Token tidak valid: ${message}` });
    } finally {
      setValidating(false);
    }
  };

  const saveBotConfig = async (event) => {
    event.preventDefault();
    setSavingBot(true);
    setBotFeedback(null);
    try {
      const body = { reseller_enabled: botForm.resellerEnabled };
      if (botForm.token.trim()) body.telegram_token = botForm.token.trim();
      if (botForm.brandName.trim()) body.brand_name = botForm.brandName.trim();
      if (botForm.adminIds.trim()) {
        const ids = botForm.adminIds.split(",").map((s) => s.trim()).filter(Boolean);
        const nums = ids.map(Number);
        if (ids.length === 0 || nums.some((n) => !Number.isInteger(n) || n <= 0)) {
          setBotFeedback({ type: "error", message: "Admin ID harus angka dipisah koma, contoh: 123456789, 987654321" });
          setSavingBot(false);
          return;
        }
        body.admin_ids = nums;
      }
      const response = await api.put(`/v2/platform/tenants/${managing.id}/bot-config`, body);
      const bot = response.data || {};
      const prov = bot.bot_provisioning;
      if (prov) setProvisioning(prov);
      const eta = prov?.estimated_minutes ? ` Estimasi selesai ±${prov.estimated_minutes} menit.` : "";
      setBotFeedback({ type: "success", message: `Bot @${bot.username || "?"} berhasil dipasang untuk ${managing.name}.${eta} Notifikasi dikirim ke admin.` });
      toast.success("Konfigurasi bot tersimpan.");
      setBotForm((current) => ({ ...current, token: "" }));
      setValidation(null);
    } catch (error) {
      const message = formatApiErrorDetail(error.response?.data?.detail);
      setBotFeedback({ type: "error", message: `Gagal menyimpan: ${message}` });
    } finally {
      setSavingBot(false);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    const name = form.name.trim();
    const slug = form.slug.trim().toLowerCase();
    if (!name || !slug) {
      setFeedback({ type: "error", message: "Nama dan slug tenant wajib diisi." });
      return;
    }

    setSubmitting(true);
    setFeedback(null);
    try {
      const tenant = await createAndProvisionTenant(api, { name, slug, plan: form.plan });
      setFeedback({ type: "success", message: `${name} berhasil diprovisikan ke database ${tenant.database_name}.` });
      toast.success("Tenant berhasil dibuat dan diprovisikan.");
      setForm(initialForm);
      await loadTenants();
    } catch (error) {
      const message = formatApiErrorDetail(error.response?.data?.detail);
      setFeedback({ type: "error", message: `Provision tenant gagal: ${message}` });
      toast.error("Tenant tidak dapat dibuat atau diprovisikan.");
      await loadTenants();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-mono uppercase tracking-[0.18em] text-cyan-400">Platform RBAC required</p>
          <h1 className="mt-1 text-2xl font-heading font-bold text-white">Platform Control Center</h1>
          <p className="mt-2 text-sm text-slate-400">Daftarkan tenant baru dan provision database-nya dari control plane.</p>
        </div>
        <button type="button" onClick={loadTenants} disabled={loading} className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:border-cyan-500/50 hover:text-cyan-300 disabled:opacity-50">
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} /> Muat ulang
        </button>
      </section>

      {feedback && (
        <div role="alert" className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${feedback.type === "success" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-rose-500/30 bg-rose-500/10 text-rose-200"}`}>
          {feedback.type === "success" ? <CheckCircle2 size={18} className="mt-0.5 shrink-0" /> : <ServerCrash size={18} className="mt-0.5 shrink-0" />}
          <span>{feedback.message}</span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-800">
        <button
          onClick={() => setActiveTab("tenants")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold transition-colors ${
            activeTab === "tenants" ? "border-b-2 border-cyan-400 text-white" : "text-slate-400 hover:text-white"
          }`}
        >
          <Users size={16} /> Tenant
        </button>
        <button
          onClick={() => setActiveTab("database")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-semibold transition-colors ${
            activeTab === "database" ? "border-b-2 border-cyan-400 text-white" : "text-slate-400 hover:text-white"
          }`}
        >
          <Database size={16} /> Database
        </button>
      </div>

      {activeTab === "database" ? (
        <DatabaseBrowser />
      ) : (
      <>

      <section className="rounded-xl border border-slate-800 bg-[#0D1220] p-5 shadow-xl">
        <div className="mb-5 flex items-center gap-2"><Plus size={18} className="text-cyan-400" /><h2 className="font-heading font-semibold">Provision tenant</h2></div>
        <form onSubmit={submit} className="grid gap-4 md:grid-cols-4 md:items-end">
          <label className="block text-sm text-slate-300">Nama tenant
            <input required value={form.name} onChange={(event) => updateField("name", event.target.value)} maxLength={200} placeholder="Acme Store" className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-white outline-none placeholder:text-slate-600 focus:border-cyan-500" />
          </label>
          <label className="block text-sm text-slate-300">Slug
            <input required value={form.slug} onChange={(event) => updateField("slug", event.target.value)} pattern="[a-zA-Z0-9-]+" maxLength={100} placeholder="acme-store" className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-white outline-none placeholder:text-slate-600 focus:border-cyan-500" />
          </label>
          <label className="block text-sm text-slate-300">Plan
            <select value={form.plan} onChange={(event) => updateField("plan", event.target.value)} className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-white outline-none focus:border-cyan-500">
              {plans.map((plan) => <option key={plan} value={plan}>{plan.charAt(0).toUpperCase() + plan.slice(1)}</option>)}
            </select>
          </label>
          <button type="submit" disabled={submitting} className="inline-flex items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 py-2.5 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60">
            {submitting ? <LoaderCircle size={17} className="animate-spin" /> : <Database size={17} />} {submitting ? "Memproses..." : "Buat & provision"}
          </button>
        </form>
      </section>

      <section className="overflow-hidden rounded-xl border border-slate-800 bg-[#0D1220] shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4"><h2 className="font-heading font-semibold">Tenant terdaftar</h2><span className="rounded-full bg-slate-800 px-2.5 py-1 text-xs text-slate-400">{tenants.length} tenant</span></div>
        {loading ? <div className="flex items-center justify-center gap-2 p-10 text-sm text-slate-400"><LoaderCircle size={18} className="animate-spin" /> Memuat tenant...</div> : tenants.length === 0 ? <div className="p-10 text-center text-sm text-slate-500">Belum ada tenant terdaftar.</div> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-slate-900/60 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-5 py-3 font-medium">Tenant</th><th className="px-5 py-3 font-medium">Status</th><th className="px-5 py-3 font-medium">Database</th><th className="px-5 py-3 font-medium">Dibuat</th><th className="px-5 py-3 font-medium">Aksi</th></tr></thead><tbody className="divide-y divide-slate-800">{tenants.map((tenant) => <tr key={tenant.id} className="hover:bg-slate-800/30"><td className="px-5 py-4"><div className="font-medium text-slate-100">{tenant.name}</div><div className="mt-0.5 font-mono text-xs text-slate-500">{tenant.slug}</div></td><td className="px-5 py-4"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${statusClasses(tenant.status)}`}>{tenant.status}</span></td><td className="px-5 py-4 font-mono text-xs text-cyan-200">{tenant.database_name}</td><td className="px-5 py-4 text-slate-400">{fmtDate(tenant.created_at)}</td><td className="px-5 py-4"><div className="flex gap-2"><button type="button" onClick={() => openBotManager(tenant)} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-semibold text-cyan-300 hover:border-cyan-500/50 hover:text-cyan-200">🤖 Kelola Bot</button><button type="button" onClick={() => deleteTenant(tenant)} className="rounded-lg border border-rose-700/50 px-3 py-1.5 text-xs font-semibold text-rose-400 hover:border-rose-500 hover:text-rose-300">🗑️ Hapus</button></div></td></tr>)}</tbody></table></div>
        )}
      </section>

      {managing && (
        <section className="rounded-xl border border-cyan-500/30 bg-[#0D1220] p-5 shadow-xl">
          <div className="mb-5 flex items-center justify-between">
            <h2 className="font-heading font-semibold">🤖 Konfigurasi Bot — {managing.name} <span className="font-mono text-xs text-slate-500">({managing.slug})</span></h2>
            <button type="button" onClick={closeBotManager} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200">Tutup</button>
          </div>

          {provisioning?.status === "provisioning" && (
            <div role="status" className="mb-4 flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
              <LoaderCircle size={18} className="mt-0.5 shrink-0 animate-spin" />
              <span>⏳ Bot sedang dalam proses pemasangan... Estimasi selesai ±{provisioning.estimated_minutes || 2} menit. Mohon jangan simpan ulang.</span>
            </div>
          )}
          {provisioning?.status === "running" && (
            <div role="status" className="mb-4 flex items-start gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
              <CheckCircle2 size={18} className="mt-0.5 shrink-0" />
              <span>✅ Bot sudah aktif dan berjalan.</span>
            </div>
          )}

          {botFeedback && (
            <div role="alert" className={`mb-4 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${botFeedback.type === "success" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-rose-500/30 bg-rose-500/10 text-rose-200"}`}>
              {botFeedback.type === "success" ? <CheckCircle2 size={18} className="mt-0.5 shrink-0" /> : <ServerCrash size={18} className="mt-0.5 shrink-0" />}
              <span>{botFeedback.message}</span>
            </div>
          )}

          <form onSubmit={saveBotConfig} className="grid gap-4 md:grid-cols-2">
            <label className="block text-sm text-slate-300 md:col-span-2">Token Bot Telegram <span className="text-slate-500">(dari BotFather — kosongkan jika tidak ingin mengganti)</span>
              <div className="mt-1.5 flex gap-2">
                <input type="password" value={botForm.token} onChange={(event) => updateBotField("token", event.target.value)} placeholder="123456789:AAH..." autoComplete="off" disabled={provisioning?.status === "provisioning"} className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 font-mono text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-500 disabled:opacity-50" />
                <button type="button" onClick={validateToken} disabled={validating || provisioning?.status === "provisioning"} className="shrink-0 rounded-lg border border-slate-700 px-4 py-2.5 text-sm font-semibold text-cyan-300 hover:border-cyan-500/50 disabled:opacity-50">
                  {validating ? <LoaderCircle size={16} className="animate-spin" /> : "Cek"}
                </button>
              </div>
              {validation && <p className="mt-2 text-sm text-emerald-300">✅ Token valid: @{validation.username} ({validation.bot_name})</p>}
            </label>
            <label className="block text-sm text-slate-300">Nama brand bot
              <input value={botForm.brandName} onChange={(event) => updateBotField("brandName", event.target.value)} maxLength={200} placeholder="Acme Store" className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 text-white outline-none placeholder:text-slate-600 focus:border-cyan-500" />
            </label>
            <label className="block text-sm text-slate-300">Admin ID Telegram <span className="text-slate-500">(pisah koma)</span>
              <input value={botForm.adminIds} onChange={(event) => updateBotField("adminIds", event.target.value)} placeholder="123456789, 987654321" inputMode="numeric" className="mt-1.5 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2.5 font-mono text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-500" />
            </label>
            <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-300 md:col-span-2">
              <input type="checkbox" checked={botForm.resellerEnabled} onChange={(event) => updateBotField("resellerEnabled", event.target.checked)} className="h-4 w-4 accent-cyan-500" />
              <span>Tampilkan tombol <b>"Bikin Bot Sendiri"</b> (reseller) di bot tenant ini</span>
            </label>
            <div className="md:col-span-2">
              <button type="submit" disabled={savingBot || provisioning?.status === "provisioning"} className="inline-flex items-center justify-center gap-2 rounded-lg bg-cyan-500 px-6 py-2.5 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60">
                {savingBot ? <LoaderCircle size={17} className="animate-spin" /> : <CheckCircle2 size={17} />} {savingBot ? "Menyimpan..." : provisioning?.status === "provisioning" ? "Bot sedang dipasang..." : "Simpan konfigurasi bot"}
              </button>
              <p className="mt-3 text-xs text-slate-500">Token disimpan terenkripsi dan tidak pernah ditampilkan kembali. Setelah disimpan, dispatcher otomatis menjalankan bot tenant ini.</p>
            </div>
          </form>

          {/* Domain settings per tenant */}
          <div className="mt-6 border-t border-slate-800 pt-5">
            <h3 className="mb-3 text-sm font-semibold text-slate-200">🌐 Domain tenant</h3>
            {domains.length > 0 ? (
              <ul className="mb-4 space-y-2">
                {domains.map((d) => (
                  <li key={d.domain} className="flex items-center justify-between rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm">
                    <span><span className="font-mono text-cyan-300">{d.domain}</span> <span className="ml-2 rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-400">{d.purpose}</span></span>
                    <button type="button" onClick={() => removeDomain(d.domain)} className="text-xs text-rose-400 hover:text-rose-300">Hapus</button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mb-4 text-xs text-slate-500">Belum ada domain. Daftarkan subdomain untuk tenant ini, misal <span className="font-mono">anasyah-store.idseconnect.my.id</span>.</p>
            )}
            <form onSubmit={saveDomain} className="flex flex-wrap items-end gap-2">
              <label className="block text-xs text-slate-400">Domain
                <input value={domainForm.domain} onChange={(e) => setDomainForm((c) => ({ ...c, domain: e.target.value }))} placeholder="anasyah-store.idseconnect.my.id" className="mt-1 w-64 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-500" />
              </label>
              <label className="block text-xs text-slate-400">Fungsi
                <select value={domainForm.purpose} onChange={(e) => setDomainForm((c) => ({ ...c, purpose: e.target.value }))} className="mt-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500">
                  <option value="storefront">Toko online</option>
                  <option value="stock_panel">Panel stok</option>
                  <option value="api">API</option>
                </select>
              </label>
              <button type="submit" disabled={savingDomain || !domainForm.domain.trim()} className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50">
                {savingDomain ? "Menyimpan..." : "Tambah domain"}
              </button>
            </form>
            <p className="mt-2 text-xs text-slate-500">DNS diarahkan ke server dulu, lalu daftarkan di sini. Pindah environment (dev → production) tinggal ganti DNS + daftar ulang, tanpa ubah kode.</p>
          </div>
        </section>
      )}
      </>
      )}
    </div>
  );
}
