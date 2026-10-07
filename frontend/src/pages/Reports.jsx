import { useCallback, useEffect, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import api, { fmtAmount } from "../lib/api";

const today = () => new Date().toISOString().slice(0, 10);

export default function Reports() {
  const [period, setPeriod] = useState("daily");
  const [date, setDate] = useState(today());
  const [month, setMonth] = useState(today().slice(0, 7));
  const [currency, setCurrency] = useState("all");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data: result } = await api.get("/admin/reports", {
        params: {
          ...(period === "daily" ? { date } : { month }),
          currency,
        },
      });
      setData(result);
    } finally {
      setLoading(false);
    }
  }, [period, date, month, currency]);

  const download = async () => {
    const res = await api.get("/admin/reports/export", {
      params: {
        ...(period === "daily" ? { date } : { month }),
        currency,
      },
      responseType: "blob",
    });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = `report-${period === "daily" ? date : month}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const money = (obj) => Object.entries(obj || {}).map(([cur, val]) => `${cur} ${fmtAmount(val, cur)}`).join(" · ") || "-";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2 items-center">
        <button onClick={() => setPeriod("daily")} className={period === "daily" ? "px-3 py-2 rounded-lg border border-cyan-500/40 text-cyan-400 text-sm" : "px-3 py-2 rounded-lg border border-slate-800 text-slate-400 text-sm"}>Harian</button>
        <button onClick={() => setPeriod("monthly")} className={period === "monthly" ? "px-3 py-2 rounded-lg border border-cyan-500/40 text-cyan-400 text-sm" : "px-3 py-2 rounded-lg border border-slate-800 text-slate-400 text-sm"}>Bulanan</button>
        {period === "daily" ? (
          <input type="date" value={date} onChange={e => setDate(e.target.value)} className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm" />
        ) : (
          <input type="month" value={month} onChange={e => setMonth(e.target.value)} className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm" />
        )}
        <select value={currency} onChange={e => setCurrency(e.target.value)} className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm">
          <option value="all">Semua Currency</option><option value="IDR">IDR</option><option value="USD">USD</option>
        </select>
        <button onClick={load} className="p-2 rounded-lg border border-slate-800 text-slate-400 hover:text-slate-100" title="Refresh"><RefreshCw size={16} /></button>
        <button onClick={download} className="ml-auto flex items-center gap-2 px-3 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-semibold"><Download size={16} /> Download Excel</button>
      </div>

      {loading && <div className="text-slate-500 text-sm">Memuat rekap...</div>}
      {data && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              ["Orders", data.summary.orders],
              ["Selesai", data.summary.completed_orders],
              ["Refund", data.summary.refunded_orders],
              ["Item Terjual", data.summary.items_sold],
              ["Pembeli Unik", data.summary.unique_buyers],
              ["Depositor Unik", data.summary.unique_depositors],
            ].map(([label, value]) => <div key={label} className="bg-slate-900/70 border border-slate-800 rounded-xl p-4"><p className="text-xs text-slate-500">{label}</p><p className="text-xl font-bold mt-1">{value}</p></div>)}
          </div>

          <div className="grid lg:grid-cols-3 gap-3">
            <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4"><p className="text-xs text-slate-500 mb-2">Gross Sales</p><p className="font-semibold">{money(data.summary.gross_sales)}</p></div>
            <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4"><p className="text-xs text-slate-500 mb-2">Refund</p><p className="font-semibold">{money(data.summary.refund_total)}</p></div>
            <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4"><p className="text-xs text-slate-500 mb-2">Net Sales</p><p className="font-semibold">{money(data.summary.net_sales)}</p></div>
            <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4"><p className="text-xs text-slate-500 mb-2">Deposit Approved</p><p className="font-semibold">{money(data.summary.deposits)}</p></div>
            <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4"><p className="text-xs text-slate-500 mb-2">Total Discount</p><p className="font-semibold">{money(data.summary.discount_total)}</p></div>
          </div>

          <div className="bg-slate-900/70 border border-slate-800 rounded-xl overflow-x-auto">
            <div className="px-4 py-3 border-b border-slate-800 font-semibold">Rekap Produk</div>
            <table className="w-full text-sm"><thead><tr className="text-xs text-slate-500 border-b border-slate-800"><th className="px-4 py-3 text-left">Produk</th><th className="px-4 py-3">Qty</th><th className="px-4 py-3">Orders</th><th className="px-4 py-3">Gross</th><th className="px-4 py-3">Discount</th></tr></thead>
              <tbody>{data.products.map(p => <tr key={p.product_id || p.name} className="border-b border-slate-800/60"><td className="px-4 py-3">{p.name}</td><td className="text-center">{p.qty}</td><td className="text-center">{p.orders}</td><td className="text-center">{money(p.gross)}</td><td className="text-center">{money(p.discount)}</td></tr>)}</tbody>
            </table>
          </div>

          {period === "monthly" && <div className="bg-slate-900/70 border border-slate-800 rounded-xl overflow-x-auto">
            <div className="px-4 py-3 border-b border-slate-800 font-semibold">Breakdown Harian</div>
            <table className="w-full text-sm"><thead><tr className="text-xs text-slate-500 border-b border-slate-800"><th className="px-4 py-3">Tanggal</th><th>Orders</th><th>Item</th><th>Gross</th><th>Deposit</th><th>Refund</th><th>Net</th></tr></thead>
              <tbody>{data.daily.map(d => <tr key={d.date} className="border-b border-slate-800/60"><td className="px-4 py-3">{d.date}</td><td className="text-center">{d.orders}</td><td className="text-center">{d.items}</td><td className="text-center">{money(d.gross)}</td><td className="text-center">{money(d.deposits)}</td><td className="text-center">{money(d.refunds)}</td><td className="text-center">{money(Object.fromEntries(Object.keys(d.gross).map(c => [c, (d.gross[c] || 0) - (d.refunds[c] || 0)])))}</td></tr>)}</tbody>
            </table>
          </div>}
        </>
      )}
    </div>
  );
}
