import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";

export default function Messages() {
  const [rows, setRows] = useState([]);
  const [lang, setLang] = useState("id");
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState([]);
  const [historyOpen, setHistoryOpen] = useState(false);

  const load = () => api.get("/admin/messages").then(({ data }) => setRows(data));
  useEffect(() => { load(); }, []);

  const visible = useMemo(() => rows.filter((r) => r.lang === lang && (!filter || r.key.includes(filter))), [rows, lang, filter]);

  const save = async () => {
    setBusy(true);
    try {
      await api.put("/admin/messages/" + editing.lang + "/" + editing.key, { text });
      toast.success("Pesan disimpan");
      setEditing(null); load();
    } catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail)); }
    finally { setBusy(false); }
  };

  const reset = async (row) => {
    await api.delete("/admin/messages/" + row.lang + "/" + row.key);
    load();
  };

  const openHistory = async (row) => {
    try {
      const { data } = await api.get("/admin/messages/" + row.lang + "/" + row.key + "/history");
      setEditing(row);
      setHistory(data);
      setHistoryOpen(true);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  const rollback = async (version) => {
    try {
      const { data } = await api.post("/admin/messages/" + editing.lang + "/" + editing.key + "/rollback", { version });
      toast.success("Rollback ke version " + version + " berhasil");
      setHistoryOpen(false);
      load();
      setText(data.text || text);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  const testRow = async (row) => {
    try {
      await api.post("/admin/messages/test", { lang: row.lang, key: row.key, text: row.text });
      toast.success("Test dikirim ke Telegram admin");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  const cls = "w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";
  return (
    <>
      <div className="flex gap-2 flex-wrap">
        <button className={lang === "id" ? "px-4 py-2 rounded-lg border border-cyan-500/40 text-cyan-400" : "px-4 py-2 rounded-lg border border-slate-800 text-slate-400"} onClick={() => setLang("id")}>Indonesia</button>
        <button className={lang === "en" ? "px-4 py-2 rounded-lg border border-cyan-500/40 text-cyan-400" : "px-4 py-2 rounded-lg border border-slate-800 text-slate-400"} onClick={() => setLang("en")}>English</button>
        <input className="ml-auto w-64 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm" placeholder="Cari key..." value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b border-slate-800 text-xs text-slate-500 uppercase"><th className="px-4 py-3">Key</th><th className="px-4 py-3">Custom</th><th className="px-4 py-3">Preview</th><th className="px-4 py-3 text-right">Aksi</th></tr></thead>
          <tbody>
            {visible.map((row) => (
              <tr key={row.lang + ":" + row.key} className="border-b border-slate-800/60 align-top">
                <td className="px-4 py-3 font-mono text-xs text-cyan-400">{row.key}</td>
                <td className="px-4 py-3 text-xs">{row.custom ? "Ya" : "Default"}</td>
                <td className="px-4 py-3 text-xs text-slate-400 max-w-xl">{row.text}</td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <button className="text-emerald-400 text-xs mr-3" onClick={() => testRow(row)}>Test</button>
                  <button className="text-cyan-400 text-xs mr-3" onClick={() => { setEditing(row); setText(row.text); }}>Edit</button>
                  <button className="text-violet-400 text-xs mr-3" onClick={() => openHistory(row)}>History</button>
                  {row.custom && <button className="text-rose-400 text-xs" onClick={() => reset(row)}>Reset</button>}

                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {historyOpen && editing && (
        <div className="fixed inset-0 z-[60] bg-black/60 flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <div className="flex justify-between">
              <h3 className="font-heading font-semibold">History — {editing.key}</h3>
              <button onClick={() => setHistoryOpen(false)} className="text-slate-400">✕</button>
            </div>
            <div className="max-h-[60vh] overflow-y-auto space-y-2">
              {history.map((h) => (
                <div key={h._id} className="border border-slate-800 rounded-lg p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-xs text-cyan-400">v{h.version}</span>
                    <span className="text-[11px] text-slate-500">{h.created_at}</span>
                    <button onClick={() => rollback(h.version)} className="text-xs text-amber-400">Rollback</button>
                  </div>
                  <p className="mt-2 text-xs text-slate-400 whitespace-pre-wrap">{h.text}</p>
                </div>
              ))}
              {!history.length && <p className="text-sm text-slate-500">Belum ada history.</p>}
            </div>
          </div>
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
            <div className="flex justify-between"><h3 className="font-heading font-semibold">{editing.lang} / {editing.key}</h3><button onClick={() => setEditing(null)} className="text-slate-400">✕</button></div>
            <textarea rows={12} className={cls} value={text} onChange={(e) => setText(e.target.value)} />
            <p className="text-xs text-slate-500">Placeholder dan HTML Telegram divalidasi backend.</p>
            <button onClick={save} disabled={busy} className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold rounded-lg py-2.5">{busy ? "Menyimpan..." : "Simpan"}</button>
          </div>
        </div>
      )}
    </>
  );
}
