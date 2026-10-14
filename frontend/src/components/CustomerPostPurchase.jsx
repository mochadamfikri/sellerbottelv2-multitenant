import { useCallback, useEffect, useState } from "react";
import api, { fmtIDR, formatApiErrorDetail } from "../lib/api";

export function GatewayMethods({ apiPrefix, method, onChange, amount, onQuote }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let active = true;
    api.get(`${apiPrefix}/gateway/methods`, {params: amount > 0 ? {amount} : {}}).then(r => {
      if (active) { setData({ ...r.data, requestedAmount: amount }); if (r.data.methods?.length && ((r.data.launch_profile === "v1_kasera" && !method.startsWith("gateway:")) || method === "qris" || (method.startsWith("gateway:") && !r.data.methods.some(m => m.code === method)))) onChange(r.data.methods[0].code); }
    }).catch(() => { if (active) setData({ methods: [] }); });
    return () => { active = false; };
    // The initial method is selected once per store, never on every selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiPrefix, amount]);
  useEffect(() => {
    const selected = data?.methods?.find(m => m.code === method);
    onQuote?.({ launch_profile: data?.launch_profile, amount, method,
      ready: Boolean(selected && data.requestedAmount === amount),
      fee_quote: data?.requestedAmount === amount ? selected?.fee_quote : null });
  }, [data, method, amount, onQuote]);
  if (!data?.methods?.length) return null;
  return <fieldset className="mt-3 space-y-2"><legend className="font-semibold">Metode gateway {data.coverage === "MOCKED" ? "(simulasi)" : "(sandbox)"}</legend>{data.methods.map(m => <label key={m.code} className="flex items-center gap-2 rounded border p-3"><input type="radio" name="store-payment-method" checked={method === m.code} onChange={() => onChange(m.code)}/>{m.label}</label>)}</fieldset>;
}

export function ShippingOptions({ apiPrefix, items, address, enabled, onSelect }) {
  const [data, setData] = useState(null), [error, setError] = useState("");
  const [selected, setSelected] = useState("");
  useEffect(() => {
    let active = true;
    setSelected(""); setData(null); onSelect(null); setError("");
    if (!enabled) return undefined;
    const timer = setTimeout(() => {
      api.post(`${apiPrefix}/gateway/rates`, { items, shipping_address: address }).then(r => {
        if (active) { setData(r.data); if (r.data.mode === "pickup_only") onSelect({ _id: null, amount: 0, mode: "pickup_only" }); }
      }).catch(e => { if (active) setError(formatApiErrorDetail(e.response?.data?.detail)); });
    }, 250);
    return () => { active = false; clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiPrefix, items, address, enabled]);
  return <section className="mt-3 space-y-2" aria-label="Pilihan pengiriman">
    {error && <p role="alert">{error}</p>}
    {data?.mode === "pickup_only" && <p>Ambil sendiri (pickup) — ongkir Rp0.</p>}
    {data?.mode === "integrated_shipping" && <><h3 className="font-bold">Pilih layanan pengiriman (MOCKED)</h3>{data.rates.map(r => <label className="flex gap-2 rounded border p-3" key={r._id}><input type="radio" name="shipping-service" checked={selected === r._id} onChange={() => { setSelected(r._id); onSelect(r); }}/>{r.label} · {fmtIDR(r.amount)} · {r.eta}</label>)}</>}
  </section>;
}

export default function CustomerPostPurchase({ orderId, items = [], apiPrefix }) {
  const [payment, setPayment] = useState(null), [returns, setReturns] = useState([]);
  const [eligible, setEligible] = useState([]);
  const [selection, setSelection] = useState({}), [reason, setReason] = useState("");
  const [key, setKey] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [p, r, e] = await Promise.all([api.get(`${apiPrefix}/orders/${orderId}/payment`), api.get(`${apiPrefix}/orders/${orderId}/returns`), api.get(`${apiPrefix}/orders/${orderId}/return-eligibility`)]);
    setPayment(p.data); setReturns(r.data); setEligible(e.data);
  }, [orderId, apiPrefix]);
  useEffect(() => { load().catch(e => setError(formatApiErrorDetail(e.response?.data?.detail))); }, [load]);
  const physical = items.filter(i => i.fulfillment_type === "physical" && eligible.some(e => e.line_id === i.line_id)).map(i => ({...i, qty: eligible.find(e => e.line_id === i.line_id).quantity}));
  const request = async () => {
    const id = key || window.crypto?.randomUUID?.() || `${Date.now()}-return-request`;
    setKey(id); setBusy(true); setError("");
    try {
      await api.post(`${apiPrefix}/orders/${orderId}/returns`, { idempotency_key: id, item_lines: Object.entries(selection).filter(([,q]) => Number(q) > 0).map(([line_id, q]) => ({ line_id, quantity: Number(q) })), reason });
      await load(); setSelection({}); setReason(""); setKey("");
    } catch (e) { setError(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return <section className="mt-4 space-y-3 rounded border p-3">
    {error && <p role="alert">{error}</p>}
    {payment && <div><h3 className="font-bold">Status pembayaran</h3><p>{payment.method} · {fmtIDR(payment.amount)} · {payment.status}</p>{payment.expires_at && payment.status === "pending" && <p>Berlaku sampai {new Date(payment.expires_at).toLocaleString("id-ID")}</p>}<p>{payment.instructions?.label}</p>{payment.instructions?.checkout_url && <a className="underline" href={payment.instructions.checkout_url} rel="noreferrer" target="_blank">Buka pembayaran sandbox</a>}{payment.instructions?.instrument?.qr_string && <p className="break-all text-xs">QR payload sandbox: {payment.instructions.instrument.qr_string}</p>}<button className="rounded border px-3 py-1" onClick={() => load().catch(e => setError(formatApiErrorDetail(e.response?.data?.detail)))}>Perbarui status pembayaran</button></div>}
    {physical.length > 0 && <><h3 className="font-bold">Ajukan return barang yang sudah diterima</h3><p className="text-sm">Pilih item dan jumlah. Permintaan akan ditinjau toko sebelum diproses.</p>{physical.map(line => <label key={line.line_id} className="block">{line.name} ({line.sku})<input aria-label={`Jumlah return ${line.sku}`} className="ml-2 w-20 rounded border p-1" type="number" min="0" max={line.qty} value={selection[line.line_id] || ""} onChange={e => { setSelection({ ...selection, [line.line_id]: e.target.value }); setKey(""); }}/></label>)}<label className="block">Alasan return<textarea className="mt-1 w-full rounded border p-2" value={reason} onChange={e => { setReason(e.target.value); setKey(""); }} maxLength={500}/></label><button className="rounded bg-emerald-800 px-3 py-2 text-white disabled:opacity-40" disabled={busy || !reason.trim() || !Object.values(selection).some(q => Number(q) > 0)} onClick={request}>Ajukan return</button></>}
    {returns.map(r => <p role="status" key={r._id}>Return: {r.status} · {r.reason} · {r.resolution}</p>)}
  </section>;
}
