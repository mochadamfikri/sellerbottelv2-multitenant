import { useState } from 'react';
import api from '../lib/api';

export default function IdseExcelPreview() {
  const [file, setFile] = useState(null);
  const [tenant, setTenant] = useState('');
  const [precedence, setPrecedence] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const preview = async () => {
    setBusy(true); setError(''); setResult(null);
    try {
      const form = new FormData(); form.append('file', file);
      form.append('summary_precedence', String(precedence));
      const response = await api.post('/v2/import-excel/preview', form, { headers: { 'X-Tenant-ID': tenant.trim() } });
      setResult(response.data);
    } catch { setError('Preview gagal. Periksa akses tenant, format XLSX, dan batas ukuran 10 MB.'); }
    finally { setBusy(false); }
  };
  return <section className="rounded border p-4 my-4" aria-label="Import Excel IDSE">
    <h2 className="font-semibold">Import Excel IDSE — Preview</h2>
    <p>Belum mengubah database. Apply belum tersedia pada tahap ini.</p>
    <label className="block">Tenant ID<input className="border p-2 ml-2 text-black" value={tenant} onChange={e => {setTenant(e.target.value); setResult(null);}} /></label>
    <label className="block">Workbook XLSX<input type="file" accept=".xlsx" onChange={e => {setFile(e.target.files?.[0] || null); setResult(null);}} /></label>
    <label className="block"><input type="checkbox" checked={precedence} onChange={e => {setPrecedence(e.target.checked);setResult(null);}} /> Saya memilih Summary sebagai acuan konflik jenis/harga</label>
    <button type="button" className="border rounded p-2 mt-2" disabled={busy || !file || !tenant.trim()} onClick={preview}>{busy ? 'Memvalidasi…' : 'Dry-run / Preview'}</button>
    {error && <p role="alert">{error}</p>}
    {result && <div className="overflow-x-auto"><p>{result.message}</p>
      <p>{result.summary_rows} baris · {result.sheet_count} sheet · {result.errors?.length || 0} kesalahan struktur/mapping</p>
      <table className="w-full text-sm"><caption>Metadata sumber — belum dibandingkan dengan database</caption><thead><tr>{['SKU','Jenis','Harga IDR','Sheet','Status'].map(h => <th key={h} className="text-left p-2">{h}</th>)}</tr></thead><tbody>
        {(result.products || []).map((p,i) => <tr key={`${p.sku}-${i}`}><td>{p.sku}</td><td>{p.kind}</td><td>{p.price_idr ?? 'Belum ditentukan'}</td><td>{p.source_sheet}</td><td>{p.issues.join(', ') || 'Perlu review'}</td></tr>)}
      </tbody></table>
      {(result.errors || []).map((e,i) => <p key={i} role="alert">{e.sheet || 'Workbook'} {e.row || ''}: {e.code}</p>)}
    </div>}
  </section>;
}
