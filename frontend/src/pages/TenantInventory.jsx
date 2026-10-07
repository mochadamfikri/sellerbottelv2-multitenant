import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { groupCatalogs } from "../lib/catalog";
import { toast } from "sonner";
import { Upload, Plus, Trash2, RefreshCw, Database, PackageCheck } from "lucide-react";
import api, { formatApiErrorDetail } from "../lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";

const cls = "w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";

export default function TenantInventory() {
  const [products, setProducts] = useState([]);
  const [bulkText, setBulkText] = useState("");
  const [schemaText, setSchemaText] = useState("");
  const [editing, setEditing] = useState(null);
  const [editData, setEditData] = useState({});
  const [replacementFile, setReplacementFile] = useState(null);
  const [pid, setPid] = useState("");
  const [meta, setMeta] = useState({ schema: [], items: [], available: 0, reserved: 0, sold: 0 });
  const [status, setStatus] = useState("available");
  const [inventoryPage, setInventoryPage] = useState(0);
  const [file, setFile] = useState(null);
  const [files, setFiles] = useState([]);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [manualData, setManualData] = useState({});
  const [fileName, setFileName] = useState("");
  const [transformFile, setTransformFile] = useState(null);
  const [transformInfo, setTransformInfo] = useState(null);
  const [oldDomain, setOldDomain] = useState("");
  const [newDomain, setNewDomain] = useState("");
  const [emailColumn, setEmailColumn] = useState("");
  const [passwordColumn, setPasswordColumn] = useState("");
  const [passwordMode, setPasswordMode] = useState("random");
  const [fixedPassword, setFixedPassword] = useState("");
  const [showFixedPassword, setShowFixedPassword] = useState(false);
  const actionLock = useRef(false);
  const fileInputRef = useRef(null);

  const selectedProduct = useMemo(() => products.find((p) => p._id === pid) || null, [products, pid]);

  const loadProducts = useCallback(async (silent = false) => {
    try {
      const { data } = await api.get("/public/tenant/full/products");
      const digital = (Array.isArray(data) ? data : data.products || []).filter((p) => p.product_kind !== "service");
      setProducts(digital);
      if (!pid && digital.length) setPid(digital[0]._id);
      if (pid && !digital.some((p) => p._id === pid)) setPid(digital[0]?._id || "");
    } catch (err) {
      if (!silent) toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal memuat product inventory.");
    }
  }, [pid]);

  const loadInventory = useCallback(async () => {
    if (!pid) {
      setMeta({ schema: [], items: [], available: 0, reserved: 0, sold: 0 });
      return;
    }
    try {
      const { data } = await api.get("/public/tenant/full/products/" + pid + "/inventory", { params: { status, offset: inventoryPage * 100, limit: 100 } });
      setMeta(data);
      const next = {};
      (data.schema || []).forEach((field) => { next[field] = ""; });
      setManualData((current) => Object.keys(current).length ? current : next);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal memuat inventory.");
    }
  }, [pid, status, inventoryPage]);

  useEffect(() => { loadProducts(); }, [loadProducts]);
  useEffect(() => { loadInventory(); }, [loadInventory]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible" || busy || !pid) return;
      loadProducts(true);
      api.get(`/admin/products/${pid}/inventory/summary`)
        .then(({ data }) => setMeta((current) => ({ ...current, ...data })))
        .catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [busy, pid, loadProducts]);

  const selectProduct = (value) => {
    setEditing(null); setBulkText(""); setSchemaText("");
    setPid(value);
    setInventoryPage(0);
    setFile(null);
    setFiles([]);
    setFileName("");
    setPreview(null);
    setManualData({});
    setTransformFile(null);
    setTransformInfo(null);
    setOldDomain("");
    setNewDomain("");
    setEmailColumn("");
    setPasswordColumn("");
    setPasswordMode("random");
    setFixedPassword("");
  };

  const validateFile = async (selectedFile = file, selectedPid = pid) => {
    if (!selectedFile && fileInputRef.current?.files?.[0]) selectedFile = fileInputRef.current.files[0];
    if (!selectedPid || (!selectedFile && !bulkText.trim())) {
      toast.error("Pilih product dan file inventory terlebih dahulu.");
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("content", bulkText);
      if ((selectedProduct?.inventory_mode === "telegram_session" || (selectedProduct?.inventory_schema?.length === 1 && selectedProduct.inventory_schema[0] === "Session File"))) {
        (files.length ? files : (selectedFile ? [selectedFile] : [])).forEach((f) => fd.append("files", f, f.name));
      } else {
        if (selectedFile) fd.append("file", selectedFile, selectedFile.name);
      }
      const { data } = await api.post("/public/tenant/full/products/" + selectedPid + "/inventory/validate", fd);
      setPreview(data);
      const next = {};
      (data.schema || []).forEach((field) => { next[field] = ""; });
      setManualData(next);
      toast.success("Valid: " + data.valid_count + " · Duplikat: " + data.duplicate_count);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Validasi gagal.");
    } finally {
      setBusy(false);
    }
  };

  const importFile = async (selectedFile = file, selectedPid = pid) => {
    if (!selectedFile && fileInputRef.current?.files?.[0]) selectedFile = fileInputRef.current.files[0];
    if (!selectedPid || (!selectedFile && !bulkText.trim())) {
      toast.error("Pilih product dan file inventory terlebih dahulu.");
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("content", bulkText);
      if (selectedProduct?.inventory_mode === "telegram_session" || selectedProduct?.inventory_schema?.length === 1 && selectedProduct.inventory_schema[0] === "Session File") {
        (files.length ? files : (selectedFile ? [selectedFile] : [])).forEach((f) => fd.append("files", f, f.name));
      } else {
        if (selectedFile) fd.append("file", selectedFile, selectedFile.name);
      }
      const { data } = await api.post("/public/tenant/full/products/" + selectedPid + "/inventory/import", fd);
      toast.success("Inventory masuk: " + data.created + " item · dilewati: " + data.skipped);
      setFile(null);
      setFileName("");
      setPreview(null);
      setBulkText("");
      await loadProducts();
      await loadInventory();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Import inventory gagal.");
    } finally {
      setBusy(false);
    }
  };

  const addManual = async () => {
    if (!pid) return;
    setBusy(true);
    try {
      await api.post("/public/tenant/full/products/" + pid + "/inventory/manual", { data: manualData });
      toast.success("1 data inventory ditambahkan.");
      const cleared = {};
      (meta.schema || []).forEach((field) => { cleared[field] = ""; });
      setManualData(cleared);
      await loadProducts();
      await loadInventory();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal menambah data inventory.");
    } finally {
      setBusy(false);
    }
  };

  const removeItem = async (itemId) => {
    if (!window.confirm("Hapus item inventory yang masih tersedia ini?")) return;
    try {
      await api.delete("/public/tenant/full/products/" + pid + "/inventory/" + itemId);
      toast.success("Item dihapus dari inventory.");
      await loadProducts();
      await loadInventory();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal menghapus item.");
    }
  };

  const inspectTransform = async () => {
    if (!pid || !transformFile) { toast.error("Pilih produk dan file yang akan diolah."); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", transformFile, transformFile.name);
      const { data } = await api.post(`/admin/products/${pid}/inventory/transform/inspect`, fd);
      setTransformInfo(data);
      setEmailColumn(data.email_columns?.find((name) => name.toLowerCase() === "email") || data.email_columns?.[0] || "");
      setPasswordColumn(data.password_columns?.[0] || "");
      if (!data.password_columns?.length) setPasswordMode("keep");
      toast.success(`${data.row_count} baris terbaca. Pilih perubahan lalu unduh hasilnya.`);
    } catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail) || "File gagal dibaca."); }
    finally { setBusy(false); }
  };

  const downloadTransformed = async () => {
    if (!transformFile || !transformInfo) { toast.error("Baca kolom file terlebih dahulu."); return; }
    if (!newDomain.trim() && passwordMode === "keep") { toast.error("Isi domain baru atau pilih pengubahan sandi."); return; }
    if (newDomain.trim() && !emailColumn) { toast.error("File tidak punya kolom email yang bisa diubah."); return; }
    if (passwordMode !== "keep" && !passwordColumn) { toast.error("File tidak punya header password/kata sandi/sandi."); return; }
    if (passwordMode === "fixed" && !fixedPassword) { toast.error("Isi nilai sandi tetap."); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", transformFile, transformFile.name);
      fd.append("old_domain", oldDomain.trim());
      fd.append("new_domain", newDomain.trim());
      fd.append("email_column", newDomain.trim() ? emailColumn : "");
      fd.append("password_column", passwordMode === "keep" ? "" : passwordColumn);
      fd.append("password_mode", passwordMode);
      fd.append("fixed_password", passwordMode === "fixed" ? fixedPassword : "");
      const response = await api.post(`/admin/products/${pid}/inventory/transform`, fd, { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `inventory-transformed-${(selectedProduct?.name || "produk").replace(/[^a-z0-9_-]+/gi, "-")}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      toast.success(`File diunduh: ${response.headers["x-rows"] || transformInfo.row_count} baris, ${response.headers["x-domain-changes"] || 0} domain, ${response.headers["x-password-changes"] || 0} sandi diubah.`);
    } catch (err) {
      let detail = err.response?.data?.detail;
      if (err.response?.data instanceof Blob) {
        try { detail = JSON.parse(await err.response.data.text()).detail; } catch (_) { /* empty */ }
      }
      toast.error(formatApiErrorDetail(detail) || "Gagal mengolah file inventory.");
    } finally { setBusy(false); }
  };

  const saveEdit = async () => {
    setBusy(true);
    try {
      const path = `/admin/products/${pid}/inventory/${editing._id}`;
      if (editing.item?.is_file) {
        if (!replacementFile) { toast.error("Pilih file .session pengganti."); return; }
        const data = new FormData(); data.append("file", replacementFile);
        await api.post(`${path}/file`, data);
      } else await api.put(path, { data: editData });
      toast.success("Item inventory diperbarui."); setEditing(null); await loadInventory();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Item gagal diperbarui."); }
    finally { setBusy(false); }
  };
  const downloadTemplate = async (format) => {
    try {
      const { data } = await api.get(`/admin/products/${pid}/inventory/template`, { params: { format }, responseType: "blob" });
      const url = URL.createObjectURL(data); const a = document.createElement("a"); a.href = url; a.download = `inventory-template.${format}`; a.click(); URL.revokeObjectURL(url);
    } catch (_) { toast.error("Template tidak tersedia. Pilih produk inventory tabel."); }
  };
  const saveSchema = async () => {
    setBusy(true);
    try { await api.put(`/admin/products/${pid}/inventory/schema`, { fields: schemaText.split(",") }); await loadProducts(); await loadInventory(); toast.success("Kolom inventory disimpan."); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Kolom gagal disimpan."); }
    finally { setBusy(false); }
  };

  const selectedStock = selectedProduct?.stock_mode === "manual"
    ? Math.min(Math.max(0, Number(selectedProduct?.manual_stock ?? selectedProduct?.stock ?? 0) - Number(meta.marketing_allocated || 0)), Number(meta.available ?? 0))
    : Number(meta.available ?? 0);

  return (
    <div className="space-y-5">
      <p className="text-xs text-slate-500">Jumlah stok diperbarui otomatis setiap 5 detik saat halaman aktif.</p>
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto_auto_auto] gap-3 items-end">
        <div>
          <label className="text-xs text-slate-400">Pilih product inventory</label>
          <select className={cls} value={pid} onChange={(e) => selectProduct(e.target.value)}>
            <option value="">Pilih product</option>
            {groupCatalogs(products).map((catalog) => <optgroup key={catalog.key} label={catalog.name}>{catalog.products.map((p) => <option key={p._id} value={p._id}>{p.name}</option>)}</optgroup>)}
          </select>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-4 py-2.5">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Available</div>
          <div className="font-mono font-bold text-emerald-400">{selectedStock}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-4 py-2.5">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Reserved</div>
          <div className="font-mono font-bold text-amber-400">{meta.reserved}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 px-4 py-2.5">
          <div className="text-[10px] uppercase tracking-widest text-slate-500">Sold</div>
          <div className="font-mono font-bold text-slate-300">{meta.sold}</div><p className="mt-1 text-xs text-cyan-300">Marketing / By Me: {meta.marketing_allocated || 0}</p>
        </div>
      </div>

      {selectedProduct && (
        <div className="bg-slate-900/70 border border-slate-800 rounded-xl px-4 py-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-slate-200 font-semibold"><Database size={16} className="text-cyan-400" /> {selectedProduct.name}</div>
            <p className="mt-1 text-xs text-cyan-400">Katalog: {selectedProduct.catalog_name || "Produk Lainnya"}</p>
            <p className="text-xs text-slate-500 mt-1">Semua upload dan input manual di halaman ini hanya masuk ke product yang sedang dipilih.</p>
          </div>
          <div className="text-xs text-slate-500">Schema file wajib: <span className="text-cyan-300 font-mono">{(meta.schema || []).join(" · ") || "Belum ditentukan — header file valid pertama akan menjadi schema product"}</span></div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
          <div>
            <h2 className="font-heading font-semibold flex items-center gap-2"><Upload size={17} className="text-emerald-400" /> Upload Bulk Inventory</h2>
            <p className="text-xs text-slate-500 mt-1">Pilih product dulu, lalu upload file. XLSX/CSV/TXT memakai header/schema product. File binary seperti .session dikirim sebagai file asli dan tidak dipaksa mengikuti schema kolom.</p>
          </div>
          <input
            type="file"
            accept={(selectedProduct?.inventory_mode === "telegram_session" || (selectedProduct?.inventory_schema?.length === 1 && selectedProduct.inventory_schema[0] === "Session File")) ? "*/*" : ".xlsx,.csv,.txt"}
            ref={fileInputRef}
            className={cls}
            multiple={selectedProduct?.inventory_mode === "telegram_session" || (selectedProduct?.inventory_schema?.length === 1 && selectedProduct.inventory_schema[0] === "Session File")}
            onChange={(e) => {
              const picked = Array.from(e.target.files || []);
              const selected = picked[0] || null;
              setFiles(picked);
              setFile(selected);
              setFileName(selectedProduct?.inventory_mode === "telegram_session" ? (picked.length + " file .session dipilih") : (selected?.name || ""));
              setPreview(null);
            }}
          />
          {selectedProduct && selectedProduct.inventory_mode !== "telegram_session" && <><div className="flex flex-wrap gap-2">{["xlsx", "csv", "txt"].map((format) => <button key={format} type="button" className="rounded bg-slate-800 px-3 py-2 text-xs" onClick={() => downloadTemplate(format)}>Template {format.toUpperCase()}</button>)}</div><textarea rows={4} className={cls} disabled={Boolean(file)} placeholder="Atau tempel data TXT. Header kolom pada baris pertama, satu item per baris, dipisahkan |." value={bulkText} onChange={(e) => { setBulkText(e.target.value); setPreview(null); }}/><p className="text-xs text-slate-500">Gunakan kolom sesuai template. Katalog melekat pada produk, bukan pada baris inventory.</p></>}
          {fileName && <p className="text-xs text-cyan-400 mt-2 break-all">File dipilih: {fileName}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (actionLock.current || busy) return;
                actionLock.current = true;
                Promise.resolve(validateFile(file, pid)).finally(() => { actionLock.current = false; });
              }}
              className="flex-1 px-4 py-2.5 rounded-lg border border-slate-700 text-slate-200 disabled:opacity-40"
            >
              {busy ? "Memproses..." : "Validasi"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                if (actionLock.current || busy) return;
                actionLock.current = true;
                Promise.resolve(importFile(file, pid)).finally(() => { actionLock.current = false; });
              }}
              className="flex-1 px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-40"
            >
              {busy ? "Memproses..." : "Import Bulk"}
            </button>
          </div>
          {preview && (
            <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 text-xs text-slate-300 space-y-1">
              <div>Schema: <b>{(preview.schema || []).join(" · ")}</b></div>
              <div>Valid baru: <b>{preview.valid_count}</b> · Duplikat: <b>{preview.duplicate_count}</b></div>
              {!!preview.preview?.length && <div className="mt-2 text-slate-500">Preview record: {JSON.stringify(preview.preview[0])}</div>}
            </div>
          )}
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
          <div>
            <h2 className="font-heading font-semibold flex items-center gap-2"><Plus size={17} className="text-cyan-400" /> Input Data Manual</h2>
            <p className="text-xs text-slate-500 mt-1">Form ini memakai field inventory milik product yang sedang dipilih.</p>
          </div>
          {selectedProduct?.inventory_mode === "telegram_session" || meta.schema?.[0] === "Session File" ? <p className="text-sm text-slate-400">Unggah file .session asli melalui Upload Bulk Inventory. Setiap file menjadi satu item; gunakan Ganti file untuk memperbarui item.</p> : !meta.schema?.length ? (
            <div className="space-y-3"><p className="text-sm text-slate-500">Tetapkan kolom untuk input manual, atau unggah file dengan header.</p><input className={cls} placeholder="email,password,recovery" value={schemaText} onChange={(e) => setSchemaText(e.target.value)}/><button className="rounded bg-cyan-700 px-3 py-2 text-sm disabled:opacity-40" disabled={busy || !pid || !schemaText.trim()} onClick={saveSchema}>Simpan kolom inventory</button></div>
          ) : (
            <>
              <div className="space-y-3">
                {meta.schema.map((field) => (
                  <div key={field}>
                    <label className="text-xs text-slate-400">{field}</label>
                    <input
                      className={cls}
                      value={manualData[field] || ""}
                      onChange={(e) => setManualData({ ...manualData, [field]: e.target.value })}
                      placeholder={field}
                    />
                  </div>
                ))}
              </div>
              <button type="button" disabled={!pid || busy || !Object.values(manualData).some((v) => String(v || "").trim())} onClick={addManual} className="w-full px-4 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold disabled:opacity-40">Simpan 1 Data</button>
            </>
          )}
        </div>
      </div>

      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
        <div><h2 className="font-heading font-semibold flex items-center gap-2"><Upload size={17} className="text-cyan-400" /> Pengolah File Inventory</h2>
          <p className="text-xs text-slate-500 mt-1">Unggah XLSX/CSV/TXT, ubah domain email dan/atau sandi, lalu unduh XLSX hasilnya. Data stok yang sudah tersimpan tidak berubah. Periksa file hasil sebelum mengimpor lewat Upload Bulk di atas. Pengubahan file tidak mengganti sandi akun pada layanan aslinya.</p></div>
        <div className="grid gap-3 lg:grid-cols-2">
          <div><label className="text-xs text-slate-400">File yang akan diolah</label><input type="file" accept=".xlsx,.csv,.txt" className={cls} onChange={(event) => { setTransformFile(event.target.files?.[0] || null); setTransformInfo(null); }} /></div>
          <div className="flex items-end"><button type="button" disabled={busy || !pid || !transformFile} onClick={inspectTransform} className="w-full rounded-lg bg-slate-700 hover:bg-slate-600 px-4 py-2.5 text-sm disabled:opacity-40">Baca Kolom File</button></div>
        </div>
        {transformInfo && <>
          <p className="text-xs text-cyan-300">{transformInfo.row_count} baris · header: {transformInfo.schema.join(" · ")}</p>
          <div className="grid gap-3 md:grid-cols-3">
            <div><label className="text-xs text-slate-400">Domain lama (opsional)</label><input className={cls} placeholder="gmail.com" value={oldDomain} onChange={(event) => setOldDomain(event.target.value)} /></div>
            <div><label className="text-xs text-slate-400">Domain baru</label><input className={cls} placeholder="contoh.com" value={newDomain} onChange={(event) => setNewDomain(event.target.value)} /></div>
            <div><label className="text-xs text-slate-400">Kolom email yang diubah</label><select className={cls} value={emailColumn} onChange={(event) => setEmailColumn(event.target.value)}>
              <option value="">Tidak ada</option>{(transformInfo.email_columns || []).map((field) => <option key={field} value={field}>{field}</option>)}
            </select></div>
          </div>
          <p className="text-xs text-slate-500">Jika domain lama kosong, semua alamat pada kolom email terpilih memakai domain baru. Kolom email pemulihan hanya berubah bila dipilih.</p>
          <div className="grid gap-3 md:grid-cols-2">
            <div><label className="text-xs text-slate-400">Pengubahan kata sandi</label><select className={cls} value={passwordMode} onChange={(event) => setPasswordMode(event.target.value)}>
              <option value="random">Acak 12 karakter per baris</option><option value="fixed">Nilai tetap untuk semua baris</option><option value="keep">Tidak diubah</option>
            </select></div>
            <div><label className="text-xs text-slate-400">Kolom sandi</label><select className={cls} value={passwordColumn} onChange={(event) => setPasswordColumn(event.target.value)} disabled={passwordMode === "keep"}>
              <option value="">Pilih kolom</option>{(transformInfo.password_columns || []).map((field) => <option key={field} value={field}>{field}</option>)}
            </select></div>
          </div>
          {passwordMode === "fixed" && <div><label className="text-xs text-slate-400">Nilai sandi tetap</label><div className="flex gap-2"><input className={cls} type={showFixedPassword ? "text" : "password"} value={fixedPassword} onChange={(event) => setFixedPassword(event.target.value)} placeholder="Isi sandi yang dipakai untuk setiap baris" /><button type="button" className="rounded-lg bg-slate-700 px-3 text-xs" onClick={() => setShowFixedPassword(!showFixedPassword)}>{showFixedPassword ? "Sembunyikan" : "Lihat"}</button></div></div>}
          {passwordMode === "random" && <p className="text-xs text-slate-400">Setiap baris mendapat sandi berbeda sepanjang 12 karakter, berisi huruf besar, huruf kecil, angka, dan karakter spesial.</p>}
          <button type="button" disabled={busy} onClick={downloadTransformed} className="rounded-lg bg-cyan-600 hover:bg-cyan-700 px-4 py-2.5 text-sm font-semibold disabled:opacity-40">Buat dan Unduh XLSX Hasil</button>
        </>}
      </div>

      <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-heading font-semibold flex items-center gap-2"><PackageCheck size={17} className="text-cyan-400" /> Data Inventory</h2>
            <p className="text-xs text-slate-500 mt-1">Item tersedia dapat diedit atau dihapus satu per satu. Item reserved/terjual/marketing dikunci. Restore marketing melalui Broadcast → Campaign.</p>
          </div>
          <div className="flex gap-2">
            <select className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm" value={status} onChange={(e) => { setStatus(e.target.value); setInventoryPage(0); }}>
              <option value="available">Available</option>
              <option value="reserved">Reserved</option>
              <option value="sold">Sold</option>
              <option value="marketing_allocated">Marketing / By Me</option>
              <option value="all">Semua</option>
            </select>
            <button type="button" onClick={loadInventory} className="p-2 rounded-lg border border-slate-800 text-slate-400 hover:text-cyan-400" title="Refresh"><RefreshCw size={16} /></button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs text-slate-500 uppercase">
                <th className="px-5 py-3">Data</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">Order</th>
                <th className="px-5 py-3">Telegram ID</th>
                <th className="px-5 py-3">Tanggal</th>
                <th className="px-5 py-3 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {(meta.items || []).map((item) => (
                <tr key={item._id} className="border-b border-slate-800/60 align-top">
                  <td className="px-5 py-3">
                    {item.item ? (
                      <div className="space-y-1 text-xs font-mono">
                        {item.item.is_file ? <span>{item.item.file}</span> : (meta.schema || Object.keys(item.item)).map((field) => (
                          <div key={field}><span className="text-slate-500">{field}:</span> <span className="text-slate-200 break-all">{item.item?.[field] ?? ""}</span></div>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-slate-600">Data disembunyikan untuk item terjual.</span>
                    )}
                  </td>
                  <td className="px-5 py-3">
                    <span className={
                      item.status === "available" ? "text-emerald-400" :
                      item.status === "reserved" ? "text-amber-400" : "text-slate-400"
                    }>{item.status}</span>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs text-slate-400">{item.order_id || "—"}</td>
                  <td className="px-5 py-3 font-mono text-xs text-slate-400">{item.user_tid || "—"}</td>
                  <td className="px-5 py-3 text-xs text-slate-500">{item.sold_at || item.created_at}</td>
                  <td className="px-5 py-3 text-right">
                    {item.status === "available" && (
                      <div className="flex justify-end gap-2"><button type="button" disabled={busy} onClick={() => { setEditing(item); setEditData({ ...item.item }); setReplacementFile(null); }} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-cyan-400">{item.item?.is_file ? "Ganti file" : "Edit"}</button><button type="button" disabled={busy} onClick={() => removeItem(item._id)} className="flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-xs text-rose-400" title="Hapus item"><Trash2 size={15}/> Hapus</button></div>
                    )}
                  </td>
                </tr>
              ))}
              {!meta.items?.length && <tr><td colSpan={6} className="px-5 py-10 text-center text-slate-500">Belum ada data inventory untuk product ini.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-slate-800 p-4 text-xs"><span>{meta.total || 0} item · halaman {inventoryPage + 1}</span><div className="flex gap-3"><button disabled={!inventoryPage || busy} className="text-cyan-400 disabled:opacity-40" onClick={() => setInventoryPage(inventoryPage - 1)}>Sebelumnya</button><button disabled={(inventoryPage + 1) * 100 >= (meta.total || 0) || busy} className="text-cyan-400 disabled:opacity-40" onClick={() => setInventoryPage(inventoryPage + 1)}>Berikutnya</button></div></div>
      </div>
      <Dialog open={Boolean(editing)} onOpenChange={(open) => { if (!open && !busy) setEditing(null); }}><DialogContent className="max-h-[85vh] overflow-y-auto border-slate-800 bg-slate-900 text-slate-100"><DialogHeader><DialogTitle>Edit item inventory</DialogTitle></DialogHeader><p className="text-xs text-slate-400">{selectedProduct?.catalog_name} → {selectedProduct?.name}</p>{editing?.item?.is_file ? <input type="file" accept=".session" onChange={(e) => setReplacementFile(e.target.files?.[0] || null)}/> : (meta.schema || []).map((field) => <label key={field} className="text-sm">{field}<input className={cls} value={editData[field] || ""} onChange={(e) => setEditData({ ...editData, [field]: e.target.value })}/></label>)}<button disabled={busy} onClick={saveEdit} className="rounded-lg bg-cyan-700 px-4 py-2 disabled:opacity-40">{busy ? "Menyimpan…" : "Simpan perubahan"}</button></DialogContent></Dialog>
    </div>
  );
}
