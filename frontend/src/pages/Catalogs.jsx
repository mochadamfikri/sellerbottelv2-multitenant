import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";
import { catalogHref } from "../lib/catalog";

const input = "w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100";
const button = "rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40";

export default function Catalogs() {
  const [catalogs, setCatalogs] = useState([]);
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");
  const [checked, setChecked] = useState([]);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const load = async () => {
    const { data } = await api.get("/admin/catalogs");
    setCatalogs(data); setLoaded(true); setError("");
  };
  useEffect(() => { load().catch((e) => setError(formatApiErrorDetail(e.response?.data?.detail) || "Katalog gagal dimuat.")); }, []);
  const run = async (operation, message, next = selected) => {
    setBusy(true);
    try { await operation(); await load(); setSelected(next); setChecked([]); toast.success(message); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Perubahan katalog gagal."); }
    finally { setBusy(false); }
  };
  const current = catalogs.find((c) => c.name === selected);
  const products = (current ? current.products : catalogs.flatMap((c) => c.products.map((p) => ({ ...p, catalog: c.name })))).filter((p) => `${p.name} ${p.catalog || ""}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="space-y-5">
    <p className="text-sm text-slate-400">Katalog mengelompokkan varian produk. Harga, stok, inventory, dan pesanan tetap dikelola per produk.</p>
    {error && <p role="alert" className="text-rose-400">{error}</p>}
    {!loaded && !error && <p role="status">Memuat katalog…</p>}
    <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); run(() => api.post("/admin/catalogs", { name: name.trim() }), "Katalog dibuat.", name.trim()); }}>
      <input aria-label="Nama katalog baru" className={`${input} sm:max-w-sm`} maxLength={80} placeholder="Nama katalog baru, contoh Claude Pro" value={name} required onChange={(e) => setName(e.target.value)}/><button className={button} disabled={busy || !name.trim()}>Buat katalog</button>
    </form>
    <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
      <aside className="max-h-[65vh] space-y-2 overflow-y-auto rounded-xl border border-slate-800 bg-slate-900 p-3">
        <button className={`${input} text-left ${!selected ? "border-cyan-500" : ""}`} onClick={() => { setSelected(""); setChecked([]); }}>Semua produk</button>
        {catalogs.map((c) => <button key={c.name} className={`${input} flex items-center justify-between gap-2 text-left ${selected === c.name ? "border-cyan-500 text-cyan-300" : ""}`} onClick={() => { setSelected(c.name); setChecked([]); setSearch(""); }}><span>{c.name}</span><span className="text-xs text-slate-400">{c.products.length}</span></button>)}
      </aside>
      <section className="min-w-0 space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-semibold">{current?.name || "Semua produk"}</h2><p className="mt-1 text-xs text-slate-400">{current ? `${current.products.filter((p) => p.active).length} produk aktif · katalog kosong tidak ditampilkan di toko` : "Pilih produk untuk memindahkan beberapa varian sekaligus."}</p></div>{current && <Link className="text-sm text-cyan-400" to={catalogHref(current.name)}>Lihat di toko →</Link>}</div>
        {current && current.name !== "Produk Lainnya" && <div className="flex flex-wrap gap-2"><button disabled={busy} className="text-sm text-cyan-400" onClick={() => { const next = window.prompt("Nama katalog baru", current.name); if (next?.trim() && next.trim() !== current.name) run(() => api.put("/admin/catalogs/rename", { old_name: current.name, name: next.trim() }), "Nama katalog diperbarui.", next.trim()); }}>Ubah nama</button><button disabled={busy} className="text-sm text-rose-400" onClick={() => { if (window.confirm(`Hapus katalog ${current.name}? ${current.products.length} produk akan dipindahkan ke Produk Lainnya. Produk dan inventory tidak dihapus.`)) run(() => api.delete("/admin/catalogs", { params: { name: current.name } }), "Katalog dihapus; produk tetap tersedia.", ""); }}>Hapus katalog</button></div>}
        <input aria-label="Cari produk dalam pengelolaan katalog" className={input} placeholder="Cari produk" value={search} onChange={(e) => setSearch(e.target.value)}/>
        <div className="flex flex-wrap items-center gap-2"><input aria-label="Katalog tujuan" className={`${input} sm:max-w-xs`} list="catalog-targets" maxLength={80} placeholder="Pilih atau ketik katalog tujuan" value={target} onChange={(e) => setTarget(e.target.value)}/><datalist id="catalog-targets">{catalogs.map((c) => <option key={c.name} value={c.name}/>)}</datalist><button className={button} disabled={busy || !checked.length || !target.trim()} onClick={() => run(() => api.put("/admin/catalogs/assign", { name: target.trim(), product_ids: checked }), "Produk dipindahkan ke katalog.")}>Pindahkan {checked.length} produk</button></div>
        <label className="flex gap-2 text-sm text-slate-400"><input type="checkbox" checked={products.length > 0 && products.every((p) => checked.includes(p._id))} onChange={(e) => setChecked(e.target.checked ? [...new Set([...checked, ...products.map((p) => p._id)])] : checked.filter((id) => !products.some((p) => p._id === id)))}/> Pilih semua hasil ({products.length})</label>
        <div className="max-h-[55vh] divide-y divide-slate-800 overflow-y-auto">{products.map((p) => <label key={p._id} className="flex cursor-pointer items-start gap-3 py-3"><input type="checkbox" className="mt-1" checked={checked.includes(p._id)} onChange={(e) => setChecked(e.target.checked ? [...checked, p._id] : checked.filter((id) => id !== p._id))}/><span className="text-sm"><span className="block">{p.name}</span><span className="text-xs text-slate-500">{p.catalog || current?.name} · {p.active ? "Aktif" : "Nonaktif"}</span></span></label>)}{loaded && !products.length && <p className="py-8 text-center text-sm text-slate-500">Belum ada produk yang sesuai. Tambahkan produk atau pindahkan dari katalog lain.</p>}</div>
        <Link className="inline-block text-sm text-cyan-400" to={current ? `/products?catalog=${encodeURIComponent(current.name)}` : "/products"}>Kelola harga, varian & inventory →</Link>
      </section>
    </div>
  </div>;
}
