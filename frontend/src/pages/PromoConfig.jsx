import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { Save, ArrowUp, ArrowDown, Eye, EyeOff, Plus, Trash2, LoaderCircle } from "lucide-react";
import api, { formatApiErrorDetail } from "../lib/api";

/**
 * Landing page configurator — panel.idseconnect.my.id
 * Edits everything on the promo landing: hero text, buttons (order/label/
 * url/visibility/style), highlights, section visibility, accent color, CTA.
 */

const ACCENTS = ["emerald", "blue", "amber", "rose", "violet", "cyan"];
const STYLES = ["primary", "secondary", "outline"];
const SECTIONS = [
  ["simulation", "Simulasi transaksi"],
  ["features", "Fitur unggulan"],
  ["steps", "Langkah mudah"],
  ["faq", "FAQ"],
  ["final_cta", "CTA akhir"],
];

const ACCENT_DOT = {
  emerald: "bg-emerald-500", blue: "bg-blue-500", amber: "bg-amber-500",
  rose: "bg-rose-500", violet: "bg-violet-500", cyan: "bg-cyan-500",
};

const inputCls = "w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-500";

export default function PromoConfig() {
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/v2/platform/promo-config");
      setCfg(r.data);
    } catch {
      toast.error("Gagal memuat konfigurasi.");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const set = (patch) => setCfg((c) => ({ ...c, ...patch }));
  const setHero = (patch) => setCfg((c) => ({ ...c, hero: { ...c.hero, ...patch } }));
  const setCta = (patch) => setCfg((c) => ({ ...c, final_cta: { ...c.final_cta, ...patch } }));
  const setSection = (key, val) => setCfg((c) => ({ ...c, sections: { ...c.sections, [key]: val } }));

  const moveButton = (i, dir) => {
    setCfg((c) => {
      const b = [...c.buttons];
      const j = i + dir;
      if (j < 0 || j >= b.length) return c;
      [b[i], b[j]] = [b[j], b[i]];
      return { ...c, buttons: b };
    });
  };

  const editButton = (i, patch) => {
    setCfg((c) => {
      const b = [...c.buttons];
      b[i] = { ...b[i], ...patch };
      return { ...c, buttons: b };
    });
  };

  const addButton = () => {
    setCfg((c) => ({
      ...c,
      buttons: [...c.buttons, { id: `tombol-${Date.now()}`, label: "Tombol baru", url: "", style: "outline", visible: true }],
    }));
  };

  const removeButton = (i) => {
    setCfg((c) => ({ ...c, buttons: c.buttons.filter((_, x) => x !== i) }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/v2/platform/promo-config", cfg);
      setCfg(r.data);
      toast.success("Konfigurasi tersimpan. Landing page langsung berubah.");
    } catch (e) {
      toast.error(`Gagal: ${formatApiErrorDetail(e.response?.data?.detail)}`);
    } finally {
      setSaving(false);
    }
  };

  if (!cfg) {
    return <div className="flex items-center justify-center py-20 text-slate-400"><LoaderCircle className="animate-spin" /> Memuat...</div>;
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">🎨 Konfigurasi Landing Page</h1>
          <p className="text-sm text-slate-400">idseconnect.my.id — semua perubahan langsung tampil di web.</p>
        </div>
        <div className="flex gap-2">
          <a href="/promo" target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800">
            <Eye size={16} /> Lihat Landing
          </a>
          <button onClick={save} disabled={saving}
            className="inline-flex items-center gap-2 rounded-xl bg-cyan-500 px-5 py-2.5 text-sm font-bold text-slate-950 hover:bg-cyan-400 disabled:opacity-50">
            {saving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
            {saving ? "Menyimpan..." : "Simpan"}
          </button>
        </div>
      </div>

      {/* Site + accent */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <h2 className="mb-4 font-semibold text-white">Identitas & Warna</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-xs text-slate-400">Nama situs
            <input value={cfg.site_name || ""} onChange={(e) => set({ site_name: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-400">Domain promo (misal idseconnect.my.id)
            <input value={cfg.promo_domain || ""} onChange={(e) => set({ promo_domain: e.target.value.trim().toLowerCase() })}
              placeholder="idseconnect.my.id" className={`${inputCls} mt-1 font-mono`} />
          </label>
          <label className="block text-xs text-slate-400">Nomor WhatsApp (format 628xx)
            <input value={cfg.whatsapp_number || ""} onChange={(e) => set({ whatsapp_number: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
        </div>
        <p className="mt-2 text-xs text-slate-500">Kalau domain promo diisi dan DNS-nya sudah diarahkan ke server, buka domain itu langsung tampil landing page.</p>
        <p className="mt-4 text-xs text-slate-400">Warna aksen</p>
        <div className="mt-2 flex gap-2">
          {ACCENTS.map((a) => (
            <button key={a} onClick={() => set({ accent: a })} title={a}
              className={`h-9 w-9 rounded-full ${ACCENT_DOT[a]} ${cfg.accent === a ? "ring-2 ring-white ring-offset-2 ring-offset-slate-900" : "opacity-50 hover:opacity-100"}`} />
          ))}
        </div>
      </section>

      {/* Hero */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-semibold text-white">Hero (bagian atas)</h2>
          <button onClick={() => setHero({ visible: cfg.hero?.visible === false })}
            className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-white">
            {cfg.hero?.visible === false ? <EyeOff size={14} /> : <Eye size={14} />}
            {cfg.hero?.visible === false ? "Disembunyikan" : "Tampil"}
          </button>
        </div>
        <div className="space-y-3">
          <label className="block text-xs text-slate-400">Badge
            <input value={cfg.hero?.badge || ""} onChange={(e) => setHero({ badge: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-400">Judul
            <input value={cfg.hero?.title || ""} onChange={(e) => setHero({ title: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-400">Judul aksen (warna)
            <input value={cfg.hero?.title_accent || ""} onChange={(e) => setHero({ title_accent: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-400">Sub-judul
            <textarea value={cfg.hero?.subtitle || ""} onChange={(e) => setHero({ subtitle: e.target.value })} rows={3} className={`${inputCls} mt-1`} />
          </label>
        </div>
      </section>

      {/* Buttons */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="font-semibold text-white">Tombol</h2>
          <button onClick={addButton} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700">
            <Plus size={14} /> Tambah tombol
          </button>
        </div>
        <p className="mb-4 text-xs text-slate-500">Urutkan dengan panah atas/bawah. Layout di web tetap sama, hanya urutannya berubah.</p>
        <div className="space-y-3">
          {(cfg.buttons || []).map((b, i) => (
            <div key={b.id} className={`rounded-xl border p-3 ${b.visible ? "border-slate-700 bg-slate-950" : "border-slate-800 bg-slate-950/50 opacity-60"}`}>
              <div className="flex items-center gap-2">
                <div className="flex flex-col">
                  <button onClick={() => moveButton(i, -1)} className="text-slate-500 hover:text-white"><ArrowUp size={14} /></button>
                  <button onClick={() => moveButton(i, 1)} className="text-slate-500 hover:text-white"><ArrowDown size={14} /></button>
                </div>
                <input value={b.label} onChange={(e) => editButton(i, { label: e.target.value })}
                  placeholder="Label tombol" className={`${inputCls} flex-1`} />
                <button onClick={() => editButton(i, { visible: !b.visible })} title="Tampil/sembunyi"
                  className="text-slate-400 hover:text-white">{b.visible ? <Eye size={16} /> : <EyeOff size={16} />}</button>
                <button onClick={() => removeButton(i)} title="Hapus" className="text-rose-400 hover:text-rose-300"><Trash2 size={16} /></button>
              </div>
              <div className="mt-2 flex gap-2">
                <input value={b.url} onChange={(e) => editButton(i, { url: e.target.value })}
                  placeholder="Link redirect, misal https://wa.me/628xx atau /daftar" className={`${inputCls} flex-1 font-mono text-xs`} />
                <select value={b.style} onChange={(e) => editButton(i, { style: e.target.value })} className={`${inputCls} w-32`}>
                  {STYLES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Highlights */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <h2 className="mb-4 font-semibold text-white">Highlight (centang di bawah tombol)</h2>
        <textarea value={(cfg.highlights || []).join("\n")} rows={3}
          onChange={(e) => set({ highlights: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })}
          placeholder="Satu per baris" className={inputCls} />
      </section>

      {/* Sections */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <h2 className="mb-4 font-semibold text-white">Bagian halaman</h2>
        <div className="space-y-2">
          {SECTIONS.map(([key, label]) => (
            <label key={key} className="flex cursor-pointer items-center justify-between rounded-lg bg-slate-950 px-4 py-3">
              <span className="text-sm text-slate-200">{label}</span>
              <input type="checkbox" checked={cfg.sections?.[key] !== false}
                onChange={(e) => setSection(key, e.target.checked)}
                className="h-4 w-4 accent-cyan-500" />
            </label>
          ))}
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <label className="block text-xs text-slate-400">Judul fitur
            <input value={cfg.features_title || ""} onChange={(e) => set({ features_title: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-400">Judul langkah
            <input value={cfg.steps_title || ""} onChange={(e) => set({ steps_title: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-400">Judul FAQ
            <input value={cfg.faq_title || ""} onChange={(e) => set({ faq_title: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
        </div>
      </section>

      {/* Final CTA */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <h2 className="mb-4 font-semibold text-white">CTA akhir</h2>
        <div className="space-y-3">
          <label className="block text-xs text-slate-400">Badge
            <input value={cfg.final_cta?.badge || ""} onChange={(e) => setCta({ badge: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-400">Judul
            <input value={cfg.final_cta?.title || ""} onChange={(e) => setCta({ title: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-400">Sub-judul
            <textarea value={cfg.final_cta?.subtitle || ""} onChange={(e) => setCta({ subtitle: e.target.value })} rows={2} className={`${inputCls} mt-1`} />
          </label>
          <label className="block text-xs text-slate-400">Label tombol
            <input value={cfg.final_cta?.button_label || ""} onChange={(e) => setCta({ button_label: e.target.value })} className={`${inputCls} mt-1`} />
          </label>
        </div>
      </section>

      <button onClick={save} disabled={saving}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-cyan-500 px-5 py-3 text-sm font-bold text-slate-950 hover:bg-cyan-400 disabled:opacity-50">
        {saving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
        {saving ? "Menyimpan..." : "Simpan semua perubahan"}
      </button>
    </div>
  );
}
