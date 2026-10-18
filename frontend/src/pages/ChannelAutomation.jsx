import React, { useState, useEffect } from "react";
import api, { fmtIDR, fmtDate, formatApiErrorDetail } from "../lib/api";
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
} from "lucide-react";

export default function ChannelAutomation() {
  const [activeTab, setActiveTab] = useState("campaigns"); // campaigns, restore, channel, logs, preview, protected
  const [metrics, setMetrics] = useState(null);
  const [channel, setChannel] = useState(null);
  const [campaigns, setCampaigns] = useState([]);
  const [reservedList, setReservedList] = useState([]);
  const [protectedProducts, setProtectedProducts] = useState([]);
  const [activityLogs, setActivityLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(null);

  // Form states
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
    try {
      const res = await api.get(`/admin/channel-automation/preview?template_type=${tmpl}`);
      setPreviewData(res.data);
    } catch (err) {
      setMessage({ type: "error", text: "Gagal memuat preview" });
    }
  };

  const handleConnectChannel = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/admin/channel-automation/channel/connect", channelForm);
      setMessage({ type: "success", text: "Channel berhasil dihubungkan & disimpan." });
      await loadChannel();
    } catch (err) {
      setMessage({ type: "error", text: formatApiErrorDetail(err.response?.data?.detail) });
    } finally {
      setLoading(false);
    }
  };

  const handleValidateChannel = async () => {
    setLoading(true);
    try {
      const res = await api.post("/admin/channel-automation/channel/validate");
      if (res.data.success) {
        setMessage({ type: "success", text: "Bot memiliki izin admin di channel!" });
      } else {
        setMessage({ type: "error", text: "Validasi gagal: bot belum menjadi admin di channel." });
      }
      await loadChannel();
    } catch (err) {
      setMessage({ type: "error", text: "Gagal validasi channel." });
    } finally {
      setLoading(false);
    }
  };

  const handleSendTestMessage = async () => {
    if (!window.confirm("Kirim Test Message berlabel SIMULASI ke channel?")) return;
    setLoading(true);
    try {
      const res = await api.post("/admin/channel-automation/channel/test-message");
      if (res.data.success) {
        setMessage({ type: "success", text: "Test Message berhasil terkirim ke channel!" });
      } else {
        setMessage({ type: "error", text: "Gagal mengirim test message." });
      }
      await loadMetrics();
      await loadChannel();
    } catch (err) {
      setMessage({ type: "error", text: formatApiErrorDetail(err.response?.data?.detail) });
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
      setMessage({ type: "success", text: "Campaign berhasil dibuat!" });
      setShowCreateModal(false);
      await loadCampaigns();
      await loadMetrics();
    } catch (err) {
      setMessage({ type: "error", text: formatApiErrorDetail(err.response?.data?.detail) });
    } finally {
      setLoading(false);
    }
  };

  const handleCampaignAction = async (cid, action) => {
    setLoading(true);
    try {
      await api.post(`/admin/channel-automation/campaigns/${cid}/${action}`);
      setMessage({ type: "success", text: `Campaign berhasil di-${action}!` });
      await loadCampaigns();
      await loadMetrics();
    } catch (err) {
      setMessage({ type: "error", text: formatApiErrorDetail(err.response?.data?.detail) });
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteCampaign = async (cid) => {
    if (!window.confirm("Hapus campaign ini?")) return;
    setLoading(true);
    try {
      await api.delete(`/admin/channel-automation/campaigns/${cid}`);
      setMessage({ type: "success", text: "Campaign dihapus." });
      await loadCampaigns();
      await loadMetrics();
    } catch (err) {
      setMessage({ type: "error", text: formatApiErrorDetail(err.response?.data?.detail) });
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
        ? `Yakin ingin merestore SEMUA (${selectedProductForRestore.reserved_count}) unit ${selectedProductForRestore.product_name} kembali ke AVAILABLE?`
        : `Yakin ingin merestore ${restoreQty} unit ${selectedProductForRestore.product_name} kembali ke AVAILABLE?`;
    if (!window.confirm(confirmMsg)) return;

    setLoading(true);
    try {
      const res = await api.post("/admin/channel-automation/inventory/restore", {
        product_id: selectedProductForRestore.product_id,
        mode: restoreMode,
        quantity: restoreMode === "partial" ? parseInt(restoreQty) : null,
      });
      setMessage({
        type: "success",
        text: `Berhasil merestore ${res.data.restored_count} unit inventory!`,
      });
      setShowRestoreModal(false);
      await loadReserved();
      await loadMetrics();
    } catch (err) {
      setMessage({ type: "error", text: formatApiErrorDetail(err.response?.data?.detail) });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* HEADER */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-slate-900 border border-slate-800 p-6 rounded-2xl">
        <div>
          <div className="flex items-center gap-3">
            <Radio className="w-8 h-8 text-blue-500 animate-pulse" />
            <h1 className="text-2xl font-bold text-white tracking-wide">
              Channel Automation
            </h1>
          </div>
          <p className="text-slate-400 text-sm mt-1">
            Modul Otomasi Siaran Telegram Channel & Manajemen Reservasi Stok
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadAll}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-sm transition"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* ALERT NOTIFICATION */}
      {message && (
        <div
          className={`p-4 rounded-xl flex items-center justify-between ${
            message.type === "success"
              ? "bg-emerald-950/60 border border-emerald-500/40 text-emerald-300"
              : "bg-red-950/60 border border-red-500/40 text-red-300"
          }`}
        >
          <div className="flex items-center gap-3">
            {message.type === "success" ? (
              <CheckCircle className="w-5 h-5 text-emerald-400" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-red-400" />
            )}
            <span className="text-sm font-medium">{message.text}</span>
          </div>
          <button
            onClick={() => setMessage(null)}
            className="text-xs opacity-70 hover:opacity-100"
          >
            ✕
          </button>
        </div>
      )}

      {/* METRICS DASHBOARD */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
          <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl">
            <span className="text-xs text-slate-400 font-medium">Campaign Aktif</span>
            <div className="text-xl font-bold text-emerald-400 mt-1">
              {metrics.running_campaigns} / {metrics.total_campaigns}
            </div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl">
            <span className="text-xs text-slate-400 font-medium">Pesan Terkirim</span>
            <div className="text-xl font-bold text-blue-400 mt-1">
              {metrics.messages_sent}
            </div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl">
            <span className="text-xs text-slate-400 font-medium">Pesan Gagal</span>
            <div className="text-xl font-bold text-amber-400 mt-1">
              {metrics.failed_messages}
            </div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl">
            <span className="text-xs text-slate-400 font-medium">Produk Eligible</span>
            <div className="text-xl font-bold text-indigo-400 mt-1">
              {metrics.eligible_products}
            </div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl">
            <span className="text-xs text-slate-400 font-medium">Stok Reserved</span>
            <div className="text-xl font-bold text-amber-500 mt-1">
              {metrics.reserved_stock}
            </div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl">
            <span className="text-xs text-slate-400 font-medium">Produk Protected</span>
            <div className="text-xl font-bold text-rose-500 mt-1">
              {metrics.protected_products_excluded} (Excl)
            </div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 p-4 rounded-xl">
            <span className="text-xs text-slate-400 font-medium">Next Run</span>
            <div className="text-xs font-semibold text-slate-300 mt-2 truncate">
              {metrics.next_run ? fmtDate(metrics.next_run) : "—"}
            </div>
          </div>
        </div>
      )}

      {/* TABS NAVIGATION */}
      <div className="flex border-b border-slate-800 space-x-2">
        {[
          { id: "campaigns", label: "Campaign Manager" },
          { id: "restore", label: "Reserved Inventory (Restore)" },
          { id: "channel", label: "Channel Connection" },
          { id: "preview", label: "Message Preview & Format" },
          { id: "protected", label: "Protected Products" },
          { id: "logs", label: "Activity Logs" },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => {
              setActiveTab(tab.id);
              if (tab.id === "preview") loadPreview(previewTemplate);
            }}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition ${
              activeTab === tab.id
                ? "border-blue-500 text-blue-400 bg-slate-800/40"
                : "border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* TAB 1: CAMPAIGN MANAGER */}
      {activeTab === "campaigns" && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="text-lg font-semibold text-white">Daftar Campaign</h2>
            <button
              onClick={() => {
                setNewCampaign((prev) => ({
                  ...prev,
                  channel_id: channel?.channel_id || "",
                }));
                setShowCreateModal(true);
              }}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition"
            >
              <Plus className="w-4 h-4" />
              Buat Campaign Baru
            </button>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-950 text-slate-400 text-xs uppercase border-b border-slate-800">
                <tr>
                  <th className="p-4">Nama Campaign</th>
                  <th className="p-4">Channel ID</th>
                  <th className="p-4">Status</th>
                  <th className="p-4">Mode Runtime</th>
                  <th className="p-4">Sent / Failed</th>
                  <th className="p-4">Next Run</th>
                  <th className="p-4 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {campaigns.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="p-8 text-center text-slate-500">
                      Belum ada campaign. Buat campaign baru untuk memulai penjadwalan.
                    </td>
                  </tr>
                ) : (
                  campaigns.map((c) => (
                    <tr key={c._id} className="hover:bg-slate-800/30">
                      <td className="p-4 font-medium text-white">
                        {c.name}
                        {c.is_simulation && (
                          <span className="ml-2 px-2 py-0.5 text-xs bg-amber-950 text-amber-400 border border-amber-800 rounded">
                            SIMULASI
                          </span>
                        )}
                      </td>
                      <td className="p-4 font-mono text-xs text-slate-400">
                        {c.channel_id}
                      </td>
                      <td className="p-4">
                        <span
                          className={`px-2.5 py-1 text-xs rounded-full font-semibold ${
                            c.status === "RUNNING"
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                              : c.status === "PAUSED"
                              ? "bg-amber-950 text-amber-400 border border-amber-800"
                              : "bg-slate-800 text-slate-400"
                          }`}
                        >
                          {c.status}
                        </span>
                      </td>
                      <td className="p-4 text-xs text-slate-400">
                        {c.schedule_mode === "custom_sequence"
                          ? "Custom Sequence"
                          : c.schedule_mode === "random_pool"
                          ? "Randomized Pool"
                          : "Fixed Interval"}
                      </td>
                      <td className="p-4 text-xs">
                        <span className="text-emerald-400">{c.messages_sent || 0}</span> /{" "}
                        <span className="text-rose-400">{c.failed_messages || 0}</span>
                      </td>
                      <td className="p-4 text-xs text-slate-400">
                        {c.next_run_at ? fmtDate(c.next_run_at) : "—"}
                      </td>
                      <td className="p-4 text-right space-x-2">
                        {c.status === "RUNNING" ? (
                          <button
                            onClick={() => handleCampaignAction(c._id, "pause")}
                            title="Pause"
                            className="p-1.5 bg-amber-900/60 hover:bg-amber-800 text-amber-300 rounded"
                          >
                            <Pause className="w-4 h-4" />
                          </button>
                        ) : (
                          <button
                            onClick={() => handleCampaignAction(c._id, "start")}
                            title="Start / Resume"
                            className="p-1.5 bg-emerald-900/60 hover:bg-emerald-800 text-emerald-300 rounded"
                          >
                            <Play className="w-4 h-4" />
                          </button>
                        )}
                        <button
                          onClick={() => handleCampaignAction(c._id, "stop")}
                          title="Stop"
                          className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded"
                        >
                          <Square className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDeleteCampaign(c._id)}
                          title="Delete"
                          className="p-1.5 bg-red-950/80 hover:bg-red-900 text-red-300 rounded"
                        >
                          <Trash2 className="w-4 h-4" />
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

      {/* TAB 2: RESERVED INVENTORY (RESTORE) */}
      {activeTab === "restore" && (
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-white">
              Reserved Inventory Management
            </h2>
            <p className="text-sm text-slate-400">
              Kelola stok yang sedang berstatus <code>RESERVED_CHANNEL</code>. Admin
              dapat melakukan Restore All atau Restore Partial per produk untuk
              mengembalikan stok menjadi AVAILABLE.
            </p>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-950 text-slate-400 text-xs uppercase border-b border-slate-800">
                <tr>
                  <th className="p-4">Produk</th>
                  <th className="p-4">SKU</th>
                  <th className="p-4">Jumlah Reserved</th>
                  <th className="p-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {reservedList.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="p-8 text-center text-slate-500">
                      Tidak ada inventory yang berstatus RESERVED_CHANNEL saat ini.
                    </td>
                  </tr>
                ) : (
                  reservedList.map((item) => (
                    <tr key={item.product_id} className="hover:bg-slate-800/30">
                      <td className="p-4 font-medium text-white">
                        {item.product_name}
                      </td>
                      <td className="p-4 font-mono text-xs text-slate-400">
                        {item.sku}
                      </td>
                      <td className="p-4">
                        <span className="px-2.5 py-1 text-xs rounded-full bg-amber-950 text-amber-400 border border-amber-800 font-semibold">
                          {item.reserved_count} Unit
                        </span>
                      </td>
                      <td className="p-4 text-right">
                        <button
                          onClick={() => handleOpenRestoreModal(item)}
                          className="flex items-center gap-1.5 ml-auto px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-medium transition"
                        >
                          <RotateCcw className="w-3.5 h-3.5" />
                          Restore
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
        <div className="space-y-6 max-w-2xl">
          <div>
            <h2 className="text-lg font-semibold text-white">
              Pengaturan Channel Telegram
            </h2>
            <p className="text-sm text-slate-400">
              Hubungkan Telegram Channel ID untuk siaran promosi dan notifikasi
              transaksi terverifikasi.
            </p>
          </div>

          <form
            onSubmit={handleConnectChannel}
            className="bg-slate-900 border border-slate-800 p-6 rounded-xl space-y-4"
          >
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Telegram Channel ID (Contoh: -1004464466918)
              </label>
              <input
                type="text"
                required
                value={channelForm.channel_id}
                onChange={(e) =>
                  setChannelForm({ ...channelForm, channel_id: e.target.value })
                }
                className="w-full px-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-sm focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Channel Title / Nama Channel
              </label>
              <input
                type="text"
                value={channelForm.channel_title}
                onChange={(e) =>
                  setChannelForm({ ...channelForm, channel_title: e.target.value })
                }
                placeholder="IDSE Store Channel"
                className="w-full px-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Channel Username (Opsional)
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
                className="w-full px-4 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="pt-2 flex flex-wrap gap-3">
              <button
                type="submit"
                disabled={loading}
                className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition"
              >
                Simpan & Hubungkan
              </button>
              <button
                type="button"
                onClick={handleValidateChannel}
                disabled={loading}
                className="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-sm font-medium transition"
              >
                Validasi Izin Bot
              </button>
              <button
                type="button"
                onClick={handleSendTestMessage}
                disabled={loading}
                className="px-4 py-2.5 bg-amber-900/60 hover:bg-amber-800 text-amber-200 rounded-lg text-sm font-medium transition flex items-center gap-1.5"
              >
                <Send className="w-3.5 h-3.5" />
                Kirim Test Message
              </button>
            </div>
          </form>

          {channel && (
            <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl text-xs space-y-2 text-slate-400">
              <div className="flex justify-between">
                <span>Status Koneksi:</span>
                <span className="font-semibold text-emerald-400">
                  {channel.connection_status}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Status Izin Admin Bot:</span>
                <span className="font-semibold text-blue-400">
                  {channel.bot_permission_status}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Terakhir Sukses Kirim:</span>
                <span>{channel.last_successful_send ? fmtDate(channel.last_successful_send) : "—"}</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 4: MESSAGE PREVIEW & FORMAT */}
      {activeTab === "preview" && (
        <div className="space-y-6 max-w-3xl">
          <div>
            <h2 className="text-lg font-semibold text-white">
              Preview Format Native Telegram Table
            </h2>
            <p className="text-sm text-slate-400">
              Menampilkan format rendering Telegram Rich Table, masking privasi,
              dan hyperlink produk.
            </p>
          </div>

          <div className="flex gap-2">
            {[
              { id: "verified_transaction", label: "A. Verified Transaction" },
              { id: "promo", label: "B. Scheduled Promotion" },
              { id: "simulation", label: "C. Testing / Simulation" },
            ].map((tmpl) => (
              <button
                key={tmpl.id}
                onClick={() => {
                  setPreviewTemplate(tmpl.id);
                  loadPreview(tmpl.id);
                }}
                className={`px-4 py-2 text-xs font-semibold rounded-lg transition ${
                  previewTemplate === tmpl.id
                    ? "bg-blue-600 text-white"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                }`}
              >
                {tmpl.label}
              </button>
            ))}
          </div>

          {previewData && (
            <div className="space-y-4">
              <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl space-y-4">
                <span className="text-xs uppercase tracking-wider text-slate-500 font-bold">
                  Simulasi Render Chat Telegram
                </span>
                <div
                  className="p-5 bg-slate-950 rounded-lg text-slate-200 text-sm leading-relaxed border border-slate-800"
                  dangerouslySetInnerHTML={{ __html: previewData.html }}
                />
              </div>

              {previewData.nominal_breakdown && (
                <div className="bg-slate-900 border border-slate-800 p-4 rounded-xl text-xs space-y-2 text-slate-400">
                  <span className="text-slate-300 font-semibold block mb-1">
                    Detail Rumus Nominal:
                  </span>
                  <div>
                    FINAL = BASE_PRICE + FEE_0_7_PERCENT + ADMIN_FEE +
                    UNIQUE_SEQUENCE
                  </div>
                  <div className="font-mono text-slate-300">
                    Rp{previewData.nominal_breakdown.base_price.toLocaleString("id-ID")}{" "}
                    + Rp{previewData.nominal_breakdown.fee_0_7_percent.toLocaleString("id-ID")}{" "}
                    + Rp{previewData.nominal_breakdown.admin_fee} + Rp
                    {previewData.nominal_breakdown.unique_sequence} ={" "}
                    <span className="text-emerald-400 font-bold">
                      {previewData.nominal_breakdown.formatted_final}
                    </span>
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
          <div className="p-4 bg-rose-950/40 border border-rose-800/40 rounded-xl flex items-start gap-3">
            <ShieldAlert className="w-6 h-6 text-rose-400 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="text-rose-300 font-semibold text-sm">
                Permanent Protected Products Exclusion
              </h3>
              <p className="text-xs text-rose-400/80 mt-1">
                Produk-produk berikut secara permanen DILARANG diproses oleh
                seluruh modul Channel Automation (pemilihan otomatis, reservasi
                stok, restore, pengurangan stock, atau promosi otomatis).
              </p>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-950 text-slate-400 text-xs uppercase border-b border-slate-800">
                <tr>
                  <th className="p-4">Nama Produk</th>
                  <th className="p-4">Product ID</th>
                  <th className="p-4">SKU</th>
                  <th className="p-4">Kebijakan Modul</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {protectedProducts.map((p) => (
                  <tr key={p.product_id} className="hover:bg-slate-800/30">
                    <td className="p-4 font-medium text-white">{p.name}</td>
                    <td className="p-4 font-mono text-xs text-slate-400">
                      {p.product_id}
                    </td>
                    <td className="p-4 font-mono text-xs text-slate-400">
                      {p.sku}
                    </td>
                    <td className="p-4">
                      <span className="px-2.5 py-1 text-xs rounded-full bg-rose-950 text-rose-400 border border-rose-800 font-semibold">
                        EXCLUDED PERMANENTLY
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 6: ACTIVITY LOGS */}
      {activeTab === "logs" && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-white">Audit Trail & Logs</h2>
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-950 text-slate-400 text-xs uppercase border-b border-slate-800">
                <tr>
                  <th className="p-4">Waktu</th>
                  <th className="p-4">Aksi</th>
                  <th className="p-4">Actor</th>
                  <th className="p-4">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {activityLogs.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="p-8 text-center text-slate-500">
                      Belum ada log aktivitas.
                    </td>
                  </tr>
                ) : (
                  activityLogs.map((log) => (
                    <tr key={log._id} className="hover:bg-slate-800/30">
                      <td className="p-4 text-xs text-slate-400 font-mono">
                        {fmtDate(log.created_at)}
                      </td>
                      <td className="p-4 font-semibold text-blue-400 text-xs">
                        {log.action}
                      </td>
                      <td className="p-4 text-xs text-slate-300">{log.actor}</td>
                      <td className="p-4 text-xs font-mono text-slate-400 truncate max-w-md">
                        {JSON.stringify(log.details)}
                      </td>
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
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-xl w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-bold text-white">Buat Campaign Baru</h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateCampaign} className="space-y-4 text-sm">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Nama Campaign
                </label>
                <input
                  type="text"
                  required
                  value={newCampaign.name}
                  onChange={(e) =>
                    setNewCampaign({ ...newCampaign, name: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Channel ID Tujuan
                </label>
                <input
                  type="text"
                  required
                  value={newCampaign.channel_id}
                  onChange={(e) =>
                    setNewCampaign({ ...newCampaign, channel_id: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Mode Runtime Penjadwalan
                </label>
                <select
                  value={newCampaign.schedule_mode}
                  onChange={(e) =>
                    setNewCampaign({ ...newCampaign, schedule_mode: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white"
                >
                  <option value="custom_sequence">
                    Mode A/B: Custom Sequence (Detik)
                  </option>
                  <option value="random_pool">
                    Mode C: Randomized Sequence dari Pool
                  </option>
                  <option value="fixed">Interval Tetap (Detik)</option>
                </select>
              </div>

              {newCampaign.schedule_mode === "custom_sequence" && (
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1">
                    Sequence Detik (Pisahkan koma)
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
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-xs"
                  />
                  <span className="text-[11px] text-slate-500">
                    Contoh: 180 (3m), 120 (2m), 180 (3m), 360 (6m), 300 (5m), 330 (5.5m)
                  </span>
                </div>
              )}

              {newCampaign.schedule_mode === "random_pool" && (
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1">
                    Pool Interval Detik (Pisahkan koma)
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
                    placeholder="30, 60, 90, 120, 140, 150, 180, 210, 300, 330, 360, 1800"
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white font-mono text-xs"
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">
                  Reservasi Inventory per Post (0 jika tanpa reservasi)
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
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white"
                />
              </div>

              <div className="flex items-center gap-2 pt-2">
                <input
                  type="checkbox"
                  id="is_sim"
                  checked={newCampaign.is_simulation}
                  onChange={(e) =>
                    setNewCampaign({
                      ...newCampaign,
                      is_simulation: e.target.checked,
                    })
                  }
                  className="rounded bg-slate-950 border-slate-800 text-blue-600"
                />
                <label htmlFor="is_sim" className="text-xs text-slate-300">
                  Mode Simulasi / Testing (Pesan berlabel SIMULASI, tanpa reservasi nyata)
                </label>
              </div>

              <div className="pt-4 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg"
                >
                  Batal
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium"
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
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-bold text-white">Restore Inventory</h3>
              <button
                onClick={() => setShowRestoreModal(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="p-3 bg-slate-950 rounded-lg text-xs space-y-1 text-slate-300 border border-slate-800">
              <div>
                Produk: <b>{selectedProductForRestore.product_name}</b>
              </div>
              <div>
                Total Reserved:{" "}
                <b className="text-amber-400">
                  {selectedProductForRestore.reserved_count} Unit
                </b>
              </div>
            </div>

            <form onSubmit={handleExecuteRestore} className="space-y-4 text-sm">
              <div className="space-y-2">
                <label className="block text-xs font-medium text-slate-400">
                  Pilih Mode Restore
                </label>
                <div className="space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="rmode"
                      value="all"
                      checked={restoreMode === "all"}
                      onChange={() => setRestoreMode("all")}
                      className="text-blue-600"
                    />
                    <span className="text-slate-200 text-xs">
                      <b>A. Restore All:</b> Kembalikan semua (
                      {selectedProductForRestore.reserved_count}) unit ke
                      AVAILABLE
                    </span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="rmode"
                      value="partial"
                      checked={restoreMode === "partial"}
                      onChange={() => setRestoreMode("partial")}
                      className="text-blue-600"
                    />
                    <span className="text-slate-200 text-xs">
                      <b>B. Restore Partial:</b> Masukkan kuantitas tertentu
                    </span>
                  </label>
                </div>
              </div>

              {restoreMode === "partial" && (
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1">
                    Kuantitas Unit yang akan di-Restore (Maksimal:{" "}
                    {selectedProductForRestore.reserved_count})
                  </label>
                  <input
                    type="number"
                    min="1"
                    max={selectedProductForRestore.reserved_count}
                    value={restoreQty}
                    onChange={(e) => setRestoreQty(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-white"
                  />
                </div>
              )}

              <div className="pt-4 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowRestoreModal(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg"
                >
                  Batal
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium"
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
