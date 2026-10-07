import { useCallback, useEffect, useMemo, useState } from "react";
import { BadgePercent, Ban, Check, Megaphone, RefreshCw, Send, Trash2, Upload, UserPlus, Users } from "lucide-react";
import { toast } from "sonner";
import api, { formatApiErrorDetail } from "../lib/api";

const cls = "w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-cyan-500/60";
const tabs = [
  ["overview", "Ringkasan"],
  ["accounts", "Akun Telegram"],
  ["prospects", "Prospek"],
  ["campaigns", "Kampanye"],
  ["groups", "Posting Grup"],
  ["coupons", "Kupon"],
  ["results", "Hasil"],
];

const emptyCoupon = { code: "", type: "percent", value: "", currency: "IDR", quota_total: "", per_user_limit: 1, min_purchase: 0, max_discount: "", product_ids: [], starts_at: "", ends_at: "", active: true };
const emptyCampaign = { name: "", template: "", source_code: "", bot_link: "", product_id: "", account_ids: [], approval_required: true, daily_limit: 20, min_interval_seconds: 300, send_window_start: "09:00", send_window_end: "21:00" };

function toLocalDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export default function Promotions() {
  const [tab, setTab] = useState("overview");
  const [summary, setSummary] = useState({});
  const [accounts, setAccounts] = useState([]);
  const [products, setProducts] = useState([]);
  const [prospects, setProspects] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [groups, setGroups] = useState([]);
  const [coupons, setCoupons] = useState([]);
  const [results, setResults] = useState({});
  const [sources, setSources] = useState([]);
  const [events, setEvents] = useState([]);
  const [busy, setBusy] = useState(false);

  const [phone, setPhone] = useState("");
  const [pendingAccount, setPendingAccount] = useState("");
  const [otp, setOtp] = useState("");
  const [twofa, setTwofa] = useState("");
  const [manual, setManual] = useState({ tg_user_id: "", username: "", name: "", notes: "" });
  const [source, setSource] = useState({ code: "", kind: "campaign", label: "" });
  const [coupon, setCoupon] = useState(emptyCoupon);
  const [editingCouponId, setEditingCouponId] = useState("");
  const [campaign, setCampaign] = useState(emptyCampaign);
  const [post, setPost] = useState({ account_id: "", group_id: "", message: "" });
  const [userMessage, setUserMessage] = useState({ account_id: "", prospect_id: "", message: "" });

  const error = (e) => toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Terjadi kesalahan.");
  const activeAccounts = useMemo(() => accounts.filter((a) => a.status === "active"), [accounts]);
  const postGroups = useMemo(
    () => groups.filter((g) => !post.account_id || g.account_id === post.account_id),
    [groups, post.account_id],
  );

  const load = useCallback(async () => {
    try {
      const [s, a, prod, p, c, j, g, co, r, src, ev] = await Promise.all([
        api.get("/admin/promo/summary"),
        api.get("/admin/promo/accounts"),
        api.get("/admin/products"),
        api.get("/admin/promo/prospects"),
        api.get("/admin/promo/campaigns"),
        api.get("/admin/promo/jobs"),
        api.get("/admin/promo/groups"),
        api.get("/admin/promo/coupons"),
        api.get("/admin/promo/results"),
        api.get("/admin/promo/results/sources"),
        api.get("/admin/promo/events"),
      ]);
      setSummary(s.data); setAccounts(a.data); setProducts(prod.data); setProspects(p.data); setCampaigns(c.data);
      setJobs(j.data); setGroups(g.data); setCoupons(co.data); setResults(r.data);
      setSources(src.data); setEvents(ev.data);
    } catch (e) { error(e); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const startLogin = async () => {
    if (!phone.trim()) return toast.error("Nomor Telegram wajib diisi.");
    setBusy(true);
    try {
      const r = await api.post("/admin/promo/accounts/login/start", { phone: phone.trim() });
      setPendingAccount(r.data.account_id);
      toast.success("OTP Telegram dikirim.");
    } catch (e) { error(e); } finally { setBusy(false); }
  };

  const verifyLogin = async () => {
    if (!pendingAccount || !otp.trim()) return toast.error("OTP wajib diisi.");
    setBusy(true);
    try {
      const r = await api.post("/admin/promo/accounts/login/" + pendingAccount + "/verify", { code: otp.trim(), password: twofa || null });
      if (r.data.status === "password_required") {
        toast.info("Akun meminta password 2FA. Masukkan password lalu klik Verifikasi lagi.");
        return;
      }
      toast.success("Akun Telegram tersambung.");
      setPendingAccount(""); setPhone(""); setOtp(""); setTwofa(""); await load();
    } catch (e) { error(e); } finally { setBusy(false); }
  };

  const accountAction = async (id, action) => {
    try {
      const r = await api.post("/admin/promo/accounts/" + id + "/" + action);
      toast.success(r.data.status || "Berhasil.");
      await load();
    } catch (e) { error(e); }
  };

  const revoke = async (id) => {
    if (!window.confirm("Cabut session akun ini?")) return;
    try { await api.delete("/admin/promo/accounts/" + id); await load(); } catch (e) { error(e); }
  };

  const importPrivate = async (id) => {
    try {
      const r = await api.post("/admin/promo/accounts/" + id + "/import-private");
      toast.success("Import selesai: " + (r.data.added || 0) + " prospek.");
      await load();
    } catch (e) { error(e); }
  };

  const syncGroups = async (id) => {
    try {
      const r = await api.post("/admin/promo/accounts/" + id + "/sync-groups");
      toast.success("Grup tersinkron: " + (r.data.groups || 0));
      await load();
    } catch (e) { error(e); }
  };

  const addManualProspect = async () => {
    if (!manual.tg_user_id) return toast.error("Telegram ID wajib diisi.");
    try {
      await api.post("/admin/promo/prospects/manual", { ...manual, tg_user_id: Number(manual.tg_user_id) });
      toast.success("Prospek ditambahkan.");
      setManual({ tg_user_id: "", username: "", name: "", notes: "" }); await load();
    } catch (e) { error(e); }
  };

  const createSource = async () => {
    if (!source.code || !source.kind || !source.label) return toast.error("Source code, jenis, dan label wajib diisi.");
    try {
      await api.post("/admin/promo/sources", source);
      toast.success("Source dibuat.");
      setSource({ code: "", kind: "campaign", label: "" }); await load();
    } catch (e) { error(e); }
  };

  const saveCoupon = async () => {
    if (!coupon.code.trim() || !Number(coupon.value)) return toast.error("Kode dan nilai kupon wajib diisi.");
    if (coupon.type === "percent" && Number(coupon.value) > 100) return toast.error("Diskon persen maksimal 100%.");
    try {
      const payload = {
        ...coupon,
        code: coupon.code.trim().toUpperCase(),
        value: Number(coupon.value),
        quota_total: coupon.quota_total ? Number(coupon.quota_total) : null,
        per_user_limit: Number(coupon.per_user_limit || 1),
        min_purchase: Number(coupon.min_purchase || 0),
        max_discount: coupon.max_discount ? Number(coupon.max_discount) : null,
        product_ids: coupon.product_ids || [],
        starts_at: coupon.starts_at ? new Date(coupon.starts_at).toISOString() : null,
        ends_at: coupon.ends_at ? new Date(coupon.ends_at).toISOString() : null,
      };
      if (editingCouponId) await api.put("/admin/promo/coupons/" + editingCouponId, payload);
      else await api.post("/admin/promo/coupons", payload);
      toast.success(editingCouponId ? "Kupon diperbarui." : "Kupon dibuat.");
      setCoupon(emptyCoupon); setEditingCouponId(""); await load();
    } catch (e) { error(e); }
  };

  const editCoupon = (item) => {
    setEditingCouponId(item._id);
    setCoupon({
      code: item.code || "", type: item.type || "percent", value: item.value ?? "",
      currency: item.currency || "IDR", quota_total: item.quota_total ?? "",
      per_user_limit: item.per_user_limit || 1, min_purchase: item.min_purchase || 0,
      max_discount: item.max_discount ?? "", product_ids: item.product_ids || [],
      starts_at: toLocalDateTime(item.starts_at), ends_at: toLocalDateTime(item.ends_at),
      active: item.active !== false,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const toggleCoupon = async (id) => {
    try { await api.patch("/admin/promo/coupons/" + id + "/toggle"); await load(); }
    catch (e) { error(e); }
  };

  const cancelCouponEdit = () => { setEditingCouponId(""); setCoupon(emptyCoupon); };

  const deleteCoupon = async (id) => {
    if (!window.confirm("Hapus kupon ini?")) return;
    try { await api.delete("/admin/promo/coupons/" + id); await load(); } catch (e) { error(e); }
  };

  const createCampaign = async () => {
    if (!campaign.name.trim() || !campaign.template.trim()) return toast.error("Nama dan template wajib diisi.");
    if (!campaign.account_ids.length) return toast.error("Pilih minimal satu akun Telegram aktif.");
    try {
      await api.post("/admin/promo/campaigns", campaign);
      toast.success("Campaign dibuat."); setCampaign(emptyCampaign); await load();
    } catch (e) { error(e); }
  };

  const enqueue = async (id) => {
    try {
      const r = await api.post("/admin/promo/campaigns/" + id + "/enqueue");
      toast.success((r.data.queued || 0) + " job masuk antrean."); await load();
    } catch (e) { error(e); }
  };

  const approve = async (id) => {
    try { await api.post("/admin/promo/jobs/" + id + "/approve"); await load(); } catch (e) { error(e); }
  };

  const stopCampaign = async (id) => {
    if (!window.confirm("Hentikan campaign dan batalkan queue yang belum dikirim?")) return;
    try { await api.patch("/admin/promo/campaigns/" + id + "/stop"); await load(); } catch (e) { error(e); }
  };

  const optOut = async (tgUserId) => {
    try {
      await api.post("/admin/promo/opt-out", { tg_user_id: Number(tgUserId), reason: "admin" });
      toast.success("Prospek masuk suppression list."); await load();
    } catch (e) { error(e); }
  };

  const setContactPermission = async (prospect) => {
    try {
      await api.patch("/admin/promo/prospects/" + prospect._id, { contact_allowed: !prospect.contact_allowed });
      await load();
    } catch (e) { error(e); }
  };

  const postGroup = async () => {
    if (!post.account_id || !post.group_id || !post.message.trim()) return toast.error("Akun, grup, dan pesan wajib diisi.");
    try {
      await api.post("/admin/promo/groups/" + post.group_id + "/post", { ...post, group_id: Number(post.group_id) });
      toast.success("Posting grup terkirim."); setPost({ ...post, message: "" });
      await load();
    } catch (e) { error(e); }
  };

  const syncPostGroups = async () => {
    if (!post.account_id) return toast.error("Pilih akun Telegram terlebih dahulu.");
    try {
      const r = await api.post("/admin/promo/accounts/" + post.account_id + "/sync-groups");
      toast.success("Grup tersinkron: " + (r.data.groups || 0));
      setPost((v) => ({ ...v, group_id: "" }));
      await load();
    } catch (e) { error(e); }
  };

  const sendUserMessage = async () => {
    if (!userMessage.account_id || !userMessage.prospect_id || !userMessage.message.trim()) {
      return toast.error("Akun, pengguna, dan pesan wajib diisi.");
    }
    try {
      await api.post("/admin/promo/prospects/" + userMessage.prospect_id + "/send", userMessage);
      toast.success("Pesan pengguna terkirim.");
      setUserMessage((v) => ({ ...v, message: "" }));
      await load();
    } catch (e) { error(e); }
  };

  return (
    <div className="space-y-5">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {tabs.map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)} className={"px-4 py-2 rounded-lg text-sm whitespace-nowrap border " + (tab === id ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-300" : "border-slate-800 text-slate-400 hover:text-slate-200")}>{label}</button>
        ))}
        <button onClick={load} className="ml-auto p-2 text-slate-400 hover:text-slate-100" title="Refresh"><RefreshCw size={16} /></button>
      </div>

      {tab === "overview" && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              ["Kupon", summary.coupons || 0, BadgePercent],
              ["Prospek", summary.prospects || 0, Users],
              ["Kampanye", summary.campaigns || 0, Megaphone],
              ["Akun Telegram", summary.telegram_accounts || 0, Send],
              ["Grup", summary.groups || 0, Users],
            ].map(([label, value, Icon]) => <div key={label} className="bg-slate-900/80 border border-slate-800 rounded-xl p-4"><Icon size={17} className="text-cyan-400 mb-3" /><p className="text-2xl font-semibold">{value}</p><p className="text-xs text-slate-500 mt-1">{label}</p></div>)}
          </div>
          <div className="grid lg:grid-cols-2 gap-5">
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
              <h2 className="font-heading font-semibold">Kontrol Pengiriman</h2>
              <p className="text-sm text-slate-400 mt-2">Interval minimum 5 menit, batas harian, jam pengiriman, approval, suppression/opt-out, dan penghentian saat Telegram memberi pembatasan.</p>
            </div>
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
              <h2 className="font-heading font-semibold">Status Hasil</h2>
              <div className="grid grid-cols-3 gap-3 mt-4 text-sm">
                <div><b>{results.sent || 0}</b><p className="text-slate-500">Terkirim</p></div>
                <div><b>{results.replied || 0}</b><p className="text-slate-500">Balas</p></div>
                <div><b>{results.customers || 0}</b><p className="text-slate-500">Customer</p></div>
              </div>
            </div>
          </div>
        </>
      )}

      {tab === "accounts" && (
        <div className="space-y-5">
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-3">
            <h2 className="font-semibold">Tambah Akun Telegram</h2>
            <div className="grid md:grid-cols-3 gap-2">
              <input className={cls} placeholder="+628..." value={phone} onChange={(e) => setPhone(e.target.value)} />
              <button disabled={busy} onClick={startLogin} className="bg-cyan-600 hover:bg-cyan-700 disabled:opacity-50 rounded-lg">Kirim OTP</button>
              <input className={cls} placeholder="OTP" value={otp} onChange={(e) => setOtp(e.target.value)} />
            </div>
            {pendingAccount && <div className="grid md:grid-cols-2 gap-2"><input className={cls} type="password" placeholder="Password 2FA jika diminta" value={twofa} onChange={(e) => setTwofa(e.target.value)} /><button disabled={busy} onClick={verifyLogin} className="bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 rounded-lg">Verifikasi</button></div>}
          </div>
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-x-auto">
            <table className="w-full text-sm"><thead><tr className="border-b border-slate-800 text-xs text-slate-500"><th className="p-3 text-left">Akun</th><th>Status</th><th>Telegram ID</th><th>Aksi</th></tr></thead>
              <tbody>{accounts.map((a) => <tr key={a._id} className="border-b border-slate-800/70"><td className="p-3">{a.name || a.username || a.phone || "-"}</td><td>{a.status}</td><td>{a.tg_user_id || "-"}</td><td className="p-3 flex gap-2 justify-center"><button onClick={() => accountAction(a._id, "check")} title="Cek"><RefreshCw size={15} /></button><button onClick={() => importPrivate(a._id)} title="Import private chat"><Upload size={15} /></button><button onClick={() => syncGroups(a._id)} title="Sync grup"><Users size={15} /></button><button onClick={() => revoke(a._id)} title="Cabut" className="text-rose-400"><Trash2 size={15} /></button></td></tr>)}</tbody>
            </table>
            {!accounts.length && <p className="p-5 text-sm text-slate-500">Belum ada akun.</p>}
          </div>
        </div>
      )}

      {tab === "prospects" && (
        <div className="space-y-5">
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-3">
            <div className="flex items-center gap-2"><UserPlus size={17} className="text-cyan-400" /><h2 className="font-semibold">Tambah Prospek Manual</h2></div>
            <div className="grid md:grid-cols-4 gap-2"><input className={cls} placeholder="Telegram ID" value={manual.tg_user_id} onChange={(e) => setManual({ ...manual, tg_user_id: e.target.value })} /><input className={cls} placeholder="Username" value={manual.username} onChange={(e) => setManual({ ...manual, username: e.target.value })} /><input className={cls} placeholder="Nama" value={manual.name} onChange={(e) => setManual({ ...manual, name: e.target.value })} /><button onClick={addManualProspect} className="bg-cyan-600 rounded-lg">Tambah</button></div>
            <input className={cls} placeholder="Catatan" value={manual.notes} onChange={(e) => setManual({ ...manual, notes: e.target.value })} />
          </div>
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-3">
            <div className="flex items-center gap-2"><Send size={17} className="text-cyan-400" /><h2 className="font-semibold">Kirim Pesan ke Pengguna</h2></div>
            <p className="text-xs text-slate-500">Hanya prospek yang berstatus izin kontak yang dapat dikirimi pesan secara manual.</p>
            <div className="grid md:grid-cols-2 gap-2">
              <select className={cls} value={userMessage.account_id} onChange={(e) => setUserMessage({ ...userMessage, account_id: e.target.value })}>
                <option value="">Pilih akun pengirim</option>
                {activeAccounts.map((a) => <option key={a._id} value={a._id}>{a.name || a.username || a.tg_user_id}</option>)}
              </select>
              <select className={cls} value={userMessage.prospect_id} onChange={(e) => setUserMessage({ ...userMessage, prospect_id: e.target.value })}>
                <option value="">Pilih pengguna</option>
                {prospects.filter((p) => p.contact_allowed && p.status !== "opt_out").map((p) => <option key={p._id} value={p._id}>{p.name || (p.username ? "@" + p.username : p.tg_user_id)}</option>)}
              </select>
            </div>
            <textarea className={cls} rows="4" placeholder="Tulis pesan..." value={userMessage.message} onChange={(e) => setUserMessage({ ...userMessage, message: e.target.value })} />
            <button onClick={sendUserMessage} className="bg-cyan-600 hover:bg-cyan-700 rounded-lg px-4 py-2">Kirim Pesan</button>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-x-auto">
            <table className="w-full text-sm"><thead><tr className="border-b border-slate-800 text-xs text-slate-500"><th className="p-3 text-left">Nama</th><th>Username</th><th>Status</th><th>Izin kontak</th><th>Source</th><th>Aksi</th></tr></thead><tbody>{prospects.map((p) => <tr key={p._id} className="border-b border-slate-800/70"><td className="p-3">{p.name || "-"}</td><td>{p.username ? "@" + p.username : "-"}</td><td>{p.status}</td><td><button onClick={() => setContactPermission(p)} className={p.contact_allowed ? "text-emerald-400" : "text-slate-500"}>{p.contact_allowed ? "Diizinkan" : "Belum"}</button></td><td>{p.source?.label || "-"}</td><td className="p-3 flex gap-2 justify-center">
  {p.contact_allowed && <button onClick={() => setUserMessage({ account_id: activeAccounts[0]?._id || "", prospect_id: p._id, message: "" })} title="Kirim pesan" className="text-cyan-400"><Send size={15} /></button>}
  <button onClick={() => optOut(p.tg_user_id)} title="Opt-out" className="text-rose-400"><Ban size={15} /></button>
</td></tr>)}</tbody></table>
            {!prospects.length && <p className="p-5 text-sm text-slate-500">Belum ada prospek.</p>}
          </div>
        </div>
      )}

      {tab === "campaigns" && (
        <div className="space-y-5">
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-3">
            <h2 className="font-semibold">Buat Campaign</h2>
            <input className={cls} placeholder="Nama campaign" value={campaign.name} onChange={(e) => setCampaign({ ...campaign, name: e.target.value })} />
            <select className={cls} value={campaign.product_id} onChange={(e) => setCampaign({ ...campaign, product_id: e.target.value })}><option value="">Broadcast umum (tanpa produk)</option>{products.filter((p) => p.active !== false).map((p) => <option key={p._id} value={p._id}>{p.name}</option>)}</select><textarea className={cls} rows="5" placeholder="Pesan. Variabel: {nama} {username} {bot_link} {produk} {harga_usd} {harga_idr}" value={campaign.template} onChange={(e) => setCampaign({ ...campaign, template: e.target.value })} /><p className="text-xs text-cyan-400">Pilih produk untuk memakai harga otomatis. Gunakan {'{harga_usd}'} dan {'{harga_idr}'} agar broadcast menampilkan kedua harga.</p>
            <div className="grid md:grid-cols-4 gap-2"><input className={cls} placeholder="Source code" value={campaign.source_code} onChange={(e) => setCampaign({ ...campaign, source_code: e.target.value })} /><input className={cls} placeholder="Bot link" value={campaign.bot_link} onChange={(e) => setCampaign({ ...campaign, bot_link: e.target.value })} /><input className={cls} type="number" min="1" max="100" placeholder="Limit/hari" value={campaign.daily_limit} onChange={(e) => setCampaign({ ...campaign, daily_limit: Number(e.target.value) })} /><input className={cls} type="number" min="300" value={campaign.min_interval_seconds} onChange={(e) => setCampaign({ ...campaign, min_interval_seconds: Number(e.target.value) })} /></div>
            <div className="grid md:grid-cols-2 gap-2"><input className={cls} type="time" value={campaign.send_window_start} onChange={(e) => setCampaign({ ...campaign, send_window_start: e.target.value })} /><input className={cls} type="time" value={campaign.send_window_end} onChange={(e) => setCampaign({ ...campaign, send_window_end: e.target.value })} /></div>
            <div className="space-y-2"><p className="text-xs text-slate-500">Akun pengirim</p>{activeAccounts.length ? activeAccounts.map((a) => <label key={a._id} className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={campaign.account_ids.includes(a._id)} onChange={(e) => setCampaign({ ...campaign, account_ids: e.target.checked ? [...campaign.account_ids, a._id] : campaign.account_ids.filter((id) => id !== a._id) })} />{a.name || a.username || a.tg_user_id}</label>) : <p className="text-xs text-amber-400">Belum ada akun Telegram aktif.</p>}</div>
            <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={campaign.approval_required} onChange={(e) => setCampaign({ ...campaign, approval_required: e.target.checked })} /> Perlu approval sebelum pengiriman</label>
            <button onClick={createCampaign} className="bg-cyan-600 hover:bg-cyan-700 rounded-lg px-4 py-2">Buat Campaign</button>
          </div>
          {campaigns.map((c) => <div key={c._id} className="bg-slate-900/80 border border-slate-800 rounded-xl p-4 flex flex-wrap gap-3 items-center justify-between"><div><b>{c.name}</b><p className="text-xs text-slate-500 mt-1">{c.status} · {c.daily_limit}/hari · ≥{c.min_interval_seconds}s · {c.approval_required ? "approval" : "auto"}</p></div><div className="flex gap-2"><button onClick={() => enqueue(c._id)} className="bg-cyan-700 px-3 py-2 rounded-lg text-sm">Buat Queue</button><button onClick={() => stopCampaign(c._id)} className="bg-rose-700 px-3 py-2 rounded-lg text-sm">Stop</button></div></div>)}
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-x-auto"><div className="p-4 border-b border-slate-800 font-semibold">Approval Queue</div><table className="w-full text-sm"><thead><tr className="border-b border-slate-800 text-xs text-slate-500"><th className="p-3 text-left">Prospek</th><th>Campaign</th><th>Status</th><th>Schedule</th><th>Aksi</th></tr></thead><tbody>{jobs.map((j) => <tr key={j._id} className="border-b border-slate-800/70"><td className="p-3">{j.prospect_id}</td><td>{j.campaign_id}</td><td>{j.status}</td><td>{j.scheduled_at || "-"}</td><td>{j.status === "queued" && <button onClick={() => approve(j._id)} className="text-emerald-400"><Check size={16} /></button>}</td></tr>)}</tbody></table>{!jobs.length && <p className="p-5 text-sm text-slate-500">Queue kosong.</p>}</div>
        </div>
      )}

      {tab === "groups" && (
        <div className="space-y-5">
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-3"><h2 className="font-semibold">Posting Grup — manual approval</h2><div className="grid md:grid-cols-[1fr_auto] gap-2">
  <select className={cls} value={post.account_id} onChange={(e) => setPost({ account_id: e.target.value, group_id: "", message: post.message })}><option value="">Pilih akun Telegram</option>{activeAccounts.map((a) => <option key={a._id} value={a._id}>{a.name || a.username || a.tg_user_id}</option>)}</select>
  <button onClick={syncPostGroups} disabled={!post.account_id} className="bg-slate-800 hover:bg-slate-700 disabled:opacity-40 rounded-lg px-4">Sync Grup</button>
</div>
<select className={cls} value={post.group_id} onChange={(e) => setPost({ ...post, group_id: e.target.value })}><option value="">Pilih grup dari akun</option>{postGroups.map((g) => <option key={g._id} value={g.chat_id}>{g.title}{g.username ? " @" + g.username : ""}</option>)}</select><textarea className={cls} rows="5" placeholder="Pesan grup" value={post.message} onChange={(e) => setPost({ ...post, message: e.target.value })} /><button onClick={postGroup} className="bg-cyan-600 rounded-lg py-2">Posting</button></div>
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5"><h2 className="font-semibold">Grup tersinkron</h2><div className="mt-3 space-y-2">{postGroups.map((g) => <div key={g._id} className="flex justify-between border-b border-slate-800 py-2 text-sm"><span>{g.title || g.chat_id}</span><span className="text-slate-500">{g.account_id}</span></div>)}{!postGroups.length && <p className="text-sm text-slate-500">Belum ada grup untuk akun yang dipilih. Klik Sync Grup.</p>}</div></div>
        </div>
      )}

      {tab === "coupons" && (
        <div className="space-y-5">
          <div className="grid xl:grid-cols-[420px_1fr] gap-5">
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-3">
              <div className="flex items-center justify-between gap-2"><h2 className="font-semibold">{editingCouponId ? "Edit Kupon" : "Buat Kupon"}</h2>{editingCouponId && <button onClick={cancelCouponEdit} className="text-xs text-slate-400 hover:text-white">Batal</button>}</div>
              <input className={cls} placeholder="Kode kupon" value={coupon.code} onChange={(e) => setCoupon({ ...coupon, code: e.target.value })} />
              <div className="grid grid-cols-2 gap-2"><select className={cls} value={coupon.type} onChange={(e) => setCoupon({ ...coupon, type: e.target.value })}><option value="percent">Persentase</option><option value="fixed">Nominal</option></select><input className={cls} type="number" min="0.01" max={coupon.type === "percent" ? 100 : undefined} step="any" placeholder={coupon.type === "percent" ? "Diskon %" : "Nilai diskon"} value={coupon.value} onChange={(e) => setCoupon({ ...coupon, value: e.target.value })} /></div>
              <div className="grid grid-cols-2 gap-2"><select className={cls} value={coupon.currency} onChange={(e) => setCoupon({ ...coupon, currency: e.target.value })}><option>IDR</option><option>USD</option></select><input className={cls} type="number" min="1" placeholder="Batas penggunaan/user" value={coupon.per_user_limit} onChange={(e) => setCoupon({ ...coupon, per_user_limit: e.target.value })} /></div>
              <div className="grid grid-cols-2 gap-2"><input className={cls} type="number" min="1" placeholder="Kuota total (kosong = tanpa batas)" value={coupon.quota_total} onChange={(e) => setCoupon({ ...coupon, quota_total: e.target.value })} /><input className={cls} type="number" min="0" step="any" placeholder="Minimum belanja" value={coupon.min_purchase} onChange={(e) => setCoupon({ ...coupon, min_purchase: e.target.value })} /></div>
              {coupon.type === "percent" && <input className={cls} type="number" min="0.01" step="any" placeholder="Maksimum potongan (opsional)" value={coupon.max_discount} onChange={(e) => setCoupon({ ...coupon, max_discount: e.target.value })} />}
              <div><label className="mb-1 block text-xs font-medium text-slate-300">Cakupan produk</label><select multiple className={`${cls} h-32`} value={coupon.product_ids} onChange={(e) => setCoupon({ ...coupon, product_ids: Array.from(e.target.selectedOptions, (option) => option.value) })}>{products.map((p) => <option key={p._id} value={p._id}>{p.name}</option>)}</select><p className="mt-1 text-xs text-slate-500">Tidak memilih produk berarti kupon berlaku universal. Pilih satu atau beberapa produk untuk membatasi kupon.</p></div>
              <div className="grid grid-cols-2 gap-2"><label className="text-xs text-slate-400">Mulai berlaku<input className={`${cls} mt-1`} type="datetime-local" value={coupon.starts_at} onChange={(e) => setCoupon({ ...coupon, starts_at: e.target.value })} /></label><label className="text-xs text-slate-400">Berakhir<input className={`${cls} mt-1`} type="datetime-local" value={coupon.ends_at} onChange={(e) => setCoupon({ ...coupon, ends_at: e.target.value })} /></label></div>
              <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={coupon.active} onChange={(e) => setCoupon({ ...coupon, active: e.target.checked })} /> Kupon aktif</label>
              <button onClick={saveCoupon} className="w-full bg-cyan-600 hover:bg-cyan-700 rounded-lg py-2">{editingCouponId ? "Simpan Perubahan" : "Buat Kupon"}</button>
            </div>
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-x-auto"><table className="w-full text-sm"><thead><tr className="border-b border-slate-800 text-xs text-slate-400"><th className="p-3 text-left">Kupon</th><th>Cakupan</th><th>Pemakaian</th><th>Status</th><th>Aksi</th></tr></thead><tbody>{coupons.map((c) => <tr key={c._id} className="border-b border-slate-800/70"><td className="p-3"><div className="font-mono font-semibold">{c.code}</div><div className="text-xs text-slate-500">{c.type === "percent" ? `${c.value}%` : `${c.currency} ${c.value}`}{c.max_discount ? ` · maks. ${c.currency} ${c.max_discount}` : ""}</div></td><td className="max-w-48 p-3 text-xs">{c.product_ids?.length ? c.product_ids.map((id) => products.find((p) => p._id === id)?.name || "Produk tidak aktif").join(", ") : "Universal"}</td><td className="p-3 text-center">{c.used_count || 0}{c.quota_total == null ? "" : " / " + c.quota_total}<div className="text-xs text-slate-500">min. {c.currency} {c.min_purchase || 0}</div></td><td className="p-3">{c.active ? "Aktif" : "Nonaktif"}</td><td className="p-3"><div className="flex items-center justify-center gap-2"><button title="Edit kupon" onClick={() => editCoupon(c)} className="text-cyan-400">Edit</button><button title={c.active ? "Nonaktifkan" : "Aktifkan"} onClick={() => toggleCoupon(c._id)} className={c.active ? "text-amber-400" : "text-emerald-400"}>{c.active ? <Ban size={15} /> : <Check size={15} />}</button><button title={c.used_count ? "Kupon yang pernah digunakan hanya bisa dinonaktifkan" : "Hapus kupon"} disabled={Number(c.used_count || 0) > 0} onClick={() => deleteCoupon(c._id)} className="text-rose-400 disabled:opacity-30"><Trash2 size={15} /></button></div></td></tr>)}</tbody></table>{!coupons.length && <p className="p-5 text-sm text-slate-500">Belum ada kupon.</p>}</div>
          </div>
          <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-3"><h2 className="font-semibold">Traffic Source</h2><div className="grid md:grid-cols-4 gap-2"><input className={cls} placeholder="code" value={source.code} onChange={(e) => setSource({ ...source, code: e.target.value })} /><input className={cls} placeholder="jenis" value={source.kind} onChange={(e) => setSource({ ...source, kind: e.target.value })} /><input className={cls} placeholder="label" value={source.label} onChange={(e) => setSource({ ...source, label: e.target.value })} /><button onClick={createSource} className="bg-cyan-600 rounded-lg">Tambah Source</button></div><div className="text-xs text-slate-500">{sources.length} source terdaftar.</div></div>
        </div>
      )}

      {tab === "results" && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">{Object.entries(results).map(([key, value]) => <div key={key} className="bg-slate-900/80 border border-slate-800 rounded-xl p-5"><p className="text-2xl font-semibold">{value}</p><p className="text-xs text-slate-500 mt-1">{key}</p></div>)}</div>
          <div className="grid lg:grid-cols-2 gap-5">
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5"><h2 className="font-semibold mb-3">Pembelian per Source</h2>{sources.map((s) => <div key={s._id} className="flex justify-between border-b border-slate-800 py-2 text-sm"><span>{s.label} <span className="text-slate-500">({s.code})</span></span><span className="text-slate-500">source</span></div>)}{!sources.length && <p className="text-sm text-slate-500">Belum ada source.</p>}</div>
            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5"><h2 className="font-semibold mb-3">Event Terbaru</h2>{events.slice(0, 20).map((e) => <div key={e._id} className="border-b border-slate-800 py-2 text-xs"><b>{e.type}</b><span className="text-slate-500 ml-2">{e.created_at}</span></div>)}{!events.length && <p className="text-sm text-slate-500">Belum ada event.</p>}</div>
          </div>
        </div>
      )}
    </div>
  );
}
