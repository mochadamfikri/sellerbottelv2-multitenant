import { useCallback, useEffect, useState } from "react";
import { Database, Table, ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import api from "../lib/api";

/**
 * Database browser — lihat collection & dokumen langsung dari panel.
 * Read-only, platform admin only.
 */
export default function DatabaseBrowser() {
  const [collections, setCollections] = useState([]);
  const [selected, setSelected] = useState(null);
  const [docs, setDocs] = useState([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const limit = 20;

  const loadCollections = useCallback(async () => {
    try {
      const res = await api.get("/v2/platform/database/collections");
      setCollections(res.data.collections || []);
    } catch { setCollections([]); }
  }, []);

  const loadDocs = useCallback(async (name, newSkip = 0) => {
    setLoading(true);
    try {
      const res = await api.get(`/v2/platform/database/collections/${name}`, {
        params: { limit, skip: newSkip },
      });
      setDocs(res.data.docs || []);
      setTotal(res.data.total || 0);
      setSkip(newSkip);
    } catch { setDocs([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadCollections(); }, [loadCollections]);

  const select = (name) => {
    setSelected(name);
    loadDocs(name, 0);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      {/* Collection list */}
      <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-bold text-slate-200">
          <Database size={16} /> Collections
        </h3>
        <div className="max-h-[500px] space-y-1 overflow-y-auto">
          {collections.map((c) => (
            <button
              key={c.name}
              onClick={() => select(c.name)}
              className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left text-sm transition-colors ${
                selected === c.name
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "text-slate-300 hover:bg-white/5"
              }`}
            >
              <span className="truncate font-mono text-xs">{c.name}</span>
              <span className="ml-2 shrink-0 rounded-full bg-white/10 px-2 py-0.5 text-xs text-slate-400">
                {c.count >= 0 ? c.count : "?"}
              </span>
            </button>
          ))}
          {collections.length === 0 && (
            <p className="text-sm text-slate-500">Tidak ada collection.</p>
          )}
        </div>
      </div>

      {/* Document viewer */}
      <div className="rounded-2xl border border-white/10 bg-slate-900/60 p-4">
        {!selected ? (
          <div className="flex h-64 items-center justify-center text-slate-500">
            <p className="flex items-center gap-2 text-sm">
              <Table size={16} /> Pilih collection di kiri untuk melihat datanya
            </p>
          </div>
        ) : (
          <>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="font-mono text-sm font-bold text-slate-200">{selected}</h3>
              <button
                onClick={() => loadDocs(selected, skip)}
                className="rounded-lg border border-white/10 p-1.5 text-slate-400 hover:text-white"
              >
                <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
              </button>
            </div>
            <div className="max-h-[450px] space-y-2 overflow-y-auto">
              {docs.map((doc, i) => (
                <details key={i} className="rounded-xl border border-white/10 bg-black/30">
                  <summary className="cursor-pointer truncate px-3 py-2 font-mono text-xs text-slate-300 hover:text-white">
                    {doc._id || `doc-${skip + i + 1}`}
                  </summary>
                  <pre className="overflow-x-auto border-t border-white/10 p-3 font-mono text-xs text-slate-400">
                    {JSON.stringify(doc, null, 2)}
                  </pre>
                </details>
              ))}
              {docs.length === 0 && !loading && (
                <p className="py-8 text-center text-sm text-slate-500">Collection kosong.</p>
              )}
            </div>
            {total > limit && (
              <div className="mt-3 flex items-center justify-between text-sm text-slate-400">
                <span>{skip + 1}-{Math.min(skip + limit, total)} dari {total}</span>
                <div className="flex gap-2">
                  <button
                    disabled={skip === 0}
                    onClick={() => loadDocs(selected, Math.max(0, skip - limit))}
                    className="rounded-lg border border-white/10 p-1.5 disabled:opacity-30"
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <button
                    disabled={skip + limit >= total}
                    onClick={() => loadDocs(selected, skip + limit)}
                    className="rounded-lg border border-white/10 p-1.5 disabled:opacity-30"
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
