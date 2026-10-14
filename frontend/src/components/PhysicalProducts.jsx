import { useCallback, useEffect, useState } from "react";
import { useTenantApi } from "../lib/tenantApi";
import { formatApiErrorDetail, fmtIDR } from "../lib/api";

const productEmpty = {name:"", description:"", price_idr:0, catalog_name:"", has_variants:false, default_weight:0, default_length:0, default_width:0, default_height:0, active:true};
const variantEmpty = {sku:"", barcode:"", option_values:{}, price_override:null, weight:0, length:0, width:0, height:0, active:true};
const field = "block w-full rounded border border-slate-700 bg-slate-950 p-2 text-sm";
const button = "rounded bg-emerald-700 px-3 py-2 text-sm text-white disabled:opacity-50";

export default function PhysicalProducts({initialProduct=null}) {
  const api = useTenantApi();
  const [products,setProducts] = useState([]), [selected,setSelected] = useState(null), [form,setForm] = useState(productEmpty);
  const [variants,setVariants] = useState([]), [variant,setVariant] = useState(variantEmpty), [variantId,setVariantId] = useState(null);
  const [options,setOptions] = useState([]), [image,setImage] = useState(null), [ledger,setLedger] = useState([]);
  const [stockRef,setStockRef] = useState("");
  const [stock,setStock] = useState({variant_id:"", type:"RECEIVE", quantity:1, reason:""});
  const [shipping,setShipping] = useState(0), [error,setError] = useState(""), [busy,setBusy] = useState(false);
  const base = "/public/tenant/full/physical";
  const load = useCallback(async () => {
    const [{data},settings] = await Promise.all([api.get("/public/tenant/full/products"),api.get(`${base}/shipping`)]);
    setProducts(data.filter(p=>p.fulfillment_type === "physical")); setShipping(settings.data.manual_shipping_fee);
  },[api]);
  useEffect(()=>{load().catch(e=>setError(formatApiErrorDetail(e.response?.data?.detail)));},[load]);
  useEffect(()=>{
    if(!initialProduct)return;
    setSelected(initialProduct);setForm({...productEmpty,...initialProduct,...initialProduct.physical_profile});
    setImage(null);setVariant(variantEmpty);setVariantId(null);setOptions([]);setLedger([]);
    api.get(`${base}/products/${initialProduct._id}/variants`).then(r=>setVariants(r.data)).catch(e=>setError(formatApiErrorDetail(e.response?.data?.detail)));
  },[initialProduct,api]);
  const refresh = async id => {const {data}=await api.get(`${base}/products/${id}/variants`);setVariants(data);};
  const run = async task => {setBusy(true);setError("");try{await task();}catch(e){setError(formatApiErrorDetail(e.response?.data?.detail)||e.message);}finally{setBusy(false);}};
  const choose = p => {setSelected(p);setForm({...productEmpty,...p,...p.physical_profile});setImage(null);setVariant(variantEmpty);setVariantId(null);setOptions([]);setLedger([]);refresh(p._id).catch(e=>setError(e.message));};
  const save = () => run(async()=>{
    const body = Object.fromEntries(Object.keys(productEmpty).map(key=>[key,form[key]]));
    const {data} = selected ? await api.put(`${base}/products/${selected._id}`,body) : await api.post(`${base}/products`,body);
    if(image){const payload=new FormData();payload.append("image",image);await api.post(`${base}/products/${data._id}/image`,payload);setImage(null);}
    setSelected(data);await load();await refresh(data._id);
  });
  const saveVariant = () => run(async()=>{
    if (options.some(row=>!row.key.trim() || !row.value.trim()) || new Set(options.map(row=>row.key.trim())).size !== options.length) throw new Error("Nama dan nilai opsi wajib diisi, nama harus unik.");
    const body={...variant,option_values:Object.fromEntries(options.map(row=>[row.key,row.value]))};
    if(variantId) await api.put(`${base}/variants/${variantId}`,body);else await api.post(`${base}/products/${selected._id}/variants`,body);
    setVariant(variantEmpty);setVariantId(null);setOptions([]);await refresh(selected._id);await load();
  });
  const adjust = () => run(async()=>{
    const reference = stockRef || window.crypto.randomUUID(); setStockRef(reference);
    await api.post(`${base}/variants/${stock.variant_id}/stock`,{type:stock.type,quantity:Number(stock.quantity),reason:stock.reason,reference_id:reference});
    setStockRef("");await refresh(selected._id);const {data}=await api.get(`${base}/variants/${stock.variant_id}/stock-movements`);setLedger(data);
  });
  return <section className="space-y-4 rounded-xl border border-slate-800 p-4" aria-label="Produk fisik">
    <h2 className="text-lg font-bold">Produk fisik & stok</h2>{error&&<p role="alert" className="text-rose-400">{error}</p>}
    <div className="flex flex-wrap items-end gap-2"><label>Ongkir flat per pesanan (IDR)<input aria-label="Ongkir flat" className={field} type="number" min="0" value={shipping} onChange={e=>setShipping(Number(e.target.value))}/></label><button className={button} disabled={busy} onClick={()=>run(()=>api.put(`${base}/shipping`,{manual_shipping_fee:Number(shipping)}))}>Simpan ongkir</button></div>
    <div className="flex flex-wrap gap-2"><button className={button} onClick={()=>{setSelected(null);setForm(productEmpty);setVariants([]);setVariantId(null);setVariant(variantEmpty);}}>Tambah produk fisik</button>{products.map(p=><button key={p._id} className="rounded border border-slate-700 px-3 py-2" onClick={()=>choose(p)}>{p.name}{!p.active&&" (nonaktif)"}</button>)}</div>
    <div className="grid gap-3 sm:grid-cols-2">{["name","description","catalog_name"].map(key=><label key={key}>{({name:"Nama produk fisik",description:"Deskripsi",catalog_name:"Katalog"})[key]}<input className={field} value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}
      {["price_idr","default_weight","default_length","default_width","default_height"].map(key=><label key={key}>{({price_idr:"Harga IDR",default_weight:"Berat (gram)",default_length:"Panjang (cm)",default_width:"Lebar (cm)",default_height:"Tinggi (cm)"})[key]}<input className={field} type="number" min="0" value={form[key]} onChange={e=>setForm({...form,[key]:Number(e.target.value)})}/></label>)}
      <label><input type="checkbox" checked={form.has_variants} onChange={e=>setForm({...form,has_variants:e.target.checked})}/> Memiliki pilihan variant</label><label><input type="checkbox" checked={form.active} onChange={e=>setForm({...form,active:e.target.checked})}/> Produk aktif</label>
      <label>Foto utama<input className={field} type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>setImage(e.target.files[0])}/></label>
    </div><button className={button} disabled={busy||!form.name} onClick={save}>Simpan produk fisik</button>
    {selected&&<><h3 className="font-bold">Variant / SKU — {selected.name}</h3><p className="text-sm text-slate-400">Setiap produk memakai SKU. Produk tanpa pilihan menggunakan satu variant dengan opsi kosong.</p>
      <table className="w-full text-left text-sm"><thead><tr>{["SKU / variant","On hand","Reserved","Available","Harga","Aksi"].map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>{variants.map(v=><tr key={v._id}><td>{v.sku} · {v.label}{!v.active&&" (nonaktif)"}</td><td>{v.on_hand}</td><td>{v.reserved}</td><td>{v.available}</td><td>{v.price_override==null?"Harga produk":fmtIDR(v.price_override)}</td><td><button onClick={()=>{setVariant(Object.fromEntries(Object.keys(variantEmpty).map(k=>[k,v[k]])));setVariantId(v._id);setOptions(Object.entries(v.option_values).map(([key,value])=>({key,value})));}}>Edit / nonaktifkan</button> · <button onClick={()=>run(async()=>{setStock({...stock,variant_id:v._id});const {data}=await api.get(`${base}/variants/${v._id}/stock-movements`);setLedger(data);})}>Stok / ledger</button></td></tr>)}</tbody></table>
      <div className="grid gap-3 sm:grid-cols-2"><label>SKU<input className={field} value={variant.sku} disabled={!!variantId} onChange={e=>setVariant({...variant,sku:e.target.value})}/></label><label>Barcode<input className={field} value={variant.barcode} onChange={e=>setVariant({...variant,barcode:e.target.value})}/></label><fieldset className="space-y-2"><legend>Opsi variant</legend>{options.map((row,index)=><div className="flex gap-2" key={index}><input aria-label={`Nama opsi ${index+1}`} placeholder="Nama opsi" className={field} value={row.key} onChange={e=>setOptions(options.map((v,i)=>i===index?{...v,key:e.target.value}:v))}/><input aria-label={`Nilai opsi ${index+1}`} placeholder="Nilai pilihan" className={field} value={row.value} onChange={e=>setOptions(options.map((v,i)=>i===index?{...v,value:e.target.value}:v))}/><button onClick={()=>setOptions(options.filter((_,i)=>i!==index))}>Hapus</button></div>)}<button className={button} onClick={()=>setOptions([...options,{key:"",value:""}])}>Tambah opsi</button></fieldset><label>Harga khusus IDR (kosong = harga produk)<input className={field} type="number" min="0" value={variant.price_override??""} onChange={e=>setVariant({...variant,price_override:e.target.value===""?null:Number(e.target.value)})}/></label>{["weight","length","width","height"].map(k=><label key={k}>{({weight:"Berat (gram)",length:"Panjang (cm)",width:"Lebar (cm)",height:"Tinggi (cm)"})[k]}<input className={field} type="number" min="0" value={variant[k]} onChange={e=>setVariant({...variant,[k]:Number(e.target.value)})}/></label>)}<label><input type="checkbox" checked={variant.active} onChange={e=>setVariant({...variant,active:e.target.checked})}/> Variant aktif</label></div>
      <button className={button} disabled={busy||!variant.sku} onClick={saveVariant}>{variantId?"Simpan variant":"Tambah variant"}</button>{variantId&&<button className="ml-3" onClick={()=>{setVariantId(null);setVariant(variantEmpty);setOptions([]);}}>Batal edit</button>}
      <h3 className="font-bold">Pergerakan stok</h3><div className="flex flex-wrap gap-2"><select aria-label="Variant stok" className={field} value={stock.variant_id} onChange={e=>{setStockRef("");setStock({...stock,variant_id:e.target.value});}}><option value="">Pilih SKU</option>{variants.map(v=><option key={v._id} value={v._id}>{v.sku}</option>)}</select><select aria-label="Jenis pergerakan" className={field} value={stock.type} onChange={e=>{setStockRef("");setStock({...stock,type:e.target.value});}}><option value="RECEIVE">Terima stok</option><option value="ADJUSTMENT">Penyesuaian (+/-)</option><option value="DAMAGE">Kerusakan (kurangi)</option></select><input aria-label="Jumlah stok" className={field} type="number" value={stock.quantity} onChange={e=>{setStockRef("");setStock({...stock,quantity:e.target.value});}}/><input aria-label="Alasan stok" className={field} placeholder="Alasan" value={stock.reason} onChange={e=>{setStockRef("");setStock({...stock,reason:e.target.value});}}/><button className={button} disabled={busy||!stock.variant_id||!stock.reason} onClick={adjust}>Catat pergerakan</button></div>
      <ul className="space-y-1 text-sm">{ledger.map(event=><li key={event._id}>{event.type} · {event.quantity} · {event.reason||event.reference_id}</li>)}</ul>
    </>}
  </section>;
}
