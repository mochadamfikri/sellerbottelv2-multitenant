export default function BroadcastOptions({ form, change }) {
  const cls = "mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100";
  return <div className="space-y-3 rounded-lg border border-slate-800 p-3">
    <label className="block text-sm">Gambar broadcast<select className={cls} value={form.image_mode || "generated"} onChange={(e) => change({ ...form, image_mode: e.target.value })}><option value="generated">Buat gambar otomatis</option><option value="none">Teks saja</option><option value="auto">Ikuti pengaturan Auto Generate Picture</option></select></label>
    {form.kind === "message" && <label className="block text-sm">Judul gambar (opsional)<input className={cls} maxLength={80} value={form.title || ""} onChange={(e) => change({ ...form, title: e.target.value })} placeholder="Pilihan produk minggu ini"/></label>}
    {form.target !== "users" && <><label className="flex gap-2 text-sm"><input type="checkbox" checked={form.chat_ids != null} onChange={(e) => change({ ...form, chat_ids: e.target.checked ? [] : null })}/> Pilih tujuan khusus untuk broadcast ini</label>{form.chat_ids != null && <textarea rows={3} className={cls} placeholder="Satu ID channel/grup atau @username per baris" value={form.chat_ids.join("\n")} onChange={(e) => change({ ...form, chat_ids: e.target.value.split("\n") })}/>}<p className="text-xs text-slate-500">Tanpa tujuan khusus, gunakan channel di Pengaturan. Rekap dan produk terlaris memakai tujuan rekap.</p></>}
  </div>;
}
