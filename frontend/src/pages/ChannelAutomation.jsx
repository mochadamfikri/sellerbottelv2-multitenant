import React, { useState, useEffect } from "react";
import api, { fmtIDR, fmtDate, formatApiErrorDetail } from "../lib/api";
import { toast } from "sonner";
import {
  Radio,
  Play,
  Pause,
  Square,
  Plus,
  Trash2,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Send,
  Eye,
  CheckCircle,
  AlertTriangle,
  Layers,
  Sparkles,
  Zap,
  Clock,
  CheckCircle2,
  Sliders,
  ExternalLink,
  ChevronRight,
  Info,
} from "lucide-react";

const inputCls =
  "w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/50 transition duration-150";

export default function ChannelAutomation() {
  const [activeTab, setActiveTab] = useState("campaigns");
  const [metrics, setMetrics] = useState(null);
  const [channel, setChannel] = useState(null);
  const [campaigns, setCampaigns] = useState([]);
  const [reservedList, setReservedList] = useState([]);
  const [protectedProducts, setProtectedProducts] = useState([]);
  const [activityLogs, setActivityLogs] = useState([]);
  const [loading, setLoading] = useState(false);

  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showRestoreModal, setShowRestoreModal] = useState(false);
  const [selectedProductForRestore, setSelectedProductForRestore] = useState(null);
  const [restoreMode, setRestoreMode] = useState("all");
  const [restoreQty, setRestoreQty] = useState(1);

  // New Campaign Form
  const [newCampaign, setNewCampaign] = useState({
    name: "",
    channel_id: "",
    schedule_mode: "custom_sequence",
    sequence_seconds: "180, 120, 180, 360, 300, 330",
    interval_pool_seconds: "30, 60, 90, 120, 140, 150, 180, 210, 300, 330, 360, 1800",
    interval_seconds: 60,
    target_category: "",
    reserve_units_per_post: 0,
    is_simulation: false,
  });

  // Channel Form
  const [channelForm, setChannelForm] = useState({
    channel_id: "",
    channel_title: "",
    channel_username: "",
  });

  // Preview State
  const [previewTemplate, setPreviewTemplate] = useState("verified_transaction");
  const [previewData, setPreviewData] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    loadAll();
  }, []);

  const loadAll = async () => {
    setLoading(true);
    try {
      await Promise.all([
        loadMetrics(),
        loadChannel(),
        loadCampaigns(),
        loadReserved(),
        loadProtected(),
        loadLogs(),
      ]);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const loadMetrics = async () => {
    try {
      const res = await api.get("/admin/channel-automation/metrics");
      setMetrics(res.data);
    } catch (err) {}
  };

  const loadChannel = async () => {
    try {
      const res = await api.get("/admin/channel-automation/channel");
      setChannel(res.data);
      if (res.data) {
        setChannelForm({
          channel_id: res.data.channel_id || "",
          channel_title: res.data.channel_title || "",
          channel_username: res.data.channel_username || "",
        });
      }
    } catch (err) {}
  };

  const loadCampaigns = async () => {
    try {
      const res = await api.get("/admin/channel-automation/campaigns");
      setCampaigns(res.data.campaigns || []);
    } catch (err) {}
  };

  const loadReserved = async () => {
    try {
      const res = await api.get("/admin/channel-automation/inventory/reserved");
      setReservedList(res.data.reserved_products || []);
    } catch (err) {}
  };

  const loadProtected = async () => {
    try {
      const res = await api.get("/admin/channel-automation/protected-products");
      setProtectedProducts(res.data.protected_products || []);
    } catch (err) {}
  };

  const loadLogs = async () => {
    try {
      const res = await api.get("/admin/channel-automation/logs?limit=50");
      setActivityLogs(res.data.logs || []);
    } catch (err) {}
  };

  const loadPreview = async (tmpl) => {
    setPreviewLoading(true);
    try {
      const res = await api.get(`/admin/channel-automation/preview?template_type=${tmpl}`);
      setPreviewData(res.data);
    } catch (err) {
      toast.error("Gagal memuat preview template.");
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleConnectChannel = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/admin/channel-automation/channel/connect", channelForm);
      toast.success("Channel berhasil dihubungkan & disimpan.");
      await loadChannel();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  const handleValidateChannel = async () => {
    setLoading(true);
    try {
      const res = await api.post("/admin/channel-automation/channel/validate");
      if (res.data.success) {
        toast.success("Bot terverifikasi sebagai Administrator channel!");
      } else {
        toast.error("Bot belum memiliki izin Administrator di channel.");
      }
      await loadChannel();
    } catch (err) {
      toast.error("Gagal melakukan validasi channel.");
    } finally {
      setLoading(false);
    }
  };

  const handleSendTestMessage = async () => {
    if (!window.confirm("Kirim Test Message berlabel SIMULASI ke channel sekarang?")) return;
    setLoading(true);
    try {
      const res = await api.post("/admin/channel-automation/channel/test-message");
      if (res.data.success) {
        toast.success("Pesan uji coba (Test Message) terkirim ke channel!");
      } else {
        toast.error("Pengiriman test message gagal.");
      }
      await loadMetrics();
      await loadChannel();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  const handleCreateCampaign = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const seqArr = newCampaign.sequence_seconds
        .split(",")
        .map((s) => parseInt(s.trim()))
        .filter((n) => !isNaN(n));
      const poolArr = newCampaign.interval_pool_seconds
        .split(",")
        .map((s) => parseInt(s.trim()))
        .filter((n) => !isNaN(n));

      const payload = {
        name: newCampaign.name,
        channel_id: newCampaign.channel_id || channel?.channel_id,
        schedule_mode: newCampaign.schedule_mode,
        sequence_seconds: seqArr.length > 0 ? seqArr : [180, 120, 180, 360, 300, 330],
        interval_pool_seconds: poolArr.length > 0 ? poolArr : [30, 60, 90, 120, 180],
        interval_seconds: parseInt(newCampaign.interval_seconds) || 60,
        target_category: newCampaign.target_category || null,
        reserve_units_per_post: parseInt(newCampaign.reserve_units_per_post) || 0,
        is_simulation: Boolean(newCampaign.is_simulation),
      };

      await api.post("/admin/channel-automation/campaigns", payload);
      toast.success("Campaign berhasil dibuat!");
      setShowCreateModal(false);
      await loadCampaigns();
      await loadMetrics();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  const handleCampaignAction = async (cid, action) => {
    setLoading(true);
    try {
      await api.post(`/admin/channel-automation/campaigns/${cid}/${action}`);
      toast.success(`Campaign di-${action}.`);
      await loadCampaigns();
      await loadMetrics();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteCampaign = async (cid) => {
    if (!window.confirm("Hapus campaign ini secara permanen?")) return;
    setLoading(true);
    try {
      await api.delete(`/admin/channel-automation/campaigns/${cid}`);
      toast.success("Campaign berhasil dihapus.");
      await loadCampaigns();
      await loadMetrics();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  const handleOpenRestoreModal = (prod) => {
    setSelectedProductForRestore(prod);
    setRestoreMode("all");
    setRestoreQty(prod.reserved_count);
    setShowRestoreModal(true);
  };

  const handleExecuteRestore = async (e) => {
    e.preventDefault();
    if (!selectedProductForRestore) return;
    const confirmMsg =
      restoreMode === "all"
        ? `Restore SEMUA (${selectedProductForRestore.reserved_count}) unit ${selectedProductForRestore.product_name} ke AVAILABLE?`
        : `Restore ${restoreQty} unit ${selectedProductForRestore.product_name} ke AVAILABLE?`;
    if (!window.confirm(confirmMsg)) return;

    setLoading(true);
    try {
      const res = await api.post("/admin/channel-automation/inventory/restore", {
        product_id: selectedProductForRestore.product_id,
        mode: restoreMode,
        quantity: restoreMode === "partial" ? parseInt(restoreQty) : null,
      });
      toast.success(`Berhasil merestore ${res.data.restored_count} unit inventory!`);
      setShowRestoreModal(false);
      await loadReserved();
      await loadMetrics();
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-7xl mx-auto">
      {/* COMMAND CENTER HEADER */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-slate-900 via-slate-900/95 to-slate-950 border border-slate-800/80 p-6 shadow-xl">
        <div className="absolute top-0 right-0 -mr-16 -mt-16 w-64 h-64 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 relative z-10">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-inner">
              <Radio className="w-6 h-6 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-2xl font-bold tracking-tight text-white">
                  Channel Automation
                </h1>
                <span className="px-2.5 py-0.5 text-[11px] font-semibold tracking-wider uppercase bg-cyan-500/15 text-cyan-400 border border-cyan-500/30 rounded-full">
                  Live Engine
                </span>
              </div>
              <p className="text-slate-400 text-xs sm:text-sm mt-0.5">
                Otomasi siaran Telegram Channel, rich table rendering, dan manajemen reservasi inventory.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2.5 self-stretch md:self-auto">
            <button
              onClick={loadAll}
              disabled={loading}
              className="flex-1 md:flex-none flex items-center justify-center gap-2 px-4 py-2.5 bg-slate-800/80 hover:bg-slate-700/80 border border-slate-700/60 text-slate-200 rounded-xl text-xs font-medium transition shadow-sm"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin text-cyan-400" : ""}`} />
              Segarkan Data
            </button>
            <button
              onClick={() => {
                setNewCampaign((prev) => ({
                  ...prev,
                  channel_id: channel?.channel_id || "",
                }));
                setShowCreateModal(true);
              }}
              className="flex-1 md:flex-none flex items-center justify-center gap-2 px-4 py-2.5 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-semibold rounded-xl text-xs transition shadow-lg shadow-cyan-600/20"
            >
              <Plus className="w-4 h-4 stroke-[2.5]" />
              Buat Campaign
            </button>
          </div>
        </div>
      </div>

      {/* TACTICAL METRIC CARDS */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3.5">
          <div className="bg-slate-900/70 border border-slate-800/80 p-4 rounded-xl shadow-sm relative overflow-hidden group hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs">
              <span className="font-medium">Campaign</span>
              <Zap className="w-3.5 h-3.5 text-cyan-400" />
            </div>
            <div className="text-xl font-bold font-mono text-white mt-2">
              <span className="text-emerald-400">{metrics.running_campaigns}</span>
              <span className="text-slate-500 text-sm font-normal"> / {metrics.total_campaigns}</span>
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">Aktif / Total</span>
          </div>

          <div className="bg-slate-900/70 border border-slate-800/80 p-4 rounded-xl shadow-sm relative overflow-hidden group hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs">
              <span className="font-medium">Terkirim</span>
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            </div>
            <div className="text-xl font-bold font-mono text-emerald-400 mt-2">
              {metrics.messages_sent.toLocaleString("id-ID")}
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">Total Pesan Sukses</span>
          </div>

          <div className="bg-slate-900/70 border border-slate-800/80 p-4 rounded-xl shadow-sm relative overflow-hidden group hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs">
              <span className="font-medium">Gagal</span>
              <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
            </div>
            <div className="text-xl font-bold font-mono text-rose-400 mt-2">
              {metrics.failed_messages}
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">Tingkat Kegagalan</span>
          </div>

          <div className="bg-slate-900/70 border border-slate-800/80 p-4 rounded-xl shadow-sm relative overflow-hidden group hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs">
              <span className="font-medium">Produk Eligible</span>
              <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            </div>
            <div className="text-xl font-bold font-mono text-cyan-300 mt-2">
              {metrics.eligible_products}
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">Stok Tersedia</span>
          </div>

          <div className="bg-slate-900/70 border border-slate-800/80 p-4 rounded-xl shadow-sm relative overflow-hidden group hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs">
              <span className="font-medium">Stok Reserved</span>
              <Layers className="w-3.5 h-3.5 text-amber-400" />
            </div>
            <div className="text-xl font-bold font-mono text-amber-400 mt-2">
              {metrics.reserved_stock}
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">Channel Held Stock</span>
          </div>

          <div className="bg-slate-900/70 border border-slate-800/80 p-4 rounded-xl shadow-sm relative overflow-hidden group hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs">
              <span className="font-medium">Protected</span>
              <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
            </div>
            <div className="text-xl font-bold font-mono text-rose-400 mt-2">
              {metrics.protected_products_excluded}
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">Eksklusi Permanen</span>
          </div>

          <div className="bg-slate-900/70 border border-slate-800/80 p-4 rounded-xl shadow-sm relative overflow-hidden group hover:border-slate-700 transition">
            <div className="flex items-center justify-between text-slate-400 text-xs">
              <span className="font-medium">Jadwal Next Run</span>
              <Clock className="w-3.5 h-3.5 text-slate-400" />
            </div>
            <div className="text-xs font-bold font-mono text-slate-200 mt-3 truncate">
              {metrics.next_run ? fmtDate(metrics.next_run) : "Standby"}
            </div>
            <span className="text-[10px] text-slate-500 mt-1 block">Execution Queue</span>
          </div>
        </div>
      )}

      {/* MODERN SEGMENTED TABS */}
      <div className="border-b border-slate-800 flex overflow-x-auto gap-1">
        {[
          { id: "campaigns", label: "Campaign Manager" },
          { id: "restore", label: "Reserved Inventory" },
          { id: "channel", label: "Channel Connection" },
          { id: "preview", label: "Live Table Preview" },
          { id: "protected", label: "Protected Products" },
          { id: "logs", label: "Audit Trail" },
        ].map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id);
                if (tab.id === "preview") loadPreview(previewTemplate);
              }}
              className={`px-4 py-3 text-xs sm:text-sm font-semibold tracking-wide whitespace-nowrap border-b-2 transition duration-150 ${
                isActive
                  ? "border-cyan-400 text-cyan-400 bg-cyan-500/5"
                  : "border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* TAB 1: CAMPAIGN MANAGER */}
      {activeTab === "campaigns" && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <div>
              <h2 className="text-base font-semibold text-white">Daftar Campaign Aktif & Terjadwal</h2>
              <p className="text-xs text-slate-400">Kelola siklus posting otomatis ke Telegram Channel.</p>
            </div>
          </div>

          <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs sm:text-sm text-slate-300">
                <thead className="bg-slate-950 text-slate-400 text-[11px] uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th className="p-3.5 font-semibold">Campaign</th>
                    <th className="p-3.5 font-semibold">Target Channel</th>
                    <th className="p-3.5 font-semibold">Status</th>
                    <th className="p-3.5 font-semibold">Mode Penjadwalan</th>
                    <th className="p-3.5 font-semibold">Sent / Fail</th>
                    <th className="p-3.5 font-semibold">Next Run</th>
                    <th className="p-3.5 font-semibold text-right">Aksi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono text-xs">
                  {campaigns.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="p-10 text-center text-slate-500 font-sans">
                        <Radio className="w-8 h-8 mx-auto mb-2 opacity-30" />
                        Belum ada campaign otomasi channel. Klik <b>Buat Campaign</b> di atas.
                      </td>
                    </tr>
                  ) : (
                    campaigns.map((c) => (
                      <tr key={c._id} className="hover:bg-slate-800/40 transition">
                        <td className="p-3.5 font-sans font-medium text-white">
                          <div className="flex items-center gap-2">
                            <span>{c.name}</span>
                            {c.is_simulation && (
                              <span className="px-1.5 py-0.5 text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/30 rounded">
                                SIMULASI
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="p-3.5 text-slate-400">
                          {c.channel_id}
                        </td>
                        <td className="p-3.5">
                          <span
                            className={`px-2 py-0.5 text-[11px] rounded-md font-semibold tracking-wide ${
                              c.status === "RUNNING"
                                ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                                : c.status === "PAUSED"
                                ? "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                                : "bg-slate-800 text-slate-400 border border-slate-700"
                            }`}
                          >
                            {c.status}
                          </span>
                        </td>
                        <td className="p-3.5 text-slate-400 font-sans text-xs">
                          {c.schedule_mode === "custom_sequence"
                            ? "Custom Sequence"
                            : c.schedule_mode === "random_pool"
                            ? "Randomized Pool"
                            : "Fixed Interval"}
                        </td>
                        <td className="p-3.5">
                          <span className="text-emerald-400">{c.messages_sent || 0}</span>
                          <span className="text-slate-600 mx-1">/</span>
                          <span className="text-rose-400">{c.failed_messages || 0}</span>
                        </td>
                        <td className="p-3.5 text-slate-400">
                          {c.next_run_at ? fmtDate(c.next_run_at) : "—"}
                        </td>
                        <td className="p-3.5 text-right space-x-1.5">
                          {c.status === "RUNNING" ? (
                            <button
                              onClick={() => handleCampaignAction(c._id, "pause")}
                              title="Jeda Campaign"
                              className="p-1.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-lg transition"
                            >
                              <Pause className="w-3.5 h-3.5" />
                            </button>
                          ) : (
                            <button
                              onClick={() => handleCampaignAction(c._id, "start")}
                              title="Jalankan Campaign"
                              className="p-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 rounded-lg transition"
                            >
                              <Play className="w-3.5 h-3.5" />
                            </button>
                          )}
                          <button
                            onClick={() => handleCampaignAction(c._id, "stop")}
                            title="Hentikan"
                            className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-lg transition"
                          >
                            <Square className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleDeleteCampaign(c._id)}
                            title="Hapus"
                            className="p-1.5 bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 rounded-lg transition"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: RESERVED INVENTORY (RESTORE) */}
      {activeTab === "restore" && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
            <div>
              <h2 className="text-base font-semibold text-white">Reserved Inventory Management</h2>
              <p className="text-xs text-slate-400">
                Unit inventory yang berstatus <code>RESERVED_CHANNEL</code> tidak dapat dibeli pelanggan sampai dipulihkan ke <code>AVAILABLE</code>.
              </p>
            </div>
          </div>

          <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-left text-xs sm:text-sm text-slate-300">
              <thead className="bg-slate-950 text-slate-400 text-[11px] uppercase tracking-wider border-b border-slate-800">
                <tr>
                  <th className="p-3.5 font-semibold">Produk</th>
                  <th className="p-3.5 font-semibold">SKU</th>
                  <th className="p-3.5 font-semibold">Stok Reserved</th>
                  <th className="p-3.5 font-semibold text-right">Tindakan</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-xs">
                {reservedList.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="p-10 text-center text-slate-500">
                      <CheckCircle2 className="w-8 h-8 mx-auto mb-2 opacity-30 text-emerald-400" />
                      Tidak ada inventory yang berstatus RESERVED_CHANNEL saat ini. Semua stok normal.
                    </td>
                  </tr>
                ) : (
                  reservedList.map((item) => (
                    <tr key={item.product_id} className="hover:bg-slate-800/40 transition">
                      <td className="p-3.5 font-medium text-white">{item.product_name}</td>
                      <td className="p-3.5 font-mono text-slate-400">{item.sku}</td>
                      <td className="p-3.5">
                        <span className="px-2 py-0.5 rounded font-mono font-bold bg-amber-500/15 text-amber-400 border border-amber-500/30">
                          {item.reserved_count} Unit
                        </span>
                      </td>
                      <td className="p-3.5 text-right">
                        <button
                          onClick={() => handleOpenRestoreModal(item)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-semibold rounded-lg text-xs transition shadow-sm"
                        >
                          <RotateCcw className="w-3.5 h-3.5" />
                          Restore Stok
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 3: CHANNEL CONNECTION */}
      {activeTab === "channel" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-white">Koneksi Telegram Channel</h2>
              <p className="text-xs text-slate-400">
                Konfigurasikan channel target untuk menerima siaran berkala dan notifikasi transaksi.
              </p>
            </div>

            <form
              onSubmit={handleConnectChannel}
              className="bg-slate-900/80 border border-slate-800 p-6 rounded-xl space-y-4 shadow-sm"
            >
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Telegram Channel ID (Contoh: -1004464466918)
                </label>
                <input
                  type="text"
                  required
                  value={channelForm.channel_id}
                  onChange={(e) =>
                    setChannelForm({ ...channelForm, channel_id: e.target.value })
                  }
                  placeholder="-100..."
                  className={inputCls}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    Judul Channel (Opsional)
                  </label>
                  <input
                    type="text"
                    value={channelForm.channel_title}
                    onChange={(e) =>
                      setChannelForm({ ...channelForm, channel_title: e.target.value })
                    }
                    placeholder="IDSE Store Official"
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    Username Channel (Opsional)
                  </label>
                  <input
                    type="text"
                    value={channelForm.channel_username}
                    onChange={(e) =>
                      setChannelForm({
                        ...channelForm,
                        channel_username: e.target.value,
                      })
                    }
                    placeholder="idsestore"
                    className={inputCls}
                  />
                </div>
              </div>

              <div className="pt-2 flex flex-wrap gap-2.5">
                <button
                  type="submit"
                  disabled={loading}
                  className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-semibold rounded-lg text-xs transition shadow-sm"
                >
                  Simpan & Hubungkan
                </button>
                <button
                  type="button"
                  onClick={handleValidateChannel}
                  disabled={loading}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 rounded-lg text-xs font-medium transition"
                >
                  Validasi Hak Administrator Bot
                </button>
                <button
                  type="button"
                  onClick={handleSendTestMessage}
                  disabled={loading}
                  className="px-4 py-2 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
                >
                  <Send className="w-3.5 h-3.5" />
                  Kirim Uji Coba (SIMULASI)
                </button>
              </div>
            </form>
          </div>

          <div className="space-y-4">
            <div>
              <h2 className="text-base font-semibold text-white">Status Koneksi Aktif</h2>
              <p className="text-xs text-slate-400">Verifikasi status izin API bot di channel.</p>
            </div>

            {channel && (
              <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-xl space-y-3.5 text-xs text-slate-300 shadow-sm">
                <div className="flex justify-between items-center pb-2 border-b border-slate-800">
                  <span className="text-slate-400">Koneksi:</span>
                  <span className="font-semibold px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 uppercase tracking-wider text-[10px]">
                    {channel.connection_status}
                  </span>
                </div>
                <div className="flex justify-between items-center pb-2 border-b border-slate-800">
                  <span className="text-slate-400">Izin Bot:</span>
                  <span className="font-semibold text-cyan-400">
                    {channel.bot_permission_status}
                  </span>
                </div>
                <div className="flex justify-between items-center pb-2 border-b border-slate-800">
                  <span className="text-slate-400">Channel ID:</span>
                  <span className="font-mono text-slate-200">{channel.channel_id || "—"}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-400">Terakhir Kirim:</span>
                  <span className="font-mono text-slate-300">
                    {channel.last_successful_send ? fmtDate(channel.last_successful_send) : "—"}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 4: MESSAGE PREVIEW & FORMAT */}
      {activeTab === "preview" && (
        <div className="space-y-6 max-w-4xl">
          <div>
            <h2 className="text-base font-semibold text-white">Preview & Format Telegram Rich Table</h2>
            <p className="text-xs text-slate-400">
              Format native Telegram rich table dengan border, hyperlink produk biru, dan privacy masking.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {[
              { id: "verified_transaction", label: "A. Verified Transaction" },
              { id: "promo", label: "B. Scheduled Product Promo" },
              { id: "simulation", label: "C. Testing & Simulation" },
            ].map((tmpl) => (
              <button
                key={tmpl.id}
                onClick={() => {
                  setPreviewTemplate(tmpl.id);
                  loadPreview(tmpl.id);
                }}
                className={`px-3.5 py-2 text-xs font-semibold rounded-lg transition ${
                  previewTemplate === tmpl.id
                    ? "bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20"
                    : "bg-slate-800/80 text-slate-300 hover:bg-slate-700"
                }`}
              >
                {tmpl.label}
              </button>
            ))}
          </div>

          {previewData && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-xl space-y-3 shadow-sm">
                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block">
                  Simulasi Render Telegram Bubble
                </span>
                <div
                  className="p-4 bg-slate-950 rounded-lg text-slate-200 text-xs sm:text-sm border border-slate-800 shadow-inner"
                  dangerouslySetInnerHTML={{ __html: previewData.html }}
                />
              </div>

              {previewData.nominal_breakdown && (
                <div className="bg-slate-900/80 border border-slate-800 p-5 rounded-xl space-y-4 shadow-sm text-xs">
                  <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block">
                    Kalkulasi Nominal Transaksi
                  </span>
                  <div className="p-3 bg-slate-950 rounded-lg border border-slate-800/80 font-mono text-slate-300 space-y-1.5">
                    <div className="text-slate-400 text-[11px]">
                      FINAL = BASE_PRICE + FEE_0_7_PERCENT + ADMIN_FEE + UNIQUE_SEQUENCE
                    </div>
                    <div className="pt-2 text-sm">
                      Rp{previewData.nominal_breakdown.base_price.toLocaleString("id-ID")} (Base) + 
                      Rp{previewData.nominal_breakdown.fee_0_7_percent.toLocaleString("id-ID")} (0,7%) + 
                      Rp{previewData.nominal_breakdown.admin_fee} (Admin) + 
                      Rp{previewData.nominal_breakdown.unique_sequence} (Kode Unik)
                    </div>
                    <div className="pt-2 border-t border-slate-800 text-base font-bold text-emerald-400">
                      Total Tagihan: {previewData.nominal_breakdown.formatted_final}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* TAB 5: PROTECTED PRODUCTS */}
      {activeTab === "protected" && (
        <div className="space-y-4 max-w-4xl">
          <div className="p-4 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-start gap-3">
            <ShieldAlert className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="text-rose-300 font-semibold text-xs sm:text-sm">
                Permanent Protected Products Isolation
              </h3>
              <p className="text-xs text-rose-400/80 mt-1 leading-relaxed">
                Produk-produk berikut <b>secara mutlak dilindungi</b> dan dilarang diproses oleh seluruh fitur Channel Automation (pemilihan berkala, reservasi inventory, pemotongan stok, maupun perubahan harga).
              </p>
            </div>
          </div>

          <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-left text-xs sm:text-sm text-slate-300">
              <thead className="bg-slate-950 text-slate-400 text-[11px] uppercase tracking-wider border-b border-slate-800">
                <tr>
                  <th className="p-3.5 font-semibold">Nama Produk</th>
                  <th className="p-3.5 font-semibold">Product ID</th>
                  <th className="p-3.5 font-semibold">SKU</th>
                  <th className="p-3.5 font-semibold">Status Kebijakan</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-xs">
                {protectedProducts.map((p) => (
                  <tr key={p.product_id} className="hover:bg-slate-800/40 transition">
                    <td className="p-3.5 font-medium text-white">{p.name}</td>
                    <td className="p-3.5 font-mono text-slate-400 text-[11px]">{p.product_id}</td>
                    <td className="p-3.5 font-mono text-slate-400">{p.sku}</td>
                    <td className="p-3.5">
                      <span className="px-2 py-0.5 text-[10px] rounded font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30 uppercase tracking-wider">
                        PERMANENT EXCLUSION
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 6: AUDIT TRAIL */}
      {activeTab === "logs" && (
        <div className="space-y-4">
          <div>
            <h2 className="text-base font-semibold text-white">Audit Trail & Activity Logs</h2>
            <p className="text-xs text-slate-400">Riwayat eksekusi scheduler, reservasi, dan tindakan admin.</p>
          </div>

          <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-950 text-slate-400 text-[11px] uppercase tracking-wider border-b border-slate-800">
                <tr>
                  <th className="p-3 font-semibold">Waktu</th>
                  <th className="p-3 font-semibold">Aksi</th>
                  <th className="p-3 font-semibold">Aktor</th>
                  <th className="p-3 font-semibold">Detail Parameter</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono text-[11px]">
                {activityLogs.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="p-8 text-center text-slate-500 font-sans">
                      Belum ada catatan aktivitas.
                    </td>
                  </tr>
                ) : (
                  activityLogs.map((log) => (
                    <tr key={log._id} className="hover:bg-slate-800/40 transition">
                      <td className="p-3 text-slate-400 whitespace-nowrap">{fmtDate(log.created_at)}</td>
                      <td className="p-3 font-bold text-cyan-400">{log.action}</td>
                      <td className="p-3 text-slate-300">{log.actor}</td>
                      <td className="p-3 text-slate-400 max-w-md truncate">{JSON.stringify(log.details)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* MODAL CREATE CAMPAIGN */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-xl w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto shadow-2xl">
            <div className="flex justify-between items-center pb-2 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <Radio className="w-5 h-5 text-cyan-400" />
                Buat Campaign Baru
              </h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateCampaign} className="space-y-4 text-xs">
              <div>
                <label className="block font-semibold text-slate-300 mb-1">
                  Nama Campaign
                </label>
                <input
                  type="text"
                  required
                  value={newCampaign.name}
                  onChange={(e) =>
                    setNewCampaign({ ...newCampaign, name: e.target.value })
                  }
                  placeholder="Promo Sore Hari"
                  className={inputCls}
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-300 mb-1">
                  Target Channel ID
                </label>
                <input
                  type="text"
                  required
                  value={newCampaign.channel_id}
                  onChange={(e) =>
                    setNewCampaign({ ...newCampaign, channel_id: e.target.value })
                  }
                  placeholder="-100..."
                  className={inputCls}
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-300 mb-1">
                  Mode Runtime Penjadwalan
                </label>
                <select
                  value={newCampaign.schedule_mode}
                  onChange={(e) =>
                    setNewCampaign({ ...newCampaign, schedule_mode: e.target.value })
                  }
                  className={inputCls}
                >
                  <option value="custom_sequence">Mode A / B: Custom Sequence (Detik)</option>
                  <option value="random_pool">Mode C: Randomized Sequence dari Pool</option>
                  <option value="fixed">Interval Tetap (Detik)</option>
                </select>
              </div>

              {newCampaign.schedule_mode === "custom_sequence" && (
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">
                    Sequence Detik (Koma sebagai pemisah)
                  </label>
                  <input
                    type="text"
                    value={newCampaign.sequence_seconds}
                    onChange={(e) =>
                      setNewCampaign({
                        ...newCampaign,
                        sequence_seconds: e.target.value,
                      })
                    }
                    placeholder="180, 120, 180, 360, 300, 330"
                    className={inputCls}
                  />
                  <span className="text-[10px] text-slate-500 mt-1 block">
                    Misal: 180 (3m), 120 (2m), 360 (6m), 330 (5.5m).
                  </span>
                </div>
              )}

              {newCampaign.schedule_mode === "random_pool" && (
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">
                    Pool Interval Detik (Koma sebagai pemisah)
                  </label>
                  <input
                    type="text"
                    value={newCampaign.interval_pool_seconds}
                    onChange={(e) =>
                      setNewCampaign({
                        ...newCampaign,
                        interval_pool_seconds: e.target.value,
                      })
                    }
                    placeholder="30, 60, 90, 120, 180, 300, 360"
                    className={inputCls}
                  />
                </div>
              )}

              <div>
                <label className="block font-semibold text-slate-300 mb-1">
                  Reservasi Stok per Post (0 jika tanpa reservasi stok)
                </label>
                <input
                  type="number"
                  min="0"
                  value={newCampaign.reserve_units_per_post}
                  onChange={(e) =>
                    setNewCampaign({
                      ...newCampaign,
                      reserve_units_per_post: e.target.value,
                    })
                  }
                  className={inputCls}
                />
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="modal_is_sim"
                  checked={newCampaign.is_simulation}
                  onChange={(e) =>
                    setNewCampaign({
                      ...newCampaign,
                      is_simulation: e.target.checked,
                    })
                  }
                  className="rounded bg-slate-950 border-slate-800 text-cyan-500"
                />
                <label htmlFor="modal_is_sim" className="text-slate-300 cursor-pointer">
                  Mode Simulasi / Uji Coba (Pesan berlabel SIMULASI, tanpa reservasi nyata)
                </label>
              </div>

              <div className="pt-3 flex justify-end gap-2.5 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs"
                >
                  Batal
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold rounded-lg text-xs transition"
                >
                  Simpan Campaign
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL RESTORE INVENTORY */}
      {showRestoreModal && selectedProductForRestore && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex justify-between items-center pb-2 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <RotateCcw className="w-5 h-5 text-cyan-400" />
                Restore Reserved Stok
              </h3>
              <button
                onClick={() => setShowRestoreModal(false)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="p-3.5 bg-slate-950 rounded-xl border border-slate-800 text-xs space-y-1 text-slate-300">
              <div>Produk: <b className="text-white">{selectedProductForRestore.product_name}</b></div>
              <div>
                Total Reserved: <b className="text-amber-400 font-mono">{selectedProductForRestore.reserved_count} Unit</b>
              </div>
            </div>

            <form onSubmit={handleExecuteRestore} className="space-y-4 text-xs">
              <div className="space-y-2">
                <label className="block font-semibold text-slate-300">
                  Pilih Metode Restore:
                </label>
                <div className="space-y-2">
                  <label className="flex items-center gap-2.5 p-3 rounded-lg border border-slate-800 bg-slate-950/50 cursor-pointer hover:border-slate-700 transition">
                    <input
                      type="radio"
                      name="restore_mode"
                      value="all"
                      checked={restoreMode === "all"}
                      onChange={() => setRestoreMode("all")}
                      className="text-cyan-500"
                    />
                    <div>
                      <b className="text-white">A. Restore All</b>
                      <p className="text-[11px] text-slate-400">
                        Kembalikan semua ({selectedProductForRestore.reserved_count}) unit ke status AVAILABLE.
                      </p>
                    </div>
                  </label>

                  <label className="flex items-center gap-2.5 p-3 rounded-lg border border-slate-800 bg-slate-950/50 cursor-pointer hover:border-slate-700 transition">
                    <input
                      type="radio"
                      name="restore_mode"
                      value="partial"
                      checked={restoreMode === "partial"}
                      onChange={() => setRestoreMode("partial")}
                      className="text-cyan-500"
                    />
                    <div>
                      <b className="text-white">B. Restore Partial</b>
                      <p className="text-[11px] text-slate-400">
                        Tentukan jumlah kuantitas tertentu untuk dikembalikan.
                      </p>
                    </div>
                  </label>
                </div>
              </div>

              {restoreMode === "partial" && (
                <div>
                  <label className="block font-semibold text-slate-300 mb-1">
                    Kuantitas Restore (Maksimal {selectedProductForRestore.reserved_count})
                  </label>
                  <input
                    type="number"
                    min="1"
                    max={selectedProductForRestore.reserved_count}
                    value={restoreQty}
                    onChange={(e) => setRestoreQty(e.target.value)}
                    className={inputCls}
                  />
                </div>
              )}

              <div className="pt-3 flex justify-end gap-2.5 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowRestoreModal(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs"
                >
                  Batal
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-slate-950 font-bold rounded-lg text-xs transition"
                >
                  Konfirmasi Restore
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
