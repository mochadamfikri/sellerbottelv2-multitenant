import { useCallback, useEffect, useState } from "react";
import { useTenantApi } from "../lib/tenantApi";
import { formatApiErrorDetail, fmtIDR } from "../lib/api";

const base = "/public/tenant/full/commerce";
const inputClass = "mt-1 w-full rounded border border-slate-600 bg-slate-900 p-2 text-white";
const buttonClass = "rounded bg-emerald-700 px-3 py-2 text-white disabled:opacity-40";
const addressFields = [["recipient_name", "Nama penerima origin"], ["phone", "Telepon origin"], ["address_line_1", "Alamat origin"], ["city", "Kota / Kabupaten origin"], ["province", "Provinsi origin"], ["postal_code", "Kode pos origin"]];
function Field({ label, value, onChange, type = "text" }) {
  return <label className="block text-sm">{label}<input className={inputClass} type={type} value={value ?? ""} onChange={e => onChange(e.target.value)} /></label>;
}
const newKey = () => window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;

export default function CommerceAdmin({ section = "payments" }) {
  const api = useTenantApi();
  const [settings, setSettings] = useState(null), [fields, setFields] = useState({});
  const [transactions, setTransactions] = useState([]), [settlement, setSettlement] = useState(null);
  const [shipping, setShipping] = useState({ mode: "manual_shipping", manual_shipping_fee: 0, origin: { country: "ID" }, provider: "mock_courier" });
  const [shippingFields, setShippingFields] = useState({}), [shipments, setShipments] = useState([]);
  const [returns, setReturns] = useState([]), [refunds, setRefunds] = useState([]), [review, setReview] = useState(null);
  const [bank, setBank] = useState({}), [savedBank, setSavedBank] = useState(null);
  const [payout, setPayout] = useState({ amount: "", idempotency_key: newKey() });
  const [refund, setRefund] = useState({ amount: "", idempotency_key: newKey(), return_id: "" });
  const [orderId, setOrderId] = useState(""), [physical, setPhysical] = useState(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [loadedSection, setLoadedSection] = useState(null);

  const load = useCallback(async () => {
    if (section === "payments") {
      const [s, t, l, b, r, q] = await Promise.all([api.get(base + "/payment-settings"), api.get(base + "/transactions"), api.get(base + "/settlement"), api.get(base + "/payout-bank"), api.get(base + "/refunds"), api.get(base + "/reconciliation")]);
      setSettings(s.data); setTransactions(t.data); setSettlement(l.data); setSavedBank(b.data); setRefunds(r.data); setReview(q.data);
    } else if (section === "shipping") {
      const [s, list] = await Promise.all([api.get(base + "/shipping-settings"), api.get(base + "/shipments")]);
      setShipping(prev => ({ ...prev, ...s.data, origin: s.data.origin || { country: "ID" } })); setShipments(list.data);
    } else {
      const [r, p, f] = await Promise.all([api.get(base + "/returns"), api.get(base + "/transactions"), api.get(base + "/refunds")]);
      setReturns(r.data); setTransactions(p.data); setRefunds(f.data);
    }
    setLoadedSection(section);
  }, [api, section]);
  useEffect(() => { load().catch(e => setError(formatApiErrorDetail(e.response?.data?.detail))); }, [load]);
  const act = async (fn, message) => {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); await load(); setNotice(message); }
    catch (e) { setError(formatApiErrorDetail(e.response?.data?.detail) || "Permintaan gagal; periksa rekonsiliasi sebelum mengulangi."); }
    finally { setBusy(false); }
  };
  const savePayment = () => act(async () => {
    await api.put(base + "/payment-settings", { payment_mode: settings.payment_mode, provider: settings.payment_mode === "platform_settlement" ? "kasera" : settings.provider, environment: settings.environment, clearing_delay_seconds: Number(settings.clearing_delay_seconds || 0), available_delay_seconds: Number(settings.available_delay_seconds || 0), ...(settings.payment_mode === "self_gateway" && Object.values(fields).some(Boolean) ? { credentials: Object.fromEntries(Object.entries(fields).filter(([,v]) => v)) } : {}) });
    setFields({});
  }, "Pengaturan pembayaran tersimpan.");
  const requestRefund = payment => act(async () => {
    await api.post(`${base}/transactions/${payment._id}/refunds`, { ...refund, amount: Number(refund.amount), return_id: refund.return_id || null });
    setRefund({ amount: "", idempotency_key: newKey(), return_id: "" });
  }, "Permintaan refund dicatat. Periksa status hasilnya.");

  if (loadedSection !== section) return <section className="mt-4 text-slate-200"><p role="status">Memuat pengaturan…</p>{error && <><p role="alert">{error}</p><button className={buttonClass} onClick={() => load().catch(e => setError(formatApiErrorDetail(e.response?.data?.detail)))}>Muat ulang</button></>}</section>;
  return <section className="mt-4 space-y-5 text-slate-200">
    {error && <p role="alert" className="rounded bg-rose-950 p-3">{error}</p>}
    {notice && <p role="status" className="rounded bg-emerald-950 p-3">{notice}</p>}
    {section === "payments" && settings && <>
      <h2 className="text-xl font-bold">Payments — Pengaturan pembayaran</h2>
      <p className="text-sm">Environment {settings.environment}; {settings.capabilities?.coverage || "Belum diverifikasi"}. Mode mock adalah simulasi tanpa perpindahan uang.</p>
      <label className="block">Mode pembayaran<select className={inputClass} value={settings.payment_mode} onChange={e => { setSettings({ ...settings, payment_mode: e.target.value, provider: "kasera" }); setFields({}); }}><option value="platform_settlement">Settlement IDSE</option><option value="self_gateway">Gateway Saya Sendiri</option></select></label>
      {settings.payment_mode === "self_gateway" && <>
        <label className="block">Provider<select className={inputClass} value={settings.provider} onChange={e => { setSettings({ ...settings, provider: e.target.value }); setFields({}); }}><option value="kasera">Kasera</option><option value="midtrans">Midtrans</option></select></label>
        <label className="block">Environment<select className={inputClass} value={settings.environment} onChange={e => { setSettings({ ...settings, environment: e.target.value }); setFields({}); }}><option value="mock">Mock (simulasi)</option><option value="sandbox">Sandbox (perlu konfigurasi server)</option></select></label>
        {(settings.credential_schemas?.[settings.provider] || []).map(key => <Field key={key} label={key} type="password" value={fields[key]} onChange={value => setFields({ ...fields, [key]: value })}/>)}
        {Object.keys(settings.masked_fields || {}).length > 0 && <p>Kredensial tersimpan: {Object.keys(settings.masked_fields).join(", ")} ••••</p>}
      </>}
      <div className="flex flex-wrap gap-2"><button disabled={busy} className={buttonClass} onClick={savePayment}>Simpan pembayaran</button><button disabled={busy} className={buttonClass} onClick={() => act(() => api.post(base + "/payment-settings/test"), "Test Connection selesai; lihat capability snapshot.")}>Test Connection</button>{settings.payment_mode === "self_gateway" && <button disabled={busy} className={buttonClass} onClick={() => act(() => api.post(base + "/payment-settings/revoke"), "Kredensial dicabut untuk pembayaran baru.")}>Cabut kredensial</button>}</div>
      {settings.capabilities && <div className="rounded border border-slate-700 p-3"><h3 className="font-bold">Capabilities</h3><p>Metode: {settings.capabilities.supported_methods?.join(", ")}</p><p>Refund: {settings.capabilities.refund_support ? "API tersedia" : "Manual diperlukan"} · Cancel: {settings.capabilities.cancel_support ? "tersedia" : "tidak tersedia"} · Payout API: {settings.capabilities.payout_support ? "tersedia" : "tidak tersedia"}</p><p>Terakhir diverifikasi: {settings.capabilities.last_verified_at}</p><p>Webhook: {settings.webhook_url}</p></div>}
      <h3 className="font-bold">Transactions</h3><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Order</th><th>Provider / Metode</th><th>Jumlah</th><th>Status</th><th>Waktu</th></tr></thead><tbody>{transactions.map(p => <tr key={p._id} className="border-t border-slate-700"><td>{p.order_id}</td><td>{p.provider} / {p.method}</td><td>{fmtIDR(p.amount)}</td><td>{p.status}{p.reconciliation && <p className="text-amber-400">{p.reconciliation}</p>}</td><td>{p.created_at}</td></tr>)}</tbody></table></div>
      {settings.payment_mode === "platform_settlement" && <>
        <h3 className="font-bold">Settlement</h3><div className="grid grid-cols-3 gap-2">{Object.entries(settlement?.balances || {}).map(([key, value]) => <div className="rounded bg-slate-900 p-3" key={key}>{key}<b className="block">{fmtIDR(value)}</b></div>)}</div>
        {transactions.filter(p => p.payment_mode === "platform_settlement" && ["paid", "partially_refunded"].includes(p.status)).map(p => <div key={p._id} className="flex flex-wrap items-center gap-2"><span>{p.order_id.slice(0, 12)}</span>{["clearing", "available"].map(stage => <button disabled={busy} className={buttonClass} key={stage} onClick={() => act(() => api.post(`${base}/settlement/${p._id}/advance`, { stage }), `Settlement ${stage} dicatat.`)}>{stage}</button>)}</div>)}
        <h3 className="font-bold">Payout — hanya simulasi</h3><p>{savedBank?.bank_name} {savedBank?.account_number_masked} {savedBank?.verification_status}</p>
        {["bank_name", "account_number", "account_holder"].map(k => <Field key={k} label={k} value={bank[k]} onChange={value => setBank({ ...bank, [k]: value })}/>)}
        <button className={buttonClass} disabled={busy} onClick={() => act(async () => { await api.put(base + "/payout-bank", bank); setBank({}); }, "Rekening simulasi tersimpan dan dimasking.")}>Simpan rekening simulasi</button>
        <Field label="Jumlah payout" type="number" value={payout.amount} onChange={value => setPayout({ amount: value, idempotency_key: newKey() })}/>
        <button className={buttonClass} disabled={busy || !payout.amount} onClick={() => act(async () => { await api.post(base + "/payouts", { ...payout, amount: Number(payout.amount) }); setPayout({ amount: "", idempotency_key: newKey() }); }, "Dana payout dicadangkan; belum dikirim ke bank.")}>Ajukan payout simulasi</button>
        {Object.values((settlement?.entries || []).filter(e => e.payout_id).reduce((result, e) => ({ ...result, [e.payout_id]: e }), {})).map(e => <div className="flex gap-2" key={e.payout_id}><span>{e.payout_id} — {e.state} {fmtIDR(e.amount)}</span>{({ requested: ["reviewing", "cancelled"], reviewing: ["processing", "rejected"], processing: ["paid", "failed"] }[e.state] || []).map(status => <button className={buttonClass} disabled={busy} key={status} onClick={() => act(() => api.post(`${base}/payouts/${e.payout_id}/simulate`, { status }), `Simulasi payout ${status}.`)}>Simulasi {status}</button>)}</div>)}
      </>}
      <h3 className="font-bold">Rekonsiliasi</h3><p>{review?.payments?.length || 0} payment perlu diperiksa; {review?.refunds?.length || 0} refund; {review?.events?.length || 0} event.</p><button className={buttonClass} disabled={busy} onClick={() => act(() => api.post(base + "/reconciliation/repair"), "Proyeksi dan receipt terpercaya dipulihkan. Aksi eksternal ambigu tetap perlu diperiksa.")}>Pulihkan receipt / proyeksi</button>
    </>}
    {section === "shipping" && <>
      <h2 className="text-xl font-bold">Shipping — Pengaturan / Providers / Shipments</h2>
      <label className="block">Mode pengiriman<select className={inputClass} value={shipping.mode} onChange={e => setShipping({ ...shipping, mode: e.target.value })}><option value="manual_shipping">Manual shipping</option><option value="integrated_shipping">Integrated shipping — Mock Courier</option><option value="pickup_only">Pickup / ambil sendiri</option></select></label>
      <Field label="Ongkir manual" type="number" value={shipping.manual_shipping_fee} onChange={value => setShipping({ ...shipping, manual_shipping_fee: value })}/>
      {shipping.mode !== "manual_shipping" && addressFields.map(([key, label]) => <Field key={key} label={label} value={shipping.origin?.[key]} onChange={value => setShipping({ ...shipping, origin: { ...shipping.origin, [key]: value } })}/>)}
      {shipping.mode === "integrated_shipping" && <><p>Provider Mock Courier (MOCKED). Kredensial mock harus diawali mock_.</p>{["api_key", "webhook_secret"].map(key => <Field key={key} label={`Shipping ${key}`} type="password" value={shippingFields[key]} onChange={value => setShippingFields({ ...shippingFields, [key]: value })}/>)}</>}
      <button className={buttonClass} disabled={busy} onClick={() => act(async () => { await api.put(base + "/shipping-settings", { mode: shipping.mode, provider: shipping.provider, manual_shipping_fee: Number(shipping.manual_shipping_fee), origin: shipping.origin, ...(Object.values(shippingFields).some(Boolean) ? { credentials: shippingFields } : {}) }); setShippingFields({}); }, "Pengaturan shipping tersimpan.")}>Simpan shipping</button>
      <Field label="Order untuk shipment" value={orderId} onChange={setOrderId}/><button className={buttonClass} disabled={busy || !orderId} onClick={() => act(async () => { const result = await api.get(`/public/tenant/full/physical/orders/${orderId}`); setPhysical(result.data); }, "Detail physical fulfillment dimuat.")}>Muat order shipment</button>
      {physical?.fulfillments.map(f => <div className="rounded border p-3" key={f._id}><p>{f.line_id} — {f.status}</p>{["pending", "packing"].includes(f.status) && <button className={buttonClass} disabled={busy} onClick={() => act(async () => { await api.post(`/public/tenant/full/physical/orders/${orderId}/fulfillments/${f._id}`, { status: f.status === "pending" ? "packing" : "ready_to_ship" }); setPhysical((await api.get(`/public/tenant/full/physical/orders/${orderId}`)).data); }, "Fulfillment diperbarui.")}>{f.status === "pending" ? "Packing" : "Ready to ship"}</button>}{f.status === "ready_to_ship" && <button className={buttonClass} disabled={busy} onClick={() => act(async () => { await api.post(`${base}/shipments/${orderId}/${f._id}`); setPhysical((await api.get(`/public/tenant/full/physical/orders/${orderId}`)).data); }, "Shipment dibuat (MOCKED).")} >Buat shipment</button>}</div>)}
      {shipments.map(s => <div className="rounded border border-slate-700 p-3" key={s._id}><p>{s.order_id} · {s.status} · {s.quote?.coverage}</p><p>{s.carrier_name} · Resi {s.tracking_number}</p></div>)}
    </>}
    {section === "returns" && <>
      <h2 className="text-xl font-bold">Returns dan Refunds</h2>
      {returns.length === 0 && <p>Belum ada permintaan return.</p>}
      {returns.map(r => <div className="space-y-2 rounded border border-slate-700 p-3" key={r._id}><b>{r.order_id}</b><p>{r.reason} · {r.status} · {r.resolution}</p><p>{r.item_lines.map(l => `${l.line_id.slice(0, 12)} × ${l.quantity}`).join(", ")}</p><div className="flex flex-wrap gap-2">{({ return_requested: ["reviewing"], reviewing: ["approved", "rejected"], approved: ["received"], return_shipped: ["received"], received: ["inspected"], inspected: ["resolved"] }[r.status] || []).map(status => status === "inspected" ? ["restock", "damaged"].map(resolution => <button className={buttonClass} disabled={busy} key={resolution} onClick={() => act(() => api.post(`${base}/returns/${r._id}`, { status, resolution }), `Inspeksi ${resolution} dicatat.`)}>Inspect {resolution}</button>) : <button className={buttonClass} disabled={busy} key={status} onClick={() => act(() => api.post(`${base}/returns/${r._id}`, { status }), `Return ${status}.`)}>{status}</button>)}</div><details><summary>Riwayat return</summary>{r.history?.map((h, i) => <p key={i}>{h.at} — {h.status} {h.resolution}</p>)}</details></div>)}
      <Field label="Jumlah refund (Rupiah)" type="number" value={refund.amount} onChange={value => setRefund({ ...refund, amount: value, idempotency_key: newKey() })}/>
      <Field label="Return ID (opsional, harus sudah inspected)" value={refund.return_id} onChange={value => setRefund({ ...refund, return_id: value, idempotency_key: newKey() })}/>
      {transactions.filter(p => ["paid", "partially_refunded"].includes(p.status)).map(p => <div key={p._id} className="flex flex-wrap items-center gap-3"><span>{p.order_id} — Dibayar {fmtIDR(p.amount)}, refund {fmtIDR(p.refunded_amount)}</span><button className={buttonClass} disabled={busy || !refund.amount} onClick={() => requestRefund(p)}>Ajukan refund {p.order_id.slice(0, 8)}</button></div>)}
      <h3 className="font-bold">Status refund</h3>{refunds.map(r => <p key={r._id}>{r.order_id} — {fmtIDR(r.amount)} — {r.status}</p>)}
    </>}
  </section>;
}
