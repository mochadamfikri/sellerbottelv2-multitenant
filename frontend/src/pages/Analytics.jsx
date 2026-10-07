import { useEffect, useState } from "react";
import api, { formatApiErrorDetail } from "../lib/api";
import { toast } from "sonner";
import { BarChart3, Globe, ShoppingBag, Bot, MousePointerClick, ShoppingCart, RefreshCw, Users } from "lucide-react";

export default function Analytics() {
  const [timeRange, setTimeRange] = useState("7d");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchAnalytics = async (range) => {
    setLoading(true);
    try {
      const res = await api.get(`/admin/analytics/summary?time_range=${range}`);
      setData(res.data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics(timeRange);
  }, [timeRange]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold font-heading text-slate-100 flex items-center gap-2.5">
            <BarChart3 className="text-cyan-400" size={24} />
            Analytics & Traffic
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Pantau traffic website, aktivitas bot Telegram, dan interaksi produk secara real-time.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex bg-slate-900 border border-slate-800 rounded-lg p-1">
            {[
              { id: "24h", label: "24 Jam" },
              { id: "7d", label: "7 Hari" },
              { id: "30d", label: "30 Hari" },
              { id: "all", label: "Semua" },
            ].map((btn) => (
              <button
                key={btn.id}
                onClick={() => setTimeRange(btn.id)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  timeRange === btn.id
                    ? "bg-cyan-500/20 text-cyan-400 border border-cyan-500/30"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {btn.label}
              </button>
            ))}
          </div>

          <button
            onClick={() => fetchAnalytics(timeRange)}
            disabled={loading}
            className="p-2 rounded-lg bg-slate-800 text-slate-300 hover:text-white border border-slate-700 disabled:opacity-50"
            title="Refresh Data"
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Traffic Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* Profile Web Traffic */}
        <div className="bg-[#0D1220] border border-slate-800 rounded-xl p-5 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono uppercase text-slate-400 tracking-wider">Profile Website Traffic</span>
            <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <Globe size={18} />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-bold font-mono text-slate-100">
              {loading ? "..." : data?.profile_web?.page_views || 0}
            </div>
            <p className="text-xs text-slate-500 mt-1">Total Page Views</p>
          </div>
          <div className="mt-4 pt-4 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
            <span>Pengunjung Unik (IP): <strong className="text-slate-200">{data?.profile_web?.unique_visitors || 0}</strong></span>
            <span>Klik: <strong className="text-slate-200">{data?.profile_web?.interactions || 0}</strong></span>
          </div>
        </div>

        {/* Shopping Web Traffic */}
        <div className="bg-[#0D1220] border border-slate-800 rounded-xl p-5 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono uppercase text-slate-400 tracking-wider">Shopping Website Traffic</span>
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <ShoppingBag size={18} />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-bold font-mono text-slate-100">
              {loading ? "..." : data?.shopping_web?.page_views || 0}
            </div>
            <p className="text-xs text-slate-500 mt-1">Total Page Views</p>
          </div>
          <div className="mt-4 pt-4 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
            <span>Pengunjung Toko (IP): <strong className="text-slate-200">{data?.shopping_web?.unique_visitors || 0}</strong></span>
            <span>Interaksi: <strong className="text-slate-200">{data?.shopping_web?.interactions || 0}</strong></span>
          </div>
        </div>

        {/* Telegram Bot Traffic */}
        <div className="bg-[#0D1220] border border-slate-800 rounded-xl p-5 relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono uppercase text-slate-400 tracking-wider">Telegram Bot Traffic</span>
            <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
              <Bot size={18} />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-bold font-mono text-slate-100">
              {loading ? "..." : data?.telegram_bot?.total_events || 0}
            </div>
            <p className="text-xs text-slate-500 mt-1">Total Interaksi Bot</p>
          </div>
          <div className="mt-4 pt-4 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
            <span>Pengguna Bot: <strong className="text-slate-200">{data?.telegram_bot?.bot_users || 0}</strong></span>
            <span>Klik Menu: <strong className="text-slate-200">{data?.telegram_bot?.interactions || 0}</strong></span>
          </div>
        </div>
      </div>

      {/* Product Interactions Top 3 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {/* Top 3 Clicked Products */}
        <div className="bg-[#0D1220] border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <MousePointerClick size={16} className="text-cyan-400" />
            Top 3 Produk Paling Sering Diklik
          </h2>

          <div className="space-y-3">
            {loading ? (
              <p className="text-xs text-slate-500 py-4 text-center">Memuat data produk...</p>
            ) : data?.top_clicked_products?.length > 0 ? (
              data.top_clicked_products.map((item, idx) => (
                <div
                  key={item.product_id}
                  className="flex items-center justify-between p-3 rounded-lg bg-slate-900/60 border border-slate-800"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-full bg-slate-800 flex items-center justify-center text-xs font-mono font-bold text-slate-300">
                      {idx + 1}
                    </span>
                    <span className="text-sm text-slate-200 font-medium line-clamp-1">{item.name}</span>
                  </div>
                  <span className="text-xs font-mono px-2.5 py-1 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-semibold">
                    {item.count} klik
                  </span>
                </div>
              ))
            ) : (
              <p className="text-xs text-slate-500 py-4 text-center">Belum ada aktivitas klik pada periode ini.</p>
            )}
          </div>
        </div>

        {/* Top 3 Added to Cart Products */}
        <div className="bg-[#0D1220] border border-slate-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2 mb-4">
            <ShoppingCart size={16} className="text-emerald-400" />
            Top 3 Produk Masuk Keranjang (Cart)
          </h2>

          <div className="space-y-3">
            {loading ? (
              <p className="text-xs text-slate-500 py-4 text-center">Memuat data produk...</p>
            ) : data?.top_cart_products?.length > 0 ? (
              data.top_cart_products.map((item, idx) => (
                <div
                  key={item.product_id}
                  className="flex items-center justify-between p-3 rounded-lg bg-slate-900/60 border border-slate-800"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-full bg-slate-800 flex items-center justify-center text-xs font-mono font-bold text-slate-300">
                      {idx + 1}
                    </span>
                    <span className="text-sm text-slate-200 font-medium line-clamp-1">{item.name}</span>
                  </div>
                  <span className="text-xs font-mono px-2.5 py-1 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold">
                    {item.count} masuk cart
                  </span>
                </div>
              ))
            ) : (
              <p className="text-xs text-slate-500 py-4 text-center">Belum ada produk masuk keranjang pada periode ini.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
