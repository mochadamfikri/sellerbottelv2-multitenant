import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Landmark, QrCode, ShieldCheck } from "lucide-react";
import api, { fmtIDR, formatApiErrorDetail } from "../lib/api";
import { Switch } from "../components/ui/switch";

const COINS = ["USDT", "USDC"];
const NETS = [
  { key: "SOL", label: "Solana" },
  { key: "POL", label: "Polygon" },
  { key: "BNB", label: "BNB (BEP-20)" },
  { key: "AVAX", label: "Avalanche" },
];

const cls = "mt-1 w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:border-cyan-500/60";

export default function SettingsPage() {
  const [s, setS] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/admin/settings")
      .then(({ data }) => setS(data))
      .catch((err) => toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal memuat pengaturan."));
  }, []);

  if (!s) return <p className="text-slate-500 text-sm">Memuat...</p>;

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.put("/admin/settings", {
        crypto_addresses: s.crypto_addresses,
        bank_name: s.bank_name,
        bank_account_number: s.bank_account_number,
        bank_account_holder: s.bank_account_holder,
        qris_enabled: !!s.qris_enabled,
        store_qris_enabled: !!s.store_qris_enabled,
        gopay_qr_timeout_minutes: Number(s.gopay_qr_timeout_minutes || 5),
        whatsapp_contact_number: String(s.whatsapp_contact_number || "+628123456789"),
        telegram_contact_target: String(s.telegram_contact_target || ""),
        bank_enabled: !!s.bank_enabled,
        min_deposit_usd: parseFloat(s.min_deposit_usd),
        min_deposit_idr: parseFloat(s.min_deposit_idr),
        admin_telegram_id: String(s.admin_telegram_id || ""),
        rate_mode: s.rate_mode,
        manual_rate: parseFloat(s.manual_rate),
        max_deposit_usd: parseFloat(s.max_deposit_usd || 100000),
        max_deposit_idr: parseFloat(s.max_deposit_idr || 100000000),
        join_gate_enabled: !!s.join_gate_enabled,
        join_gate_fail_open: !!s.join_gate_fail_open,
        required_channels: s.required_channels || [],
        auto_broadcast_new_product: !!s.auto_broadcast_new_product,
        transaction_success_channel_enabled: !!s.transaction_success_channel_enabled,
        broadcast_auto_image_enabled: !!s.broadcast_auto_image_enabled,
        broadcast_channel_id: String(s.broadcast_channel_id || ""),
        broadcast_group_ids: String(s.broadcast_group_ids || ""),
        transaction_channel_ids: String(s.transaction_channel_ids || ""),
        recap_channel_ids: String(s.recap_channel_ids || ""),
        stock_notifications_enabled: !!s.stock_notifications_enabled,
        join_group_target: String(s.join_group_target || ""),
        store_name: String(s.store_name || ""),
        store_tagline: String(s.store_tagline || ""),
        broadcast_enabled: !!s.broadcast_enabled,
        broadcast_message: String(s.broadcast_message || ""),
        require_channel_join: !!s.require_channel_join,
        channel_url: String(s.channel_url || ""),
        channel_name: String(s.channel_name || ""),
      });
      setS(data);
      toast.success("Pengaturan disimpan.");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Gagal menyimpan pengaturan.");
    } finally {
      setSaving(false);
    }
  };

  const setAddr = (key, val) => setS({ ...s, crypto_addresses: { ...s.crypto_addresses, [key]: val } });

  return (
    <div className="space-y-5">
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
        <div>
          <h2 className="font-heading font-semibold">Branding & Pengumuman Webshop</h2>
          <p className="text-xs text-slate-500 mt-1">Nama toko, banner pengumuman, dan wajib join channel di webshop.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-xs text-slate-400">Nama Toko
            <input className={cls} placeholder="Nama toko" value={s.store_name || ""} onChange={(e) => setS({ ...s, store_name: e.target.value })} />
          </label>
          <label className="block text-xs text-slate-400">Tagline
            <input className={cls} placeholder="Slogan toko" value={s.store_tagline || ""} onChange={(e) => setS({ ...s, store_tagline: e.target.value })} />
          </label>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input type="checkbox" checked={!!s.broadcast_enabled} onChange={(e) => setS({ ...s, broadcast_enabled: e.target.checked })} className="rounded" />
          Tampilkan banner pengumuman di webshop
        </label>
        {s.broadcast_enabled && (
          <label className="block text-xs text-slate-400">Isi Pengumuman
            <textarea className={cls} rows={2} placeholder="Promo spesial hari ini..." value={s.broadcast_message || ""} onChange={(e) => setS({ ...s, broadcast_message: e.target.value })} />
          </label>
        )}
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input type="checkbox" checked={!!s.require_channel_join} onChange={(e) => setS({ ...s, require_channel_join: e.target.checked })} className="rounded" />
          Wajib join channel Telegram sebelum akses webshop
        </label>
        {s.require_channel_join && (
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-xs text-slate-400">Link Channel
              <input className={cls} placeholder="https://t.me/namachannel" value={s.channel_url || ""} onChange={(e) => setS({ ...s, channel_url: e.target.value })} />
            </label>
            <label className="block text-xs text-slate-400">Nama Channel
              <input className={cls} placeholder="Nama Channel" value={s.channel_name || ""} onChange={(e) => setS({ ...s, channel_name: e.target.value })} />
            </label>
          </div>
        )}
      </div>
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
        <div>
          <h2 className="font-heading font-semibold">Kontak mengambang di Front Store</h2>
          <p className="text-xs text-slate-500 mt-1">Atur tujuan tombol WhatsApp dan Telegram. Widget akan hilang otomatis setelah 2 menit atau saat pengunjung menutupnya.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-xs text-slate-400">Nomor WhatsApp
            <input className={cls} type="tel" inputMode="tel" placeholder="+628123456789" value={s.whatsapp_contact_number ? (String(s.whatsapp_contact_number).startsWith("+") ? String(s.whatsapp_contact_number) : `+${s.whatsapp_contact_number}`) : "+628123456789"} onChange={(e) => setS({ ...s, whatsapp_contact_number: e.target.value })} />
            <span className="mt-1 block text-[11px] text-slate-600">Pengunjung diarahkan ke nomor ini dengan pesan produk terisi otomatis.</span>
          </label>
          <label className="block text-xs text-slate-400">Username / link Telegram
            <input className={cls} placeholder="@username atau https://t.me/username" value={s.telegram_contact_target || ""} onChange={(e) => setS({ ...s, telegram_contact_target: e.target.value })} />
            <span className="mt-1 block text-[11px] text-slate-600">Kosongkan untuk menyembunyikan tombol Telegram.</span>
          </label>
        </div>
      </div>
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
        <div>
          <h2 className="font-heading font-semibold">Gateway Pembayaran</h2>
          <p className="text-xs text-slate-500 mt-1">Atur metode deposit IDR yang tampil di bot. Jika keduanya OFF, bot menampilkan notifikasi gateway sedang mengalami gangguan.</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex gap-3">
                <div className="w-9 h-9 rounded-lg bg-cyan-500/10 flex items-center justify-center"><QrCode size={18} className="text-cyan-400" /></div>
                <div>
                  <p className="font-semibold text-slate-200">QRIS All Payment +0.7% otomatis</p>
                  <p className="text-xs text-slate-500 mt-1">Nominal QR dibuat otomatis dan status pembayaran dipantau oleh gateway yang terhubung.</p>
                </div>
              </div>
              <Switch checked={!!s.qris_enabled} onCheckedChange={(v) => setS({ ...s, qris_enabled: v })} />
            </div>
            <div className="mt-3 text-xs">
              <span className={s.qris_enabled ? "text-emerald-400" : "text-slate-600"}>{s.qris_enabled ? "ON" : "OFF"}</span>
              {s.qris_enabled && <span className="text-slate-600 ml-2">Pastikan GOPAY_ENABLED di server aktif.</span>}
            </div>
            <div className="mt-4 max-w-xs">
              <label className="text-xs text-slate-400" htmlFor="gopay-qr-timeout">Masa berlaku QR (menit)</label>
              <input id="gopay-qr-timeout" type="number" min="1" max="60" step="1" className={cls}
                value={s.gopay_qr_timeout_minutes ?? 5}
                onChange={(e) => setS({ ...s, gopay_qr_timeout_minutes: e.target.value })} />
              <p className="mt-1 text-xs text-slate-600">Nilai awal 5 menit. Perubahan berlaku untuk QR baru.</p>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex gap-3">
                <div className="w-9 h-9 rounded-lg bg-amber-500/10 flex items-center justify-center"><Landmark size={18} className="text-amber-400" /></div>
                <div>
                  <p className="font-semibold text-slate-200">Bank Transfer 0 fees — manual checking</p>
                  <p className="text-xs text-slate-500 mt-1">Transfer bank menggunakan bukti foto dan persetujuan admin.</p>
                </div>
              </div>
              <Switch checked={!!s.bank_enabled} onCheckedChange={(v) => setS({ ...s, bank_enabled: v })} />
            </div>
            <div className="mt-3 text-xs"><span className={s.bank_enabled ? "text-emerald-400" : "text-slate-600"}>{s.bank_enabled ? "ON" : "OFF"}</span></div>
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex gap-3">
              <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center"><QrCode size={18} className="text-emerald-400" /></div>
              <div><p className="font-semibold text-slate-200">QRIS Front Store</p><p className="mt-1 text-xs text-slate-500">Pengaturan ini hanya untuk deposit dan checkout web; tidak mengubah metode pembayaran bot.</p></div>
            </div>
            <Switch checked={!!s.store_qris_enabled} onCheckedChange={(v) => setS({ ...s, store_qris_enabled: v })} />
          </div>
          <p className={`mt-3 text-xs ${s.store_qris_enabled ? "text-emerald-400" : "text-slate-600"}`}>{s.store_qris_enabled ? "ON" : "OFF"}{s.store_qris_enabled && " · Pastikan GOPAY_ENABLED di server aktif."}</p>
        </div>
      </div>

      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
        <h2 className="font-heading font-semibold mb-1">Alamat Deposit Crypto</h2>
        <p className="text-xs text-slate-500 mb-4">Isi alamat wallet untuk setiap kombinasi koin × jaringan. Kosongkan jika tidak menerima.</p>
        {COINS.map((coin) => (
          <div key={coin} className="mb-4">
            <p className="text-sm font-semibold text-cyan-400 mb-2">{coin}</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {NETS.map((n) => (
                <div key={n.key}>
                  <label className="text-xs text-slate-400">{n.label}</label>
                  <input className={cls} placeholder={"Alamat " + coin + " di " + n.label}
                    value={s.crypto_addresses?.[coin + "_" + n.key] || ""}
                    onChange={(e) => setAddr(coin + "_" + n.key, e.target.value)} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-3">
          <h2 className="font-heading font-semibold">Rekening Bank (Deposit IDR)</h2>
          <div><label className="text-xs text-slate-400">Nama Bank</label><input className={cls} placeholder="cth: BCA" value={s.bank_name || ""} onChange={(e) => setS({ ...s, bank_name: e.target.value })} /></div>
          <div><label className="text-xs text-slate-400">Nomor Rekening</label><input className={cls} value={s.bank_account_number || ""} onChange={(e) => setS({ ...s, bank_account_number: e.target.value })} /></div>
          <div><label className="text-xs text-slate-400">Atas Nama</label><input className={cls} value={s.bank_account_holder || ""} onChange={(e) => setS({ ...s, bank_account_holder: e.target.value })} /></div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-3">
          <h2 className="font-heading font-semibold">Deposit & Admin</h2>
          <div className="grid grid-cols-2 gap-3">
            <div><label className="text-xs text-slate-400">Min. Deposit USD</label><input type="number" className={cls} value={s.min_deposit_usd} onChange={(e) => setS({ ...s, min_deposit_usd: e.target.value })} /></div>
            <div><label className="text-xs text-slate-400">Min. Deposit IDR</label><input type="number" className={cls} value={s.min_deposit_idr} onChange={(e) => setS({ ...s, min_deposit_idr: e.target.value })} /></div>
          </div>
          <div><label className="text-xs text-slate-400">Telegram ID Admin</label><input className={cls} value={s.admin_telegram_id || ""} onChange={(e) => setS({ ...s, admin_telegram_id: e.target.value })} /></div>

          <div className="pt-2 border-t border-slate-800 space-y-3">
            <h3 className="text-sm font-semibold">Batas Deposit</h3>
            <div className="grid grid-cols-2 gap-3">
              <div><label className="text-xs text-slate-400">Maks. Deposit USD</label><input type="number" className={cls} value={s.max_deposit_usd || ""} onChange={(e) => setS({ ...s, max_deposit_usd: e.target.value })} /></div>
              <div><label className="text-xs text-slate-400">Maks. Deposit IDR</label><input type="number" className={cls} value={s.max_deposit_idr || ""} onChange={(e) => setS({ ...s, max_deposit_idr: e.target.value })} /></div>
            </div>

            <h3 className="text-sm font-semibold">Kurs USD → IDR</h3>
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-400">Mode Manual</span>
              <Switch checked={s.rate_mode === "manual"} onCheckedChange={(v) => setS({ ...s, rate_mode: v ? "manual" : "auto" })} />
            </div>
            {s.rate_mode === "manual" ? (
              <div><label className="text-xs text-slate-400">Kurs Manual (1 USD = ? IDR)</label><input type="number" className={cls} value={s.manual_rate} onChange={(e) => setS({ ...s, manual_rate: e.target.value })} /></div>
            ) : (
              <p className="text-sm text-slate-400">Kurs otomatis saat ini: <span className="font-mono text-cyan-400">{fmtIDR(s.current_rate)}</span></p>
            )}
          </div>
        </div>
      </div>

      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
        <div>
          <h2 className="font-heading font-semibold">Automation & Broadcast</h2>
          <p className="text-xs text-slate-500 mt-1">Atur notifikasi otomatis tanpa mengubah notifikasi transaksi ke admin Telegram.</p>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 flex items-center justify-between gap-4">
            <div><p className="font-semibold text-slate-200">Auto Broadcast Product Baru</p><p className="text-xs text-slate-500 mt-1">Kirim product baru otomatis ke channel.</p></div>
            <Switch checked={!!s.auto_broadcast_new_product} onCheckedChange={(v) => setS({ ...s, auto_broadcast_new_product: v })} />
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 flex items-center justify-between gap-4">
            <div><p className="font-semibold text-slate-200">Transaction Success → Channel</p><p className="text-xs text-slate-500 mt-1">Kirim notice transaksi tanpa identitas pembeli.</p></div>
            <Switch checked={!!s.transaction_success_channel_enabled} onCheckedChange={(v) => setS({ ...s, transaction_success_channel_enabled: v })} />
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 flex items-center justify-between gap-4">
            <div><p className="font-semibold text-slate-200">Auto Generate Picture</p><p className="text-xs text-slate-500 mt-1">Gambar untuk notifikasi produk, transaksi, dan rekap otomatis. Broadcast manual dapat memilih gambar atau teks saja.</p></div>
            <Switch checked={!!s.broadcast_auto_image_enabled} onCheckedChange={(v) => setS({ ...s, broadcast_auto_image_enabled: v })} />
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 flex items-center justify-between gap-4">
            <div><p className="font-semibold text-slate-200">Notifikasi Stok Otomatis</p><p className="text-xs text-slate-500 mt-1">Kirim gambar ke channel/grup saat stok habis atau tersedia kembali.</p></div>
            <Switch checked={s.stock_notifications_enabled !== false} onCheckedChange={(v) => setS({ ...s, stock_notifications_enabled: v })} />
          </div>
        </div>
        <div>
          <label className="text-xs text-slate-400">Channel Broadcast ID</label>
          <input className={cls} placeholder="-1001234567890 atau @username" value={s.broadcast_channel_id || ""} onChange={(e) => setS({ ...s, broadcast_channel_id: e.target.value })} />
          <p className="text-[10px] text-slate-600 mt-1">Bot harus menjadi admin channel. Jika kosong, sistem masih bisa memakai required channel pertama yang aktif.</p>
        </div>
        <div>
          <label className="text-xs text-slate-400">Grup Broadcast ID (satu per baris)</label>
          <textarea rows={3} className={cls} placeholder="-1001234567890" value={s.broadcast_group_ids || ""} onChange={(e) => setS({ ...s, broadcast_group_ids: e.target.value })} />
          <p className="text-[10px] text-slate-600 mt-1">Bot harus menjadi anggota grup dan diizinkan mengirim pesan. Channel dan grup ini dipakai untuk broadcast serta notifikasi stok.</p>
        </div>
        <div><label className="text-xs text-slate-400">Channel transaksi berhasil (satu per baris)</label><textarea rows={2} className={cls} value={s.transaction_channel_ids || ""} onChange={(e) => setS({ ...s, transaction_channel_ids: e.target.value })} placeholder="-1001234567890 atau @username"/><p className="mt-1 text-xs text-slate-500">Mengikuti toggle Transaction Success. Kosong: gunakan channel broadcast utama.</p></div>
        <div><label className="text-xs text-slate-400">Channel rekap & produk terlaris (satu per baris)</label><textarea rows={2} className={cls} value={s.recap_channel_ids || ""} onChange={(e) => setS({ ...s, recap_channel_ids: e.target.value })} placeholder="-1001234567890 atau @username"/><p className="mt-1 text-xs text-slate-500">Dipakai untuk rekap manual dan terjadwal. Kosong: gunakan tujuan broadcast umum. Jadwal di menu Broadcast.</p></div>
        <a href="/bot-moderation" className="block text-sm text-cyan-400">Atur tindak lanjut setelah pembelian & pengecualian pengguna →</a>
        <div>
          <label className="text-xs text-slate-400">Target Join Group untuk akun Telegram terhubung</label>
          <input className={cls} placeholder="@group atau https://t.me/+invitehash" value={s.join_group_target || ""} onChange={(e) => setS({ ...s, join_group_target: e.target.value })} />
        </div>
      </div>

      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-heading font-semibold">Wajib Join Channel</h2>
            <p className="text-xs text-slate-500 mt-1">Pengguna harus menjadi member semua channel aktif sebelum bisa memakai bot. Maksimal 3 channel.</p>
          </div>
          <Switch checked={!!s.join_gate_enabled} onCheckedChange={(v) => setS({ ...s, join_gate_enabled: v })} />
        </div>

        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-300">
          <b>Penting:</b> bot wajib menjadi <b>Administrator</b> di setiap channel. Gunakan tombol <b>Test</b> setelah mengisi Channel ID untuk memastikan bot bisa membaca membership.
        </div>

        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full min-w-[900px] text-sm">
            <thead className="bg-slate-950/80">
              <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                <th className="px-3 py-3 w-12">No.</th>
                <th className="px-3 py-3">Channel ID *</th>
                <th className="px-3 py-3">Nama Channel</th>
                <th className="px-3 py-3">Username / @username</th>
                <th className="px-3 py-3">Link Join</th>
                <th className="px-3 py-3">Status</th>
                <th className="px-3 py-3 text-right">Aksi</th>
              </tr>
            </thead>
            <tbody>
              {(s.required_channels || []).map((ch, index) => (
                <tr key={index} className="border-t border-slate-800/70 align-top">
                  <td className="px-3 py-3 text-slate-500">{index + 1}</td>
                  <td className="px-3 py-3">
                    <input className={cls} placeholder="-1001234567890" value={ch.channel_id || ""} onChange={(e) => {
                      const next = [...(s.required_channels || [])];
                      next[index] = { ...next[index], channel_id: e.target.value };
                      setS({ ...s, required_channels: next });
                    }} />
                    <p className="text-[10px] text-slate-600 mt-1">Public/private: gunakan ID -100...</p>
                  </td>
                  <td className="px-3 py-3">
                    <input className={cls} placeholder="IDSE Network" value={ch.title || ""} onChange={(e) => {
                      const next = [...(s.required_channels || [])];
                      next[index] = { ...next[index], title: e.target.value };
                      setS({ ...s, required_channels: next });
                    }} />
                  </td>
                  <td className="px-3 py-3">
                    <input className={cls} placeholder="@channelku" value={ch.username || ""} onChange={(e) => {
                      const next = [...(s.required_channels || [])];
                      next[index] = { ...next[index], username: e.target.value };
                      setS({ ...s, required_channels: next });
                    }} />
                  </td>
                  <td className="px-3 py-3">
                    <input className={cls} placeholder="https://t.me/..." value={ch.invite_link || ""} onChange={(e) => {
                      const next = [...(s.required_channels || [])];
                      next[index] = { ...next[index], invite_link: e.target.value };
                      setS({ ...s, required_channels: next });
                    }} />
                  </td>
                  <td className="px-3 py-3">
                    <button onClick={async () => {
                      if (!ch.channel_id) { toast.error("Isi Channel ID dulu."); return; }
                      try {
                        const { data } = await api.post("/admin/settings/join-gate/test", null, { params: { channel_id: ch.channel_id } });
                        const next = [...(s.required_channels || [])];
                        next[index] = { ...next[index], title: data.title || ch.title, username: data.username || ch.username, enabled: true, test_status: "ok" };
                        setS({ ...s, required_channels: next });
                        toast.success("Channel terhubung. Bot berstatus " + data.bot_status + ".");
                      } catch (err) {
                        toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Channel tidak bisa diverifikasi.");
                      }
                    }} className="rounded-lg border border-cyan-500/20 text-cyan-400 hover:bg-cyan-500/10 px-3 py-2 text-xs">
                      Test
                    </button>
                    <div className="mt-2 text-[10px]">
                      {ch.test_status === "ok" ? <span className="text-emerald-400">✓ Terverifikasi</span> : <span className="text-slate-600">Belum dites</span>}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-right">
                    <button onClick={() => setS({ ...s, required_channels: (s.required_channels || []).filter((_, i) => i !== index) })} className="rounded-lg border border-rose-500/20 text-rose-400 hover:bg-rose-500/10 px-3 py-2 text-xs">Hapus</button>
                  </td>
                </tr>
              ))}
              {!(s.required_channels || []).length && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-slate-500">Belum ada channel. Klik “+ Tambah Channel” untuk membuat rule wajib join.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {(s.required_channels || []).length < 3 && (
          <button className="text-sm text-cyan-400 hover:text-cyan-300" onClick={() => setS({
            ...s,
            required_channels: [...(s.required_channels || []), { channel_id: "", title: "", username: "", invite_link: "", enabled: true }]
          })}>+ Tambah Channel</button>
        )}

        <div className="flex items-center justify-between border-t border-slate-800 pt-4">
          <div>
            <p className="text-sm font-medium">Jika Telegram gagal diperiksa</p>
            <p className="text-xs text-slate-500 mt-1">OFF = akses ditolak sampai membership berhasil diverifikasi. Ini lebih aman untuk mode wajib join.</p>
          </div>
          <Switch checked={!!s.join_gate_fail_open} onCheckedChange={(v) => setS({ ...s, join_gate_fail_open: v })} />
        </div>
      </div>

      <button onClick={save} disabled={saving} className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-semibold rounded-lg px-6 py-2.5">
        {saving ? "Menyimpan..." : "Simpan Pengaturan"}
      </button>
    </div>
  );
}
