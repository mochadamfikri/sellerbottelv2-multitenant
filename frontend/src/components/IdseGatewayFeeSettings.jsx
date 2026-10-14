import { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "../lib/api";

const path = "/v2/platform/payments/kasera/fee";
const inputClass = "mt-1 block w-full rounded border border-slate-600 bg-slate-950 p-2";
export default function IdseGatewayFeeSettings() {
  const [fee, setFee] = useState(""), [tiers, setTiers] = useState([]), [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const adopt = data => { setFee(String(data.platform_fee)); setTiers((data.tiers || []).map(t => ({ min_amount: String(t.min_amount), max_amount: t.max_amount == null ? "" : String(t.max_amount), fee: String(t.fee) }))); };
  useEffect(() => {
    let active = true;
    api.get(path).then(r => { if (active) { adopt(r.data); setLoaded(true); } })
      .catch(e => { if (active) setError(formatApiErrorDetail(e.response?.data?.detail) || "Pengaturan fee belum dapat dimuat."); });
    return () => { active = false; };
  }, []);
  const save = async event => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const result = await api.put(path, { platform_fee: Number(fee), tiers: tiers.map(t => ({ min_amount: Number(t.min_amount), max_amount: t.max_amount === "" ? null : Number(t.max_amount), fee: Number(t.fee) })) });
      adopt(result.data); setNotice("Fee tersimpan. Berlaku untuk checkout baru.");
    } catch (e) { setError(formatApiErrorDetail(e.response?.data?.detail) || "Fee belum tersimpan."); }
    finally { setBusy(false); }
  };
  const updateTier = (index, field, value) => setTiers(current => current.map((t, i) => i === index ? { ...t, [field]: value } : t));
  return <section className="rounded-xl border border-slate-800 bg-slate-900 p-5 text-slate-200">
    <h2 className="font-semibold">Fee gateway IDSE</h2>
    <p className="mt-2 text-sm">Dipotong dari penerimaan tenant pengguna Settlement IDSE. Gateway milik tenant sendiri tidak dikenai fee SellerBottel. Pembeli menanggung biaya Kasera.</p>
    <form onSubmit={save} className="mt-3 space-y-3">
      <label className="block max-w-xs text-sm">Fee default / di luar rentang (Rupiah)<input className={inputClass} type="number" min="0" max="1000000" step="1" required value={fee} disabled={!loaded || busy} onChange={e => setFee(e.target.value)}/></label>
      <p className="text-sm">Rentang memakai nilai produk setelah diskon + ongkir, sebelum biaya Kasera. Batas awal dan akhir termasuk dalam rentang. Kosongkan batas akhir untuk tanpa batas.</p>
      {tiers.map((tier, index) => <div key={index} className="grid gap-2 rounded border border-slate-700 p-3 sm:grid-cols-4">
        <label>Mulai (Rp)<input aria-label={`Mulai rentang ${index + 1}`} className={inputClass} type="number" min="1" max="1000000000000" step="1" required value={tier.min_amount} disabled={busy} onChange={e => updateTier(index, "min_amount", e.target.value)}/></label>
        <label>Sampai (Rp)<input aria-label={`Akhir rentang ${index + 1}`} className={inputClass} type="number" min="1" max="1000000000000" step="1" value={tier.max_amount} disabled={busy} onChange={e => updateTier(index, "max_amount", e.target.value)}/></label>
        <label>Potongan (Rp)<input aria-label={`Fee rentang ${index + 1}`} className={inputClass} type="number" min="0" max="1000000" step="1" required value={tier.fee} disabled={busy} onChange={e => updateTier(index, "fee", e.target.value)}/></label>
        <button type="button" disabled={busy} onClick={() => setTiers(tiers.filter((_, i) => i !== index))}>Hapus rentang {index + 1}</button>
      </div>)}
      <div className="flex flex-wrap gap-3"><button type="button" className="rounded border px-3 py-2" disabled={!loaded || busy || tiers.length >= 20} onClick={() => setTiers([...tiers, { min_amount: "", max_amount: "", fee: "250" }])}>Tambah rentang</button>
      <button className="rounded bg-emerald-700 px-4 py-2 disabled:opacity-40" disabled={!loaded || busy}>Simpan fee</button></div>
    </form>
    <p className="mt-2 text-xs">Default awal Rp250. Rentang tidak boleh tumpang tindih. Perubahan hanya berlaku pada checkout baru; fee transaksi yang sudah dibuat tetap sama.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
  </section>;
}
