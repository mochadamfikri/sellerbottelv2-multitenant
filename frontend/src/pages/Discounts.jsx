import { useEffect, useMemo, useState } from "react";
import { Percent, BadgeDollarSign, CheckSquare, Square } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";

const empty = {
  name: "",
  product_ids: [],
  mode: "percent",
  value: "",
  min_qty: 1,
  max_qty: "",
  priority: 0,
  fixed_currency: "IDR",
  starts_at: "",
  ends_at: "",
  active: true,
};

const cls = "w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";

const toLocalInput = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
};

const fromLocalInput = (value) => value ? new Date(value).toISOString() : null;

export default function Discounts() {
  const [discounts, setDiscounts] = useState([]);
  const [products, setProducts] = useState([]);
  const [form, setForm] = useState(empty);
  const [editing, setEditing] = useState(null);
  const [allProducts, setAllProducts] = useState(true);
  const [busy, setBusy] = useState(false);

  const productMap = useMemo(() => Object.fromEntries(products.map((p) => [p._id, p.name])), [products]);

  const load = async () => {
    try {
      const [d, p] = await Promise.all([
        api.get("/admin/discounts"),
        api.get("/admin/products"),
      ]);
      setDiscounts(d.data);
      setProducts(p.data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal memuat discount.");
    }
  };

  useEffect(() => { load(); }, []);

  const toggleProduct = (id) => {
    setForm((current) => {
      const exists = current.product_ids.includes(id);
      return {
        ...current,
        product_ids: exists ? current.product_ids.filter((x) => x !== id) : [...current.product_ids, id],
      };
    });
  };

  const save = async () => {
    setBusy(true);
    try {
      const payload = {
        name: form.name.trim(),
        product_ids: allProducts ? [] : form.product_ids,
        mode: form.mode,
        value: parseFloat(form.value),
        min_qty: parseInt(form.min_qty || 1, 10),
        max_qty: form.max_qty ? parseInt(form.max_qty, 10) : null,
        fixed_currency: form.mode === "fixed" ? form.fixed_currency : null,
        starts_at: fromLocalInput(form.starts_at),
        ends_at: fromLocalInput(form.ends_at),
        active: form.active,
        priority: parseInt(form.priority || 0, 10),
      };
      if (!payload.name || !Number.isFinite(payload.value) || payload.value <= 0 ||
          (form.starts_at && Number.isNaN(new Date(form.starts_at).getTime())) ||
          (form.ends_at && Number.isNaN(new Date(form.ends_at).getTime())) ||
          (form.starts_at && form.ends_at && new Date(form.ends_at) <= new Date(form.starts_at))) {
        toast.error("Nama dan nilai discount wajib diisi.");
        return;
      }
      if (!allProducts && !payload.product_ids.length) {
        toast.error("Pilih minimal satu product atau pilih Semua Product.");
        return;
      }
      const response = editing
        ? await api.put("/admin/discounts/" + editing, payload)
        : await api.post("/admin/discounts", payload);
      const refreshed = (await api.get("/admin/discounts")).data || [];
      if (!refreshed.some((rule) => rule._id === response.data?._id)) {
        throw new Error("Aturan diskon belum terlihat di daftar setelah disimpan.");
      }
      setDiscounts(refreshed);
      toast.success(editing ? "Discount diperbarui." : "Discount dibuat.");
      setForm(empty);
      setEditing(null);
      setAllProducts(true);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || err.message || "Gagal menyimpan discount.");
    } finally {
      setBusy(false);
    }
  };

  const edit = (d) => {
    const ids = d.product_ids || [];
    setEditing(d._id);
    setAllProducts(ids.length === 0);
    setForm({
      name: d.name || "",
      product_ids: ids,
      mode: d.mode || "percent",
      value: String(d.value ?? ""),
      min_qty: d.min_qty ?? 1,
      max_qty: d.max_qty ?? "",
      priority: d.priority ?? 0,
      fixed_currency: d.fixed_currency || "IDR",
      active: d.active !== false,
      starts_at: toLocalInput(d.starts_at),
      ends_at: toLocalInput(d.ends_at),
    });
  };

  const remove = async (d) => {
    if (!window.confirm('Hapus discount "' + d.name + '"?')) return;
    try {
      await api.delete("/admin/discounts/" + d._id);
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  const toggle = async (d) => {
    try {
      await api.patch("/admin/discounts/" + d._id + "/toggle");
      await load();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  const previewTotal = form.mode === "fixed"
    ? Math.max(0, Number(form.value || 0)) * Math.max(1, Number(form.min_qty || 1))
    : 0;

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-5">
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
        <div>
          <h2 className="font-heading font-semibold">{editing ? "Edit Discount" : "Buat Discount"}</h2>
          <p className="text-xs text-slate-500 mt-1">Tentukan product yang mendapat potongan dan aturan nilainya.</p>
        </div>

        <div>
          <label className="text-xs text-slate-400">Nama Discount</label>
          <input className={cls} placeholder="Contoh: Promo Gmail September" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-200 font-semibold">Product yang didiskon</p>
              <p className="text-xs text-slate-500">Pilih semua product atau hanya product tertentu.</p>
            </div>
            <button onClick={() => setAllProducts((v) => !v)} className="inline-flex items-center gap-2 text-xs text-cyan-400">
              {allProducts ? <CheckSquare size={15} /> : <Square size={15} />} Semua Product
            </button>
          </div>

          {!allProducts && (
            <div className="max-h-56 overflow-y-auto space-y-1 pr-1">
              {products.map((p) => {
                const selected = form.product_ids.includes(p._id);
                return (
                  <button
                    key={p._id}
                    onClick={() => toggleProduct(p._id)}
                    className={"w-full text-left px-3 py-2 rounded-lg border text-sm " + (selected ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-300" : "border-slate-800 text-slate-400 hover:bg-slate-800/60")}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span>{p.name}</span>
                      {selected ? <CheckSquare size={14} /> : <Square size={14} />}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div>
          <label className="text-xs text-slate-400">Jenis Potongan</label>
          <div className="grid grid-cols-2 gap-2 mt-1">
            <button
              onClick={() => setForm({ ...form, mode: "percent" })}
              className={"rounded-lg border px-3 py-2.5 text-sm flex items-center justify-center gap-2 " + (form.mode === "percent" ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-300" : "border-slate-800 text-slate-400")}
            >
              <Percent size={15} /> Persen (%)
            </button>
            <button
              onClick={() => setForm({ ...form, mode: "fixed" })}
              className={"rounded-lg border px-3 py-2.5 text-sm flex items-center justify-center gap-2 " + (form.mode === "fixed" ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-300" : "border-slate-800 text-slate-400")}
            >
              <BadgeDollarSign size={15} /> Nominal / unit
            </button>
          </div>
        </div>

        {form.mode === "percent" ? (
          <div className="space-y-3">
            <label className="text-xs text-slate-400">Nilai Persentase</label>
            <div className="relative">
              <input type="number" min="0.01" max="100" step="0.01" className={cls + " pr-10"} placeholder="10" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
              <span className="absolute right-3 top-2.5 text-xs text-slate-500">%</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div><label className="text-xs text-slate-400">Quantity minimum</label><input type="number" min="1" className={cls} value={form.min_qty} onChange={(e) => setForm({ ...form, min_qty: e.target.value })} /></div>
              <div><label className="text-xs text-slate-400">Quantity maksimum (opsional)</label><input type="number" min="1" className={cls} value={form.max_qty} onChange={(e) => setForm({ ...form, max_qty: e.target.value })} /></div>
            </div>
          </div>
        ) : (
          <div className="space-y-3 rounded-lg border border-slate-800 bg-slate-950/40 p-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-slate-400">Quantity mulai</label>
                <input type="number" min="1" className={cls} value={form.min_qty} onChange={(e) => setForm({ ...form, min_qty: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400">Sampai quantity (opsional)</label>
                <input type="number" min="1" className={cls} placeholder="Tidak dibatasi" value={form.max_qty} onChange={(e) => setForm({ ...form, max_qty: e.target.value })} />
              </div>
            </div>
            <div className="grid grid-cols-[130px_1fr] gap-2">
              <div>
                <label className="text-xs text-slate-400">Unit</label>
                <select className={cls} value={form.fixed_currency} onChange={(e) => setForm({ ...form, fixed_currency: e.target.value })}>
                  <option value="IDR">IDR / unit</option>
                  <option value="USD">USD / unit</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400">Potongan per unit</label>
                <input type="number" min="0.01" step="0.01" className={cls} placeholder="500" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
              </div>
            </div>
            <div className="rounded-lg bg-emerald-500/5 border border-emerald-500/10 px-3 py-2 text-sm">
              <span className="text-slate-500">Total potongan pada quantity mulai:</span>
              <b className="ml-2 text-emerald-400">
                {form.fixed_currency === "IDR" ? "Rp " : "$"}{previewTotal.toLocaleString("id-ID")}
              </b>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-slate-400">Mulai promo (opsional)</label>
            <input type="datetime-local" className={cls} value={form.starts_at} onChange={(e) => setForm({ ...form, starts_at: e.target.value })} />
          </div>
          <div>
            <label className="text-xs text-slate-400">Berakhir (opsional)</label>
            <input type="datetime-local" className={cls} value={form.ends_at} onChange={(e) => setForm({ ...form, ends_at: e.target.value })} />
          </div>
        </div>

        <div>
          <label className="text-xs text-slate-400">Prioritas aturan</label>
          <input type="number" min="-1000" max="1000" className={cls} value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} />
          <p className="text-[11px] text-slate-500 mt-1">Jika beberapa aturan cocok, prioritas tertinggi dipakai; jika sama, diskon nominal terbesar yang dipakai.</p>
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
          Discount aktif
        </label>

        <div className="flex gap-2">
          <button onClick={save} disabled={busy} className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold rounded-lg py-2.5">
            {editing ? "Simpan Perubahan" : "Buat Discount"}
          </button>
          {editing && (
            <button onClick={() => { setEditing(null); setForm(empty); setAllProducts(true); }} className="px-4 rounded-lg border border-slate-800 text-slate-300">Batal</button>
          )}
        </div>
        <p className="text-xs text-amber-300">Diskon berlaku di checkout setelah kamu menekan “Buat Discount” dan aturannya muncul di Daftar Discount dengan status Aktif.</p>
      </div>

      <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-x-auto">
        <div className="px-5 py-4 border-b border-slate-800">
          <h2 className="font-heading font-semibold">Daftar Discount</h2>
          <p className="text-xs text-slate-500 mt-1">{discounts.length} aturan tersimpan.</p>
        </div>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-xs text-slate-500 uppercase">
              <th className="px-4 py-3">Nama</th><th className="px-4 py-3">Produk</th><th className="px-4 py-3">Aturan</th><th className="px-4 py-3">Status</th><th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {discounts.map((d) => (
              <tr key={d._id} className="border-b border-slate-800/60 align-top">
                <td className="px-4 py-3"><div className="font-medium">{d.name}</div></td>
                <td className="px-4 py-3 text-xs text-slate-400">
                  {d.product_ids?.length ? d.product_ids.map((id) => productMap[id] || id).join(", ") : "Semua Product"}
                </td>
                <td className="px-4 py-3 font-mono text-xs">
                  {(d.mode === "percent" ? String(d.value) + "%" : String(d.fixed_currency || "currency") + " " + String(d.value) + "/unit") +
                    " · qty " + String(d.min_qty || 1) + (d.max_qty ? "–" + String(d.max_qty) : "+") + " · prioritas " + String(d.priority || 0)}
                </td>
                <td className="px-4 py-3"><span className={d.active ? "text-emerald-400" : "text-slate-600"}>{d.active ? "Aktif" : "Off"}</span></td>
                <td className="px-4 py-3 text-right">
                  <div className="flex justify-end gap-3 text-xs">
                    <button onClick={() => edit(d)} className="text-cyan-400 hover:text-cyan-300">Edit</button>
                    <button onClick={() => toggle(d)} className="text-slate-400 hover:text-slate-200">Toggle</button>
                    <button onClick={() => remove(d)} className="text-rose-400 hover:text-rose-300">Hapus</button>
                  </div>
                </td>
              </tr>
            ))}
            {!discounts.length && <tr><td colSpan={5} className="px-4 py-12 text-center text-slate-500">Belum ada discount.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
