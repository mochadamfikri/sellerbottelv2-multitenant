import { useEffect } from "react";
import { Link, useLocation, Navigate } from "react-router-dom";
import { CheckCircle2, Store, Settings, ArrowRight, Copy, Download, Check } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

export default function RegisterSuccess() {
  const { state } = useLocation();
  const [copied, setCopied] = useState(null);
  // Bersihkan form tersimpan karena pendaftaran sudah selesai
  useEffect(() => {
    try { sessionStorage.removeItem("register_form"); } catch {}
  }, []);
  if (!state?.tenant_slug) return <Navigate to="/daftar" replace />;

  const shopUrl = state.shop_url || "";
  const shopDomain = shopUrl.replace("https://", "").replace("http://", "").replace(/\/$/, "");
  const panelUrl = shopDomain ? `https://${shopDomain}/admin` : "";
  const panelDomain = shopDomain ? `${shopDomain}/admin` : "";

  const copyText = async (text, id) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      toast.success("Disalin!");
      setTimeout(() => setCopied(null), 1500);
    } catch {
      toast.error("Gagal salin.");
    }
  };

  const copyAll = () => {
    const all = `Web Shop (public): ${shopUrl}\nPanel stock (owner): ${panelUrl}`;
    copyText(all, "all");
  };

  const downloadInfo = () => {
    const content = `=== INFO TOKO ===
Nama Toko: ${state.store_name || ""}
Slug: ${state.tenant_slug || ""}

Web Shop (public): ${shopUrl}
Panel stock (owner): ${panelUrl}

Simpan info ini baik-baik ya!
`;
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `info-toko-${state.tenant_slug || "toko"}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Info didownload!");
  };

  return (
    <div className="grid min-h-screen place-items-center bg-slate-950 px-4 py-8">
      <div className="w-full max-w-md rounded-3xl border border-white/10 bg-slate-900 p-8 text-center shadow-2xl">
        <CheckCircle2 size={56} className="mx-auto text-emerald-400" />
        <h1 className="mt-4 text-2xl font-extrabold text-white">Toko Berhasil Dibuat!</h1>
        <p className="mt-2 text-sm text-slate-400">
          Selamat datang, <span className="font-semibold text-slate-200">{state.store_name}</span>.
          Toko online kamu sudah aktif:
        </p>

        {/* Web Shop */}
        <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-left">
          <p className="text-xs font-semibold text-slate-400">Web Shop (public)</p>
          <div className="mt-1.5 flex items-center gap-2">
            <a
              href={shopUrl}
              target="_blank"
              rel="noreferrer"
              className="flex flex-1 items-center gap-2 break-all font-mono text-sm font-semibold text-emerald-300 hover:underline"
            >
              <Store size={16} className="shrink-0" /> {shopDomain}
            </a>
            <button
              onClick={() => copyText(shopUrl, "shop")}
              className="shrink-0 rounded-xl border border-white/15 p-2 text-slate-300 hover:bg-white/10"
              title="Salin link"
            >
              {copied === "shop" ? <Check size={16} className="text-emerald-400" /> : <Copy size={16} />}
            </button>
          </div>
        </div>

        {/* Panel Stock */}
        <div className="mt-3 rounded-2xl border border-white/10 bg-white/5 p-4 text-left">
          <p className="text-xs font-semibold text-slate-400">Panel stock (owner)</p>
          <div className="mt-1.5 flex items-center gap-2">
            <a
              href={panelUrl}
              target="_blank"
              rel="noreferrer"
              className="flex flex-1 items-center gap-2 break-all font-mono text-sm font-semibold text-amber-300 hover:underline"
            >
              <Settings size={16} className="shrink-0" /> {panelDomain}
            </a>
            <button
              onClick={() => copyText(panelUrl, "panel")}
              className="shrink-0 rounded-xl border border-white/15 p-2 text-slate-300 hover:bg-white/10"
              title="Salin link"
            >
              {copied === "panel" ? <Check size={16} className="text-emerald-400" /> : <Copy size={16} />}
            </button>
          </div>
        </div>

        {/* Download + Copy All */}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <button
            onClick={downloadInfo}
            className="flex items-center justify-center gap-1.5 rounded-2xl border border-white/15 bg-white/5 py-3 text-sm font-bold text-slate-300 hover:bg-white/10"
          >
            <Download size={16} /> Download info
          </button>
          <button
            onClick={copyAll}
            className="flex items-center justify-center gap-1.5 rounded-2xl bg-emerald-500 py-3 text-sm font-bold text-slate-950 hover:bg-emerald-400"
          >
            {copied === "all" ? <Check size={16} /> : <Copy size={16} />} Copy all
          </button>
        </div>

        <Link
          to="/promo"
          className="mt-6 inline-flex items-center gap-2 rounded-xl bg-white/5 px-6 py-3 text-sm font-bold text-slate-300 hover:bg-white/10"
        >
          Kembali ke Beranda <ArrowRight size={16} />
        </Link>
      </div>
    </div>
  );
}
