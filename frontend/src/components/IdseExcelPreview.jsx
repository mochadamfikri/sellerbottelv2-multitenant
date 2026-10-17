import { useState } from 'react';
import api from '../lib/api';
import { toast } from 'sonner';
import { CheckCircle2, AlertTriangle, FileSpreadsheet, Loader2, ArrowRight } from 'lucide-react';

export default function IdseExcelPreview({ onImportSuccess }) {
  const [file, setFile] = useState(null);
  const [tenant, setTenant] = useState('main');
  const [precedence, setPrecedence] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState(null);

  const preview = async () => {
    if (!file) return;
    setBusy(true);
    setError('');
    setResult(null);
    setApplyResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('summary_precedence', String(precedence));
      const response = await api.post('/v2/import-excel/preview', form, {
        headers: { 'X-Tenant-ID': tenant.trim() || 'main' },
      });
      setResult(response.data);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Preview gagal. Periksa format XLSX dan batas ukuran 10 MB.';
      setError(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  };

  const handleApply = async () => {
    if (!result?.apply_allowed) return;
    setApplying(true);
    setError('');
    try {
      const form = new FormData();
      if (result.plan?.job_id && result.plan?.confirmation_token) {
        form.append('job_id', result.plan.job_id);
        form.append('confirmation_token', result.plan.confirmation_token);
        form.append('summary_precedence', String(precedence));
      } else if (file) {
        form.append('file', file);
        form.append('summary_precedence', String(precedence));
      }

      const response = await api.post('/v2/import-excel/apply', form, {
        headers: { 'X-Tenant-ID': tenant.trim() || 'main' },
      });

      const data = response.data;
      setApplyResult(data);
      toast.success(data.message || 'Import Excel berhasil diterapkan!');
      if (onImportSuccess) {
        onImportSuccess(data);
      }
    } catch (err) {
      const msg = err.response?.data?.detail || 'Gagal menerapkan import ke database.';
      setError(msg);
      toast.error(msg);
    } finally {
      setApplying(false);
    }
  };

  const diff = result?.database_diff || [];
  const newProductsCount = diff.filter((d) => d.action === 'CREATE').length;
  const updatedProductsCount = diff.filter((d) => d.action === 'UPDATE').length;
  const totalProducts = result?.products?.length || 0;
  const jasaCount = result?.products?.filter((p) => p.kind === 'Jasa').length || 0;
  const freshCount = result?.products?.filter((p) => p.kind === 'FRESH BY MADE').length || 0;
  const digitalCount = result?.products?.filter((p) => p.kind === 'Product').length || 0;

  const validInventoryCount =
    result?.products?.reduce((acc, p) => acc + (p.inventory?.valid_available || 0), 0) || 0;
  const skippedInventoryCount =
    result?.products?.reduce((acc, p) => acc + (p.inventory?.skipped || 0), 0) || 0;

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 my-4" aria-label="Import Excel IDSE">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="text-emerald-400" size={20} />
          <h2 className="font-semibold text-slate-100 text-base">One Excel Full Import System (IDSE)</h2>
        </div>
        <span className="text-xs font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded">
          Automated V2 Importer
        </span>
      </div>

      <p className="text-xs text-slate-400 mb-4">
        Impor katalog produk, varian digital, jasa, Fresh by Made, deskripsi lengkap, garansi terstruktur, dan stok terenkripsi langsung dari 1 workbook XLSX master.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1">Tenant ID</label>
          <input
            className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono focus:border-cyan-500/60"
            value={tenant}
            onChange={(e) => {
              setTenant(e.target.value);
              setResult(null);
              setApplyResult(null);
            }}
            placeholder="main"
          />
        </div>

        <div className="md:col-span-2">
          <label className="block text-xs text-slate-400 mb-1">Workbook XLSX Master</label>
          <input
            type="file"
            accept=".xlsx"
            className="w-full text-xs text-slate-300 file:mr-2 file:py-1 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-slate-800 file:text-slate-200 hover:file:bg-slate-700 cursor-pointer"
            onChange={(e) => {
              setFile(e.target.files?.[0] || null);
              setResult(null);
              setApplyResult(null);
            }}
          />
        </div>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <input
          type="checkbox"
          id="precedence"
          checked={precedence}
          onChange={(e) => {
            setPrecedence(e.target.checked);
            setResult(null);
            setApplyResult(null);
          }}
          className="rounded border-slate-700 text-emerald-500 focus:ring-emerald-500/20"
        />
        <label htmlFor="precedence" className="text-xs text-slate-300 cursor-pointer">
          Gunakan <b>Summary</b> sebagai acuan utama bila ada perbedaan jenis/harga (Approved Precedence).
        </label>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={busy || !file}
          onClick={preview}
          className="flex items-center gap-2 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 text-xs font-semibold rounded-lg px-4 py-2 transition"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : null}
          {busy ? 'Menganalisis Workbook…' : '1. Dry-Run / Preview Workbook'}
        </button>

        {result?.apply_allowed && (
          <button
            type="button"
            disabled={applying}
            onClick={handleApply}
            className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-xs font-semibold rounded-lg px-4 py-2 transition shadow-lg shadow-emerald-900/30"
          >
            {applying ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            {applying ? 'Menerapkan ke Database…' : '2. Konfirmasi & Terapkan Import (Apply)'}
          </button>
        )}
      </div>

      {error && (
        <div role="alert" className="mt-3 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-2">
          <AlertTriangle size={15} className="shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {applyResult && (
        <div className="mt-4 p-4 rounded-lg bg-emerald-950/40 border border-emerald-500/30 text-emerald-200 text-xs space-y-2">
          <div className="flex items-center gap-2 font-semibold text-emerald-300 text-sm">
            <CheckCircle2 size={16} /> {applyResult.message}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 font-mono">
            <div>Produk Baru: {applyResult.stats?.products_created || 0}</div>
            <div>Produk Diperbarui: {applyResult.stats?.products_updated || 0}</div>
            <div>Katalog Baru: {applyResult.stats?.catalogs_created || 0}</div>
            <div>Stok Diimpor: {applyResult.stats?.inventory_inserted || 0} pcs</div>
          </div>
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-2 text-center text-xs">
            <div className="bg-slate-950/70 border border-slate-800/80 p-2 rounded-lg">
              <div className="text-slate-400 text-[10px]">Total Produk</div>
              <div className="font-semibold text-slate-100 mt-0.5">{totalProducts}</div>
            </div>
            <div className="bg-slate-950/70 border border-slate-800/80 p-2 rounded-lg">
              <div className="text-slate-400 text-[10px]">Produk Baru (Diff)</div>
              <div className="font-semibold text-emerald-400 mt-0.5">{newProductsCount}</div>
            </div>
            <div className="bg-slate-950/70 border border-slate-800/80 p-2 rounded-lg">
              <div className="text-slate-400 text-[10px]">Update (Diff)</div>
              <div className="font-semibold text-cyan-400 mt-0.5">{updatedProductsCount}</div>
            </div>
            <div className="bg-slate-950/70 border border-slate-800/80 p-2 rounded-lg">
              <div className="text-slate-400 text-[10px]">Digital / Jasa / Fresh</div>
              <div className="font-semibold text-slate-200 mt-0.5">{digitalCount}/{jasaCount}/{freshCount}</div>
            </div>
            <div className="bg-slate-950/70 border border-slate-800/80 p-2 rounded-lg">
              <div className="text-slate-400 text-[10px]">Stok Valid</div>
              <div className="font-semibold text-emerald-300 mt-0.5">{validInventoryCount} pcs</div>
            </div>
            <div className="bg-slate-950/70 border border-slate-800/80 p-2 rounded-lg">
              <div className="text-slate-400 text-[10px]">Stok Dilewati</div>
              <div className="font-semibold text-amber-300 mt-0.5">{skippedInventoryCount}</div>
            </div>
          </div>

          <div className="overflow-x-auto border border-slate-800 rounded-lg max-h-72">
            <table className="w-full text-xs text-left">
              <thead className="bg-slate-950 text-slate-400 sticky top-0 border-b border-slate-800">
                <tr>
                  <th className="p-2">SKU</th>
                  <th className="p-2">Produk</th>
                  <th className="p-2">Katalog</th>
                  <th className="p-2">Jenis</th>
                  <th className="p-2">Harga (IDR)</th>
                  <th className="p-2">Sheet Stok</th>
                  <th className="p-2">Diff DB</th>
                  <th className="p-2">Catatan/Issues</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50 bg-slate-900/30">
                {(result.products || []).map((p, i) => {
                  const dbDiffItem = diff.find((d) => d.sku === p.sku);
                  const diffAction = dbDiffItem?.action || 'CREATE';
                  return (
                    <tr key={`${p.sku}-${i}`} className="hover:bg-slate-800/30">
                      <td className="p-2 font-mono font-medium text-cyan-300">{p.sku}</td>
                      <td className="p-2 max-w-[200px] truncate text-slate-200" title={p.name}>{p.name}</td>
                      <td className="p-2 text-slate-400">{p.catalog_name}</td>
                      <td className="p-2">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                          p.kind === 'Product' ? 'bg-blue-500/10 text-blue-400' :
                          p.kind === 'Jasa' ? 'bg-purple-500/10 text-purple-400' :
                          'bg-amber-500/10 text-amber-400'
                        }`}>
                          {p.kind}
                        </span>
                      </td>
                      <td className="p-2 font-mono text-slate-200">
                        {p.price_idr != null ? `Rp ${Number(p.price_idr).toLocaleString('id-ID')}` : <span className="text-amber-400 italic">Belum diset</span>}
                      </td>
                      <td className="p-2 text-slate-400 font-mono text-[11px]">{p.source_sheet}</td>
                      <td className="p-2">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                          diffAction === 'CREATE' ? 'bg-emerald-500/20 text-emerald-400' :
                          diffAction === 'UPDATE' ? 'bg-cyan-500/20 text-cyan-400' :
                          'bg-slate-800 text-slate-400'
                        }`}>
                          {diffAction}
                        </span>
                      </td>
                      <td className="p-2 text-slate-400 text-[11px]">
                        {p.issues?.length > 0 ? (
                          <span className="text-amber-400">{p.issues.join(', ')}</span>
                        ) : (
                          <span className="text-emerald-400">Siap</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {(result.errors || []).length > 0 && (
            <div className="space-y-1">
              <p className="text-xs font-semibold text-rose-400">Kesalahan Validasi:</p>
              {result.errors.map((e, i) => (
                <p key={i} className="text-xs text-rose-300/90 font-mono bg-rose-950/30 px-2 py-1 rounded">
                  {e.sheet ? `[${e.sheet}]` : '[Workbook]'} {e.row ? `Baris ${e.row}: ` : ''}{e.code}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
