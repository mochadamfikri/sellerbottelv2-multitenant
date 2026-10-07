import { useEffect, useState } from "react";
import { Download, LoaderCircle } from "lucide-react";
import api, { formatApiErrorDetail } from "../lib/api";

export default function OrderDelivery({ orderId, status }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setData(null); setError("");
    api.get(`/store/orders/${orderId}/delivery`).then(({ data }) => { if (active) setData(data); }).catch((e) => { if (active) setError(formatApiErrorDetail(e.response?.data?.detail) || "Detail akun belum dapat dimuat."); });
    return () => { active = false; };
  }, [orderId, status]);
  const download = async (suffix, filename) => {
    setBusy(true); setError("");
    try {
      const response = await api.get(`/store/orders/${orderId}/${suffix}`, { responseType: "blob" });
      const url = URL.createObjectURL(response.data); const a = document.createElement("a"); a.href = url; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (_) { setError("Unduhan belum tersedia. Muat ulang detail pesanan atau hubungi admin."); }
    finally { setBusy(false); }
  };
  return <section className="mt-5 border-t border-slate-200 pt-5"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Detail akun & pengiriman</h3>{["delivered", "completed"].includes(status) && <button disabled={busy || !data} onClick={() => download("download", `IDSE-${data?.invoice_id || orderId}.txt`)} className="inline-flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800 disabled:opacity-40"><Download size={15}/> Unduh TXT</button>}</div>
    {!data && !error && <p role="status" className="mt-3 flex items-center gap-2 text-sm text-slate-500"><LoaderCircle size={16} className="animate-spin"/> Memuat detail akun…</p>}
    {error && <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}
    {data?.message && <p className="mt-3 text-sm text-slate-500">{data.message}</p>}
    {data?.products?.map((product, index) => <div key={`${product.product_id}-${index}`} className="mt-4 rounded-xl border border-slate-200 p-3"><h4 className="text-sm font-bold">{product.name}</h4>{product.accounts.map((account, n) => <div key={n} className="mt-3 rounded-lg bg-slate-50 p-3"><p className="mb-2 text-xs font-semibold text-emerald-800">Akun {n+1}</p><dl className="space-y-2">{Object.entries(account).map(([key, value]) => <div key={key}><dt className="text-xs text-slate-500">{key}</dt><dd className="select-text whitespace-pre-wrap break-all font-mono text-sm text-slate-900">{value}</dd></div>)}</dl></div>)}{product.files.map((file) => <button key={file.id} disabled={busy} onClick={() => download(`files/${file.id}`, file.name)} className="mt-3 flex items-center gap-2 text-sm font-semibold text-emerald-800"><Download size={15}/>{file.name}</button>)}{product.message && <p className="mt-3 text-sm text-slate-500">{product.message}</p>}</div>)}
  </section>;
}
