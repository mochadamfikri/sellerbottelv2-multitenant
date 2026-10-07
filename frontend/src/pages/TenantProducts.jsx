import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Plus, Pencil, Trash2, Upload, Database, Boxes, BriefcaseBusiness } from "lucide-react";
import api, { fmtUSD, fmtIDR, formatApiErrorDetail } from "../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Switch } from "../components/ui/switch";

const empty = {
  name: "",
  description: "",
  price_usd: "",
  price_idr: "",
  product_kind: "digital",
  stock_mode: "auto",
  inventory_mode: "table",
  stock: "",
  minimum_purchase_qty: 1,
  image_url: "",
  image_source: "generated",
  catalog_name: "",
  inventory_fields: "",
  delivery_type: "link",
  content: "",
  wait_minutes: 5,
  active: true,
};

const cls = "mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";

export default function TenantProducts() {
  const [params, setParams] = useSearchParams();
  const catalogFilter = params.get("catalog") || "";
  const [search, setSearch] = useState("");
  const [catalogOptions, setCatalogOptions] = useState([]);
  const [products, setProducts] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [editId, setEditId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState("");
  const [removeImage, setRemoveImage] = useState(false);

  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importText, setImportText] = useState("");
  const [importResult, setImportResult] = useState(null);
  const [importing, setImporting] = useState(false);

  const [inventoryOpen, setInventoryOpen] = useState(false);
  const [inventoryProduct, setInventoryProduct] = useState(null);
  const [inventoryFile, setInventoryFile] = useState(null);
  const [inventoryBusy, setInventoryBusy] = useState(false);
  const [inventoryResult, setInventoryResult] = useState(null);

  const load = async (silent = false) => {
    try {
      const { data } = await api.get("/public/tenant/full/products");
      setProducts(Array.isArray(data) ? data : data.products || []);
      const catalogs = await api.get("/public/tenant/full/catalogs");
      setCatalogOptions((Array.isArray(catalogs.data) ? catalogs.data : catalogs.data.catalogs || []).map((c) => c.name));
    } catch (err) {
      if (!silent) toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal memuat produk.");
    }
  };

  useEffect(() => {
    load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") load(true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const openCreate = () => {
    setForm({ ...empty, catalog_name: catalogFilter });
    setImageFile(null);
    setImagePreview("");
    setRemoveImage(false);
    setEditId(null);
    setOpen(true);
  };

  const openEdit = (p) => {
    const kind = p.product_kind || (p.delivery_type === "inventory" ? "digital" : "service");
    setForm({
      name: p.name || "",
      description: p.description || "",
      price_usd: p.price_usd ?? "",
      price_idr: p.price_idr ?? "",
      product_kind: kind,
      stock_mode: p.stock_mode === "manual" ? "manual" : "auto",
      inventory_mode: p.inventory_mode === "telegram_session" ? "telegram_session" : "table",
      stock: p.manual_stock ?? p.stock ?? "",
      minimum_purchase_qty: p.minimum_purchase_qty ?? 1,
      image_url: p.image_url || "",
      image_source: p.image_source || "generated",
      catalog_name: p.catalog_name || "",
      inventory_fields: (p.inventory_schema || []).join(","),
      delivery_type: p.delivery_type || "link",
      content: p.service_message_template || p.content || "",
      wait_minutes: p.service_wait_minutes || 5,
      active: p.active !== false,
    });
    setImageFile(null);
    setImagePreview(p.image_url || "");
    setRemoveImage(false);
    setEditId(p._id);
    setOpen(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", form.name);
      fd.append("description", form.description);
      fd.append("price_usd", form.price_usd);
      if (form.price_idr !== "") fd.append("price_idr", form.price_idr);
      fd.append("product_kind", form.product_kind);
      fd.append("stock_mode", form.product_kind === "digital" ? form.stock_mode : "auto");
      fd.append("inventory_mode", form.product_kind === "digital" ? form.inventory_mode : "table");
      fd.append("stock", form.product_kind === "digital" && form.stock_mode === "manual" ? (form.stock || "0") : "");
      fd.append("delivery_type", form.product_kind === "digital" ? "inventory" : "service");
      fd.append("content", "");
      fd.append("service_wait_minutes", form.product_kind === "service" ? String(form.wait_minutes || 5) : "");
      fd.append("service_message_template", form.product_kind === "service" ? form.content : "");
      fd.append("active", form.active);
      fd.append("minimum_purchase_qty", String(form.minimum_purchase_qty || 1));
      fd.append("catalog_name", form.catalog_name.trim());
      if (form.product_kind === "digital" && form.inventory_mode !== "telegram_session") fd.append("inventory_fields", form.inventory_fields);
      if (imageFile) fd.append("image", imageFile);
      if (editId) fd.append("remove_image", removeImage ? "true" : "false");

      if (editId) {
        await api.put("/public/tenant/full/products/" + editId, fd);
      } else {
        await api.post("/public/tenant/full/products", fd);
      }
      toast.success(editId ? "Produk diperbarui" : "Produk ditambahkan");
      setOpen(false);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal menyimpan produk.");
    } finally {
      setSaving(false);
    }
  };

  const downloadImportTemplate = async (format = "xlsx") => {
    try {
      const response = await api.get("/public/tenant/full/products/import-template", { responseType: "blob", params: { format } });
      const url = window.URL.createObjectURL(response.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `template-product.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Template gagal dibuat.");
    }
  };

  const importProducts = async () => {
    if (!importFile && !importText.trim()) {
      toast.error("File Excel/CSV belum dipilih.");
      return;
    }
    setImporting(true);
    try {
      const fd = new FormData();
      if (importFile) fd.append("file", importFile, importFile.name);
      else fd.append("content", importText);
      const { data } = await api.post("/public/tenant/full/products/import", fd);
      setImportResult(data);
      toast.success(`Import selesai: ${data.imported || 0} baru, ${data.updated || 0} diperbarui, ${data.inventory_created || 0} item inventory.`);
      setImportFile(null);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Import produk gagal.");
    } finally {
      setImporting(false);
    }
  };

  const openInventory = (p) => {
    setInventoryProduct(p);
    setInventoryFile(null);
    setInventoryResult(null);
    setInventoryOpen(true);
  };

  const validateInventory = async () => {
    if (!inventoryProduct || !inventoryFile) {
      toast.error("Pilih file inventory terlebih dahulu.");
      return;
    }
    setInventoryBusy(true);
    try {
      const fd = new FormData();
      fd.append("content", "");
      fd.append("file", inventoryFile, inventoryFile.name);
      const { data } = await api.post(
        "/public/tenant/full/products/" + inventoryProduct._id + "/inventory/validate",
        fd
      );
      setInventoryResult(data);
      toast.success("Valid: " + (data.valid_count ?? 0) + " · Duplikat: " + (data.duplicate_count ?? 0));
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Validasi inventory gagal.");
    } finally {
      setInventoryBusy(false);
    }
  };

  const importInventory = async () => {
    if (!inventoryProduct || !inventoryFile) {
      toast.error("Pilih file inventory terlebih dahulu.");
      return;
    }
    setInventoryBusy(true);
    try {
      const fd = new FormData();
      fd.append("content", "");
      fd.append("file", inventoryFile, inventoryFile.name);
      const { data } = await api.post(
        "/public/tenant/full/products/" + inventoryProduct._id + "/inventory/import",
        fd
      );
      toast.success("Inventory masuk: " + (data.created ?? 0) + " item · dilewati: " + (data.skipped ?? 0));
      setInventoryOpen(false);
      setInventoryFile(null);
      setInventoryResult(null);
      setInventoryProduct(null);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Import inventory gagal.");
    } finally {
      setInventoryBusy(false);
    }
  };

  const toggle = async (p) => {
    try {
      await api.patch("/public/tenant/full/products/" + p._id + "/toggle");
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  const remove = async (p) => {
    if (!window.confirm('Hapus produk "' + p.name + '"?')) return;
    try {
      await api.delete("/public/tenant/full/products/" + p._id);
      toast.success("Produk dihapus");
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  const kindLabel = (p) => p.product_kind === "service"
    ? "B. Produk Jasa"
    : "A. Produk Digital / Data";

  const renderStock = (p) => {
    if (p.product_kind === "service") return <span className="text-cyan-400">Unlimited</span>;
    const actual = Number(p.inventory_stock ?? 0);
    const cap = p.stock_mode === "manual" ? Number(p.manual_stock ?? p.stock ?? 0) : actual;
    const available = p.stock_mode === "manual" ? Math.min(actual, Math.max(0, cap)) : actual;
    return (
      <div>
        <div className="font-mono font-semibold">{available}</div>
        {p.stock_mode === "manual" && <div className="text-[10px] text-slate-500">limit {cap} · data {actual}</div>}
        {p.stock_mode !== "manual" && <div className="text-[10px] text-slate-500">auto dari inventory</div>}
      </div>
    );
  };

  const visibleProducts = products.filter((p) => (!catalogFilter || p.catalog_name?.toLowerCase() === catalogFilter.toLowerCase()) && `${p.name} ${p.catalog_name || ""}`.toLowerCase().includes(search.toLowerCase()));
  const displayPreview = imageFile ? imagePreview : form.image_source === "uploaded" && !removeImage ? imagePreview : form.name.trim() ? `/api/admin/products/artwork-preview?name=${encodeURIComponent(form.name)}&catalog_name=${encodeURIComponent(form.catalog_name)}` : "";

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center gap-3 flex-wrap">
        <div>
          <p className="text-sm text-slate-400">{products.length} produk</p>
          <p className="text-xs text-slate-600 mt-1">Produk digital memakai inventory per-product. Produk jasa selalu unlimited.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            data-testid="import-products-button"
            onClick={() => { setImportFile(null); setImportOpen(true); }}
            className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold rounded-lg px-4 py-2"
          >
            <Upload size={16} /> Import Produk
          </button>
          <button
            data-testid="add-product-button"
            onClick={openCreate}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg px-4 py-2"
          >
            <Plus size={16} /> Tambah Produk
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <input aria-label="Cari produk" className={`${cls} sm:max-w-xs`} placeholder="Cari produk atau katalog" value={search} onChange={(e) => setSearch(e.target.value)}/>
        <select aria-label="Filter katalog" className={`${cls} sm:max-w-xs`} value={catalogFilter} onChange={(e) => setParams(e.target.value ? { catalog: e.target.value } : {})}><option value="">Semua katalog</option>{catalogOptions.map((name) => <option key={name} value={name}>{name}</option>)}</select>
        <Link className="text-sm text-cyan-400" to="/catalogs">Kelola katalog & pindahkan produk →</Link>
        <span className="text-xs text-slate-500">{visibleProducts.length} produk ditampilkan</span>
      </div>
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-xs text-slate-500 uppercase tracking-wide">
              <th className="px-4 py-3">Produk</th>
              <th className="px-4 py-3">Jenis Product</th>
              <th className="px-4 py-3">Harga USD</th>
              <th className="px-4 py-3">Harga IDR</th>
              <th className="px-4 py-3">Stok</th>
              <th className="px-4 py-3">Schema Inventory</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {visibleProducts.map((p) => (
              <tr key={p._id} className="border-b border-slate-800/60 hover:bg-slate-800/30 align-top">
                <td className="px-4 py-3">
                  <div className="flex items-start gap-3">
                    {p.image_url ? <img src={p.image_url} alt="" className="h-12 w-12 shrink-0 rounded-md object-cover bg-slate-800" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} /> : null}
                    <div>
                      <p className="font-medium text-slate-200">{p.name}</p>
                      <p className="text-xs text-cyan-400">Katalog: {p.catalog_name || "Otomatis"}</p>
                      <p className="text-xs text-slate-500 line-clamp-2">{p.description}</p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-2 text-xs text-slate-300">
                    {p.product_kind === "service" ? <BriefcaseBusiness size={14} /> : <Boxes size={14} />}
                    {kindLabel(p)}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono">{fmtUSD(p.price_usd)}</td>
                <td className="px-4 py-3 font-mono text-slate-400">{p.price_idr ? fmtIDR(p.price_idr) : <span className="text-slate-600 text-xs">auto kurs</span>}</td>
                <td className="px-4 py-3">{renderStock(p)}</td>
                <td className="px-4 py-3 min-w-[220px]">
                  {p.product_kind === "service" ? (
                    <span className="text-xs text-cyan-400">Tidak menggunakan inventory</span>
                  ) : (
                    <div>
                      <div className="text-xs text-slate-300 font-mono break-words">
                        {(p.inventory_schema || []).length ? p.inventory_schema.join(" · ") : "Belum ditentukan"}
                      </div>
                      <div className="text-[10px] text-slate-600 mt-1">
                        {(p.inventory_schema || []).length ? "Header file wajib mengikuti schema ini." : "Validasi upload pertama akan menetapkan schema."}
                      </div>
                    </div>
                  )}
                </td>
                <td className="px-4 py-3">
                  <Switch checked={p.active !== false} onCheckedChange={() => toggle(p)} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1.5">
                    {p.product_kind !== "service" && (
                      <button
                        data-testid={"input-inventory-btn-" + p._id}
                        onClick={() => openInventory(p)}
                        title="Input Data / Inventory"
                        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-emerald-400 hover:bg-emerald-500/10"
                      >
                        <Database size={14} /> Input Data
                      </button>
                    )}
                    <button onClick={() => openEdit(p)} title="Edit" className="p-2 rounded-lg text-slate-400 hover:text-cyan-400 hover:bg-slate-800"><Pencil size={15} /></button>
                    <button onClick={() => remove(p)} title="Hapus" className="p-2 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800"><Trash2 size={15} /></button>
                  </div>
                </td>
              </tr>
            ))}
            {!visibleProducts.length && <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-500">Tidak ada produk yang sesuai.</td></tr>}
          </tbody>
        </table>
      </div>

      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-lg">
          <DialogHeader><DialogTitle>Import Produk · XLSX, CSV, TXT atau teks</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-3 rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3">
              <div>
                <p className="text-sm text-slate-200 font-semibold">Template Excel Bulk Product</p>
                <p className="text-xs text-slate-500 mt-1">Jenis: inventory atau jasa. Harga menggunakan Rupiah.</p>
              </div>
              <div className="flex flex-wrap gap-2">{["xlsx", "csv", "txt"].map((format) => <button key={format} type="button" onClick={() => downloadImportTemplate(format)} className="bg-slate-800 rounded-lg px-3 py-2 text-xs">Template {format.toUpperCase()}</button>)}</div>
            </div>
            <div>
              <label className="text-xs text-slate-400">File Product</label>
              <input type="file" accept=".xlsx,.csv,.txt" className={cls} onChange={(e) => { setImportFile(e.target.files?.[0] || null); setImportResult(null); }} />
              <textarea rows={4} className={cls} disabled={Boolean(importFile)} placeholder="Atau tempel isi template TXT di sini (header wajib, kolom dipisahkan |)." value={importText} onChange={(e) => { setImportText(e.target.value); setImportResult(null); }}/>
              <p className="text-xs text-slate-500 mt-2">Header: katalog | product | jenis (inventory/jasa) | Harga</p>
              <p className="text-xs text-slate-500">Kolom tambahan opsional: Kolom Inventory (email,password), Minimum Pembelian, Deskripsi. CSV/TXT mengimpor produk; data inventory diunggah terpisah. XLSX dapat menyertakan sheet inventory per produk.</p>
              {importResult && <div role="status" className="max-h-40 overflow-auto rounded bg-slate-950 p-3 text-xs"><p>{importResult.imported || 0} produk baru · {importResult.updated || 0} diperbarui · {importResult.inventory_created || 0} item inventory</p>{(importResult.errors || []).map((error, index) => <p key={index} className="mt-1 text-amber-300">{error}</p>)}</div>}
              <p className="text-xs text-slate-500">Isi Katalog yang sama untuk semua varian. Kolom kosong mempertahankan katalog produk lama.</p>
              <p className="text-xs text-slate-600 mt-1">Isi jenis inventory untuk stok data, atau jasa untuk layanan tanpa inventory.</p>
            </div>
            <button onClick={importProducts} disabled={importing || (!importFile && !importText.trim())} className="w-full bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-semibold rounded-lg py-2.5">
              {importing ? "Mengimport..." : "Import Produk"}
            </button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={inventoryOpen} onOpenChange={setInventoryOpen}>
        <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-lg">
          <DialogHeader><DialogTitle>Input Data — {inventoryProduct?.name || "Inventory"}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3">
              <p className="text-xs text-slate-400">Schema file yang wajib digunakan</p>
              <p className="text-sm text-cyan-300 font-mono break-words mt-1">
                {(inventoryProduct?.inventory_schema || []).length
                  ? inventoryProduct.inventory_schema.join(" · ")
                  : "Belum ditentukan — header file valid pertama akan menjadi schema product"}
              </p>
              <p className="text-[11px] text-slate-500 mt-1">Data tabel mengikuti schema product. Mode Telegram Session menerima file .session asli.</p>
            </div>
            <div>
              <label className="text-xs text-slate-400">File Data / Inventory</label>
              <input type="file" accept={inventoryProduct?.inventory_mode === "telegram_session" ? ".session" : ".xlsx,.csv,.txt"} className={cls} onChange={(e) => { setInventoryFile(e.target.files?.[0] || null); setInventoryResult(null); }} />
            </div>
            {inventoryResult && (
              <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-300 space-y-1">
                <p>Field: <b>{(inventoryResult.schema || []).join(" · ")}</b></p>
                <p>Valid baru: <b>{inventoryResult.valid_count ?? 0}</b></p>
                <p>Duplikat: <b>{inventoryResult.duplicate_count ?? 0}</b></p>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2">
              <button onClick={validateInventory} disabled={inventoryBusy || !inventoryFile} className="bg-slate-800 hover:bg-slate-700 disabled:opacity-50 rounded-lg py-2.5 font-semibold">
                {inventoryBusy ? "Memproses..." : "Validasi"}
              </button>
              <button onClick={importInventory} disabled={inventoryBusy || !inventoryFile} className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 rounded-lg py-2.5 font-semibold">
                Import Data
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editId ? "Edit Produk" : "Tambah Produk"}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-xs text-slate-400">Jenis Product</label>
              <select
                className={cls}
                value={form.product_kind}
                onChange={(e) => {
                  const kind = e.target.value;
                  setForm({
                    ...form,
                    product_kind: kind,
                    delivery_type: kind === "digital" ? "inventory" : "service",
                    content: kind === "service"
                      ? (form.content || "Jasa {product_name} sedang dalam antrean, harap tunggu {wait_minutes} untuk dapat menghubungi admin.")
                      : "",
                  });
                }}
              >
                <option value="digital">A. Produk Digital / sudah ada datanya</option>
                <option value="service">B. Produk Jasa</option>
              </select>
            </div>

            <div>
              <label className="text-xs text-slate-400">Nama Produk</label>
              <input className={cls} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>

            <div>
              <label className="text-xs text-slate-400">Katalog</label>
              <input className={cls} list="product-catalogs" maxLength={80} placeholder="Contoh: Claude Pro" value={form.catalog_name} onChange={(e) => setForm({ ...form, catalog_name: e.target.value })} />
              <datalist id="product-catalogs">{catalogOptions.map((name) => <option key={name} value={name}/>)}</datalist>
              <p className="mt-1 text-xs text-slate-500">Gunakan nama katalog yang sama untuk semua varian. Kosongkan untuk pengelompokan otomatis.</p>
              {form.product_kind === "digital" && form.inventory_mode !== "telegram_session" && <><label className="mt-3 block text-xs text-slate-400">Kolom inventory (pisahkan dengan koma)</label><input className={cls} value={form.inventory_fields} placeholder="email,password,recovery" onChange={(e) => setForm({ ...form, inventory_fields: e.target.value })}/><p className="mt-1 text-xs text-slate-500">Isi untuk langsung input manual. Jika kosong, header file pertama menetapkan kolom. Kolom yang sudah ditetapkan harus tetap sama.</p></>}
            </div>

            <div>
              <label className="text-xs text-slate-400">Foto Produk (JPG, PNG, WEBP · maks. 5 MB)</label>
              <p className="mt-1 text-xs text-slate-500">Gambar otomatis diseragamkan ke kanvas 1200 × 1200 px tanpa memotong isi.</p>
              <input type="file" accept="image/jpeg,image/png,image/webp" className={cls} onChange={(e) => { const f = e.target.files?.[0] || null; setImageFile(f); setRemoveImage(false); setImagePreview(f ? URL.createObjectURL(f) : form.image_url || ""); }} />
              <p className="mt-2 text-xs text-cyan-400">Tanpa upload, foto otomatis menampilkan logo layanan, paket (Pro/Trial/Plus), dan durasi dari nama produk. Upload foto untuk menggantinya.</p>
              {displayPreview && <img src={displayPreview} alt="Pratinjau foto produk" className="mt-3 h-48 w-full rounded-lg border border-slate-700 bg-white object-contain p-2" />}
              {editId && form.image_source === "uploaded" && !imageFile && !removeImage && <button type="button" onClick={() => { setRemoveImage(true); setImagePreview(""); }} className="mt-2 text-xs font-medium text-rose-600 hover:text-rose-700">Hapus foto custom · gunakan gambar otomatis</button>}
              {removeImage && <div className="mt-2 flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700"><span>Foto akan dihapus saat perubahan disimpan.</span><button type="button" onClick={() => { setRemoveImage(false); setImagePreview(form.image_url); }} className="font-semibold underline">Batalkan</button></div>}
            </div>

            <div>
              <label className="text-xs text-slate-400">Deskripsi</label>
              <textarea rows={3} className={cls} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-slate-400">Harga USD</label>
                <input type="number" step="0.01" className={cls} value={form.price_usd} onChange={(e) => setForm({ ...form, price_usd: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400">Harga IDR (opsional)</label>
                <input type="number" className={cls} value={form.price_idr} onChange={(e) => setForm({ ...form, price_idr: e.target.value })} />
              </div>
            </div>

            <div>
              <label className="text-xs text-slate-400">Minimum pembelian (pcs)</label>
              <input type="number" min="1" max="1000" step="1" className={cls} value={form.minimum_purchase_qty} onChange={(e) => setForm({ ...form, minimum_purchase_qty: e.target.value })} />
              <p className="mt-1 text-[11px] text-slate-500">Berlaku hanya untuk produk ini. Pembeli harus memasukkan jumlah minimal saat checkout.</p>
            </div>

            {form.product_kind === "digital" ? (
              <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-4 space-y-3">
                <div>
                  <label className="text-xs text-slate-400">Format Inventory</label>
                  <select className={cls} value={form.inventory_mode} onChange={(e) => setForm({ ...form, inventory_mode: e.target.value })}>
                    <option value="table">Data tabel — schema mengikuti header produk</option>
                    <option value="telegram_session">Telegram Session — file .session</option>
                  </select>
                  <p className="text-[11px] text-slate-500 mt-1">Telegram Session khusus produk yang memang menjual file sesi Telegram.</p>
                </div>

                <div>
                  <label className="text-xs text-slate-400">Sumber Stok</label>
                  <select className={cls} value={form.stock_mode} onChange={(e) => setForm({ ...form, stock_mode: e.target.value })}>
                    <option value="auto">Otomatis mengikuti jumlah data/inventory</option>
                    <option value="manual">Manual / batas stok</option>
                  </select>
                </div>
                {form.stock_mode === "manual" ? (
                  <div>
                    <label className="text-xs text-slate-400">Stok manual / batas maksimum</label>
                    <input type="number" min="0" className={cls} value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} />
                  </div>
                ) : (
                  <p className="text-xs text-slate-500">Stok diambil otomatis dari jumlah inventory yang tersedia.</p>
                )}
              </div>
            ) : (
              <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-950/50 p-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-slate-300">Stok</span>
                  <span className="font-mono text-cyan-400">Unlimited</span>
                </div>
                <div>
                  <label className="text-xs text-slate-400">Waktu tunggu untuk dapat menghubungi admin</label>
                  <select className={cls} value={form.wait_minutes || 5} onChange={(e) => setForm({ ...form, wait_minutes: Number(e.target.value) })}>
                    <option value={1}>1 menit</option>
                    <option value={5}>5 menit</option>
                    <option value={10}>10 menit</option>
                    <option value={25}>25 menit</option>
                    <option value={60}>60 menit</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-slate-400">Pesan antrean jasa</label>
                  <textarea
                    rows={4}
                    className={cls}
                    value={form.content}
                    onChange={(e) => setForm({ ...form, content: e.target.value })}
                  />
                  <p className="text-[11px] text-slate-500 mt-1">Placeholder: {"{product_name}"} dan {"{wait_minutes}"}.</p>
                </div>
              </div>
            )}

            <button onClick={save} disabled={saving || !form.name || !form.price_usd} className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold rounded-lg py-2.5">
              {saving ? "Menyimpan..." : "Simpan Produk"}
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
