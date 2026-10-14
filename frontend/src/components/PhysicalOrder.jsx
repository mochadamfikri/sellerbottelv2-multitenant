import { useCallback, useEffect, useState } from "react";
import api, {formatApiErrorDetail,fmtIDR} from "../lib/api";
import {useTenantApi} from "../lib/tenantApi";
const labels={pending:"Menunggu diproses",packing:"Dikemas",ready_to_ship:"Siap dikirim",shipped:"Dikirim",delivered:"Diterima",cancelled:"Dibatalkan",failed:"Perlu pemeriksaan"};
const next={pending:"packing",packing:"ready_to_ship",ready_to_ship:"shipped",shipped:"delivered"};

export function CustomerShipping({orderId,apiPrefix="/store"}) {
  const [data,setData]=useState(null),[error,setError]=useState("");
  useEffect(()=>{api.get(`${apiPrefix}/orders/${orderId}/shipping`).then(r=>setData(r.data)).catch(e=>setError(formatApiErrorDetail(e.response?.data?.detail)));},[orderId,apiPrefix]);
  if(error)return <p role="alert">{error}</p>;
  if(!data?.shipments?.length)return null;
  return <section className="mt-4 space-y-2 rounded border p-3"><h3 className="font-bold">Pengiriman barang</h3><p>Ongkir: {fmtIDR(data.shipping_fee)}</p>{data.shipping_address&&<p>{data.shipping_address.recipient_name} · {data.shipping_address.address_line_1}, {data.shipping_address.city}, {data.shipping_address.province} {data.shipping_address.postal_code}</p>}{data.shipments.map(s=><div key={s.fulfillment_id}><b>{labels[s.status]||s.status}</b>{s.tracking_number&&<p>{s.carrier_name} · Nomor resi: <span className="font-mono">{s.tracking_number}</span></p>}</div>)}</section>;
}

export function TenantPhysicalOrder({orderId,onChange}) {
  const tenantApi=useTenantApi();
  const [data,setData]=useState(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  const [shipping,setShipping]=useState({});
  const load=useCallback(async()=>{const r=await tenantApi.get(`/public/tenant/full/physical/orders/${orderId}`);setData(r.data);},[tenantApi,orderId]);
  useEffect(()=>{load().catch(e=>setError(formatApiErrorDetail(e.response?.data?.detail)));},[load]);
  const update=async(record,status)=>{setBusy(true);setError("");try{await tenantApi.post(`/public/tenant/full/physical/orders/${orderId}/fulfillments/${record._id}`,{status,...(shipping[record._id]||{})});await load();onChange?.();}catch(e){setError(formatApiErrorDetail(e.response?.data?.detail));}finally{setBusy(false);}};
  if(!data?.fulfillments?.length && !(data?.requires_shipping && data?.order_status === "delivery_failed"))return error?<p role="alert">{error}</p>:null;
  return <section className="space-y-3 border-t border-slate-700 pt-3"><h3 className="font-bold">Pengiriman fisik</h3>{data.order_status === "delivery_failed" && <button disabled={busy} className="rounded bg-amber-700 px-3 py-2" onClick={async()=>{setBusy(true);setError("");try{await tenantApi.post(`/public/tenant/full/physical/orders/${orderId}/recover`);await load();onChange?.();}catch(e){setError(formatApiErrorDetail(e.response?.data?.detail));}finally{setBusy(false);}}}>Pulihkan inisialisasi pesanan dibayar</button>}{error&&<p role="alert" className="text-rose-400">{error}</p>}
    <p>Ongkir {fmtIDR(data.shipping_fee)}</p>{data.shipping_address&&<address className="not-italic">{data.shipping_address.recipient_name} · {data.shipping_address.phone}<br/>{data.shipping_address.address_line_1} {data.shipping_address.address_line_2}<br/>{data.shipping_address.district}, {data.shipping_address.city}, {data.shipping_address.province}, {data.shipping_address.postal_code}<br/>{data.shipping_address.notes}</address>}
    {data.fulfillments.map(record=>{const line=data.items.find(item=>record.item_refs.includes(item.line_id));return <div className="space-y-2 rounded bg-slate-950 p-3" key={record._id}><b>{line?.name} × {line?.qty}</b><p>{line?.sku} · {line?.variant_label} · {labels[record.status]}</p>{record.shipment_snapshot?.tracking_number&&<p>{record.shipment_snapshot.carrier_name} · Resi {record.shipment_snapshot.tracking_number}</p>}{record.status==="ready_to_ship"&&data.shipping_mode!=="pickup_only"&&<div className="flex gap-2"><input aria-label={`Kurir ${line?.sku}`} placeholder="Nama kurir" className="min-w-0 rounded bg-slate-800 p-2" value={shipping[record._id]?.carrier_name||""} onChange={e=>setShipping({...shipping,[record._id]:{...shipping[record._id],carrier_name:e.target.value}})}/><input aria-label={`Resi ${line?.sku}`} placeholder="Nomor resi" className="min-w-0 rounded bg-slate-800 p-2" value={shipping[record._id]?.tracking_number||""} onChange={e=>setShipping({...shipping,[record._id]:{...shipping[record._id],tracking_number:e.target.value}})}/></div>}{next[record.status]&&<button className="rounded bg-emerald-700 px-3 py-2" disabled={busy} onClick={()=>update(record,record.status==="ready_to_ship"&&data.shipping_mode==="pickup_only"?"delivered":next[record.status])}>Tandai {record.status==="ready_to_ship"&&data.shipping_mode==="pickup_only"?"diambil":labels[next[record.status]].toLowerCase()}</button>}{["pending","packing","ready_to_ship"].includes(record.status)&&<button className="ml-3 text-rose-400" disabled={busy} onClick={()=>{if(window.confirm("Batalkan pengiriman dan kembalikan stok? Pengembalian dana ditangani terpisah oleh admin."))update(record,"cancelled");}}>Batalkan pengiriman</button>}</div>;})}
  </section>;
}
