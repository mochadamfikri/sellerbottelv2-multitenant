import { useCallback, useEffect, useState } from "react";
import api, { fmtAmount, fmtDate, formatApiErrorDetail } from "../lib/api";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";

const statuses = ["all", "pending", "pending_payment", "paid", "service_waiting", "delivered", "delivery_failed", "failed", "refunded"];

export default function Orders() {
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [orders, setOrders] = useState([]);
  const [detail, setDetail] = useState(null);

  const load = useCallback(() => api.get("/admin/orders", { params: { status, search } }).then(({ data }) => setOrders(data)), [status, search]);
  useEffect(() => { load(); }, [load]);

  const openDetail = async (o) => {
    try {
      const { data } = await api.get("/admin/orders/" + o._id);
      setDetail(data);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail));
    }
  };

  const refund = async (o) => {
    if (!window.confirm("Refund order ini dan kembalikan saldo?")) return;
    try {
      await api.post("/admin/orders/" + o._id + "/refund");
      toast.success("Order direfund");
      load();
    } catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail)); }
  };

  const completeService = async (o) => {
    if (!window.confirm(`Tandai pesanan jasa ${o.invoice_id} selesai? Email penyelesaian akan dikirim setelah status selesai.`)) return;
    try {
      const { data } = await api.post("/admin/orders/" + o._id + "/complete");
      toast.success(data.email_sent ? "Pesanan selesai dan email terkirim." : "Pesanan selesai. Email belum terkirim; periksa konfigurasi SMTP.");
      await load();
      if (detail?._id === o._id) await openDetail(o);
    } catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail)); }
  };

  const retryEmail = async (o) => {
    try {
      await api.post("/admin/orders/" + o._id + "/email/retry");
      toast.success("Email order berhasil dikirim ulang.");
      await load();
      if (detail?._id === o._id) await openDetail(o);
    } catch (err) { toast.error(formatApiErrorDetail(err.response?.data?.detail)); }
  };

  return (
    <>
      <div className="flex gap-2 flex-wrap">
        {statuses.map((s) => <button key={s} onClick={() => setStatus(s)} className={status === s ? "px-3 py-1.5 rounded-lg border border-cyan-500/40 text-cyan-400 text-xs" : "px-3 py-1.5 rounded-lg border border-slate-800 text-slate-400 text-xs"}>{s}</button>)}
        <input className="ml-auto w-64 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm" placeholder="Invoice / email / username / Telegram ID" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b border-slate-800 text-xs text-slate-500 uppercase"><th className="px-4 py-3">Invoice</th><th className="px-4 py-3">User</th><th className="px-4 py-3">Produk</th><th className="px-4 py-3">Total</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Tanggal</th><th className="px-4 py-3 text-right">Aksi</th></tr></thead>
          <tbody>
            {orders.map((o) => <tr key={o._id} className="border-b border-slate-800/60">
              <td className="px-4 py-3 font-mono text-cyan-400">{o.invoice_id}</td>
              <td className="px-4 py-3 text-xs">{o.customer_email || o.username || o.user_tid || "-"}<div className="text-slate-500">{o.user_tid || (o.customer_id ? "Akun web" : "-")}</div></td>
              <td className="px-4 py-3 text-xs">{(o.items || []).map((i) => i.name + " ×" + i.qty).join(", ")}</td>
              <td className="px-4 py-3 font-mono">{fmtAmount(o.total, o.currency)}</td>
              <td className="px-4 py-3"><span className="text-xs uppercase">{o.status}</span></td>
              <td className="px-4 py-3 text-xs text-slate-500">{fmtDate(o.created_at)}</td>
              <td className="px-4 py-3 text-right flex gap-2 justify-end">
                <button className="text-cyan-400 text-xs" onClick={() => openDetail(o)}>Detail</button>
                {o.status === "service_waiting" && <button className="text-emerald-400 text-xs" onClick={() => completeService(o)}>Selesaikan</button>}
                {o.status === "delivered" && o.delivery_email_status === "failed" && <button className="text-amber-400 text-xs" onClick={() => retryEmail(o)}>Kirim email ulang</button>}
                {(o.status === "failed" || o.status === "delivery_failed") && <button className="text-rose-400 text-xs" onClick={() => refund(o)}>Refund</button>}
              </td>
            </tr>)}
            {!orders.length && <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-500">Belum ada order.</td></tr>}
          </tbody>
        </table>
      </div>

      <Dialog open={!!detail} onOpenChange={() => setDetail(null)}>
        <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="font-heading">Detail Transaksi / Invoice</DialogTitle></DialogHeader>
          {detail && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div><span className="text-slate-500">Invoice</span><div className="font-mono text-cyan-400">{detail.invoice_id}</div></div>
                <div><span className="text-slate-500">Order ID</span><div className="font-mono text-xs break-all">{detail._id}</div></div>
                <div><span className="text-slate-500">User</span><div>{detail.customer_email || detail.username || "-"}<div className="text-xs text-slate-500">{detail.user_tid || (detail.customer_id ? "Akun web" : "-")}</div></div></div>
                <div><span className="text-slate-500">Tanggal</span><div>{fmtDate(detail.created_at)}</div></div>
                <div><span className="text-slate-500">Status</span><div className="uppercase">{detail.status}</div></div>
                <div><span className="text-slate-500">Pembayaran</span><div>{detail.payment_method} · {detail.currency}</div></div>
              </div>
              <div className="border-t border-slate-800 pt-3">
                <p className="font-semibold mb-2">Produk yang dibeli</p>
                <div className="space-y-2">
                  {(detail.items || []).map((i, idx) => <div key={idx} className="bg-slate-950/70 rounded-lg p-3">
                    <div className="font-semibold">{i.name} × {i.qty}</div>
                    <div className="text-xs text-slate-400 mt-1">Harga/unit: {fmtAmount(i.unit_price, detail.currency)} · Subtotal: {fmtAmount(i.subtotal, detail.currency)}</div>
                    {Number(i.discount_total || 0) > 0 && <div className="text-xs text-emerald-400">Diskon: {fmtAmount(i.discount_total, detail.currency)}{i.discount_name ? " · " + i.discount_name : ""}</div>}
                    <div className="text-[11px] text-slate-600 mt-1">Product ID: {i.product_id}</div>
                  </div>)}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 border-t border-slate-800 pt-3">
                <div>Total diskon: <b>{fmtAmount(detail.discount_total || 0, detail.currency)}</b></div>
                <div>Coupon: <b>{detail.coupon_code || "-"}</b></div>
                <div>Total transaksi: <b className="text-cyan-400">{fmtAmount(detail.total, detail.currency)}</b></div>
                <div>Paid at: {detail.paid_at ? fmtDate(detail.paid_at) : "-"}</div>
                <div>Delivered at: {detail.delivered_at ? fmtDate(detail.delivered_at) : "-"}</div>
                <div>Delivery error: {detail.delivery_error || "-"}</div>
                <div>Email order: {detail.delivery_email_status || "-"}</div>
                <div>Email error: {detail.delivery_email_error || "-"}</div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
