import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, QrCode, CheckCircle2, AlertCircle, Save } from "lucide-react";
import api, { formatApiErrorDetail } from "../lib/api";
import { Switch } from "../components/ui/switch";

const cls = "mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-cyan-500/60";

export default function EnvSettings() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [bot, setBot] = useState(null);
  const [savingBot, setSavingBot] = useState(false);
  const [botForm, setBotForm] = useState({ telegram_token: "", owner_tenant_slug: "idse", admin_ids: "" });
  const [form, setForm] = useState({
    GOPAY_ENABLED: "true",
    GOPAY_LOGIN_METHOD: "password",
    GOPAY_EMAIL: "",
    GOPAY_PASSWORD: "",
    GOPAY_PHONE: "",
    GOPAY_QRIS_STRING: "",
    GOPAY_QR_TIMEOUT_MINUTES: "5",
    GOPAY_POLL_INTERVAL: "15",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/v2/platform/runtime-env");
      const botRes = await api.get("/v2/platform/central-bot/config");
      setData(res.data);
      setBot(botRes.data);
      setBotForm((prev) => ({ ...prev, owner_tenant_slug: botRes.data?.owner_tenant_slug || "idse", admin_ids: (botRes.data?.admin_ids || []).join(", ") }));
      setForm((prev) => ({
        ...prev,
        GOPAY_ENABLED: res.data?.values?.GOPAY_ENABLED || "true",
        GOPAY_LOGIN_METHOD: res.data?.values?.GOPAY_LOGIN_METHOD || "password",
        GOPAY_QR_TIMEOUT_MINUTES: res.data?.values?.GOPAY_QR_TIMEOUT_MINUTES || "5",
        GOPAY_POLL_INTERVAL: res.data?.values?.GOPAY_POLL_INTERVAL || "15",
      }));
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal memuat konfigurasi ENV.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        GOPAY_ENABLED: form.GOPAY_ENABLED,
        GOPAY_LOGIN_METHOD: form.GOPAY_LOGIN_METHOD,
        GOPAY_QR_TIMEOUT_MINUTES: form.GOPAY_QR_TIMEOUT_MINUTES,
        GOPAY_POLL_INTERVAL: form.GOPAY_POLL_INTERVAL,
      };
      if (form.GOPAY_EMAIL.trim()) payload.GOPAY_EMAIL = form.GOPAY_EMAIL.trim();
      if (form.GOPAY_PASSWORD.trim()) payload.GOPAY_PASSWORD = form.GOPAY_PASSWORD.trim();
      if (form.GOPAY_PHONE.trim()) payload.GOPAY_PHONE = form.GOPAY_PHONE.trim();
      if (form.GOPAY_QRIS_STRING.trim()) payload.GOPAY_QRIS_STRING = form.GOPAY_QRIS_STRING.trim();

      const res = await api.put("/v2/platform/runtime-env", payload);
      setData(res.data);
      setForm((prev) => ({
        ...prev,
        GOPAY_PASSWORD: "", // Kosongkan kembali form password setelah disimpan
      }));
      toast.success("Konfigurasi environment berhasil disimpan.");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal menyimpan konfigurasi.");
    } finally {
      setSaving(false);
    }
  };

  const saveBot = async () => {
    setSavingBot(true);
    try {
      const payload = {
        owner_tenant_slug: botForm.owner_tenant_slug.trim(),
        admin_ids: botForm.admin_ids.split(",").map((v) => v.trim()).filter(Boolean).map((v) => Number(v)),
      };
      if (botForm.telegram_token.trim()) payload.telegram_token = botForm.telegram_token.trim();
      const res = await api.put("/v2/platform/central-bot/config", payload);
      setBot(res.data);
      setBotForm((prev) => ({ ...prev, telegram_token: "" }));
      toast.success("Konfigurasi bot pusat berhasil disimpan.");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Konfigurasi bot pusat gagal disimpan.");
    } finally {
      setSavingBot(false);
    }
  };

  if (loading && !data) {
    return <div className="p-8 text-sm text-slate-400">Memuat konfigurasi...</div>;
  }

  const isConfigured = (key) => Boolean(data?.configured?.[key]);

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-xl font-bold font-heading text-slate-100">Konfigurasi Environment & Provider</h1>
        <p className="text-xs text-slate-400 mt-1">
          Pengaturan kredensial GoPay Merchant, metode login, string QRIS, dan parameter runtime sistem.
          Nilai rahasia disimpan terenkripsi di database platform dan tidak pernah dikirimkan kembali ke browser.
        </p>
      </div>

      {/* Card GoPay Merchant */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-5">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/10 flex items-center justify-center">
              <QrCode size={20} className="text-emerald-400" />
            </div>
            <div>
              <h2 className="font-heading font-semibold text-slate-100">GoPay Merchant / GoBiz (QRIS Pusat)</h2>
              <p className="text-xs text-slate-500">Konfigurasi akun dan QRIS GoBiz untuk pembayaran deposit & claim promo bot pusat.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 font-medium">Status:</span>
            <span className={`px-2 py-0.5 rounded text-xs font-semibold ${form.GOPAY_ENABLED === "true" ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30" : "bg-slate-800 text-slate-400"}`}>
              {form.GOPAY_ENABLED === "true" ? "Aktif" : "Nonaktif"}
            </span>
          </div>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-medium text-slate-300">Aktifkan GoPay QRIS</label>
            <select
              className={cls}
              value={form.GOPAY_ENABLED}
              onChange={(e) => setForm({ ...form, GOPAY_ENABLED: e.target.value })}
            >
              <option value="true">Aktif (GOPAY_ENABLED = true)</option>
              <option value="false">Nonaktif (GOPAY_ENABLED = false)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300">Metode Login GoPay</label>
            <select
              className={cls}
              value={form.GOPAY_LOGIN_METHOD}
              onChange={(e) => setForm({ ...form, GOPAY_LOGIN_METHOD: e.target.value })}
            >
              <option value="password">Password (GOPAY_LOGIN_METHOD = password)</option>
              <option value="email_otp">Email + OTP (email_otp)</option>
              <option value="otp">SMS / WhatsApp OTP (otp)</option>
            </select>
          </div>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium text-slate-300">Email GoPay</label>
              <span className="text-[11px] text-slate-500">
                {isConfigured("GOPAY_EMAIL") ? (
                  <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 size={12}/> Tersimpan</span>
                ) : (
                  <span className="text-slate-500">Belum diisi</span>
                )}
              </span>
            </div>
            <input
              type="email"
              className={cls}
              placeholder="Masukkan email merchant GoPay"
              value={form.GOPAY_EMAIL}
              onChange={(e) => setForm({ ...form, GOPAY_EMAIL: e.target.value })}
            />
            <span className="mt-1 block text-[11px] text-slate-500">Kosongkan jika tidak ingin mengubah email tersimpan.</span>
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium text-slate-300">Password GoPay</label>
              <span className="text-[11px] text-slate-500">
                {isConfigured("GOPAY_PASSWORD") ? (
                  <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 size={12}/> Tersimpan</span>
                ) : (
                  <span className="text-slate-500">Belum diisi</span>
                )}
              </span>
            </div>
            <input
              type="password"
              autoComplete="new-password"
              className={cls}
              placeholder="Masukkan password GoBiz / GoPay"
              value={form.GOPAY_PASSWORD}
              onChange={(e) => setForm({ ...form, GOPAY_PASSWORD: e.target.value })}
            />
            <span className="mt-1 block text-[11px] text-slate-500">Nilai password tidak pernah ditampilkan ulang demi keamanan.</span>
          </div>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium text-slate-300">Nomor HP GoPay</label>
              <span className="text-[11px] text-slate-500">
                {isConfigured("GOPAY_PHONE") ? (
                  <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 size={12}/> Tersimpan</span>
                ) : (
                  <span className="text-slate-500">Belum diisi</span>
                )}
              </span>
            </div>
            <input
              type="text"
              className={cls}
              placeholder="08123456789"
              value={form.GOPAY_PHONE}
              onChange={(e) => setForm({ ...form, GOPAY_PHONE: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-300">Timeout QRIS (Menit)</label>
              <input
                type="number"
                min="1"
                max="60"
                className={cls}
                value={form.GOPAY_QR_TIMEOUT_MINUTES}
                onChange={(e) => setForm({ ...form, GOPAY_QR_TIMEOUT_MINUTES: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300">Poll Interval (Detik)</label>
              <input
                type="number"
                min="5"
                max="300"
                className={cls}
                value={form.GOPAY_POLL_INTERVAL}
                onChange={(e) => setForm({ ...form, GOPAY_POLL_INTERVAL: e.target.value })}
              />
            </div>
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between">
            <label className="block text-xs font-medium text-slate-300">String QRIS GoPay</label>
            <span className="text-[11px] text-slate-500">
              {isConfigured("GOPAY_QRIS_STRING") ? (
                <span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 size={12}/> Tersimpan</span>
              ) : (
                <span className="text-amber-400 flex items-center gap-1"><AlertCircle size={12}/> Belum diisi</span>
              )}
            </span>
          </div>
          <textarea
            rows={3}
            className={cls}
            placeholder="00020101021126590014ID.LINKAJA.WWW..."
            value={form.GOPAY_QRIS_STRING}
            onChange={(e) => setForm({ ...form, GOPAY_QRIS_STRING: e.target.value })}
          />
          <span className="mt-1 block text-[11px] text-slate-500">
            String QRIS statis / dinamis dari aplikasi GoBiz merchant. Dipakai generator Node.js untuk membuat QR nominal unik.
          </span>
        </div>
      </div>

      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-5">
        <div className="flex items-center justify-between border-b border-slate-800 pb-4">
          <div className="flex items-center gap-3"><div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center"><ShieldCheck size={20} className="text-cyan-400" /></div><div><h2 className="font-heading font-semibold text-slate-100">Bot Pusat / Owner Sistem</h2><p className="text-xs text-slate-500">Token utama IDSE. Token disimpan terenkripsi dan tidak pernah ditampilkan kembali.</p></div></div>
          <span className={`px-2 py-0.5 rounded text-xs font-semibold ${bot?.configured ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30" : "bg-amber-500/15 text-amber-400 border border-amber-500/30"}`}>{bot?.configured ? "Tersimpan" : "Belum dikonfigurasi"}</span>
        </div>
        {bot?.configured && <div className="rounded-lg bg-slate-950/70 px-3 py-2 text-xs text-slate-400">Bot aktif: <span className="text-slate-200">{bot.bot_name || "-"}</span>{bot.username ? ` (@${bot.username})` : ""}</div>}
        <div className="grid gap-5 sm:grid-cols-2"><label className="block text-xs font-medium text-slate-300">Tenant Owner / Pusat<input className={cls} value={botForm.owner_tenant_slug} onChange={(e) => setBotForm({ ...botForm, owner_tenant_slug: e.target.value })} placeholder="idse" /></label><label className="block text-xs font-medium text-slate-300">Telegram ID Owner/Admin<input className={cls} value={botForm.admin_ids} onChange={(e) => setBotForm({ ...botForm, admin_ids: e.target.value })} placeholder="123456789, 987654321" /><span className="mt-1 block text-[11px] text-slate-500">Pisahkan beberapa ID dengan koma.</span></label></div>
        <label className="block text-xs font-medium text-slate-300">Token Bot Pusat<input type="password" autoComplete="new-password" className={cls} value={botForm.telegram_token} onChange={(e) => setBotForm({ ...botForm, telegram_token: e.target.value })} placeholder={bot?.configured ? "Kosongkan untuk mempertahankan token yang ada" : "123456:AA..."} /><span className="mt-1 block text-[11px] text-slate-500">Token akan divalidasi ke Telegram lalu dienkripsi sebelum disimpan.</span></label>
        <button type="button" disabled={savingBot} onClick={saveBot} className="flex items-center gap-2 rounded-lg border border-cyan-500/40 text-cyan-300 px-4 py-2 text-sm font-semibold hover:bg-cyan-500/10 disabled:opacity-50"><Save size={16}/>{savingBot ? "Menyimpan Bot..." : "Simpan Bot Pusat"}</button>
      </div>

      {/* Info Kunci Keamanan */}
      <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-5 space-y-3">
        <div className="flex items-center gap-2.5">
          <ShieldCheck size={18} className="text-cyan-400" />
          <h3 className="font-heading font-semibold text-sm text-slate-200">Panduan Kunci Keamanan & Webhook Produksi</h3>
        </div>
        <div className="text-xs text-slate-400 space-y-2 leading-relaxed">
          <p>
            • <b>Kunci Enkripsi Stok (INVENTORY_ENCRYPTION_KEY)</b>: Wajib sama persis dengan yang ada di produksi agar seluruh 1.116 baris stok dapat didekripsi saat dibeli pelanggan. Kunci ini dikunci di level backend service demi keamanan.
          </p>
          <p>
            • <b>Webhook Kasera</b>: Gunakan webhook secret yang terdaftar di dashboard Kasera untuk domain <code>pay.idsepos.my.id</code>.
          </p>
          <p>
            • <b>Token Bot Telegram</b>: Bot pusat IDSE akan berjalan otomatis setelah token diaktifkan dan tidak boleh dijalankan ganda dengan VPS lain.
          </p>
        </div>
      </div>

      <div className="pt-2">
        <button
          type="button"
          disabled={saving}
          onClick={save}
          className="flex items-center gap-2 rounded-lg bg-cyan-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-cyan-500 disabled:opacity-50 transition-colors shadow-lg shadow-cyan-950/50"
        >
          <Save size={16} />
          {saving ? "Menyimpan Konfigurasi..." : "Simpan Konfigurasi ENV"}
        </button>
      </div>
    </div>
  );
}
