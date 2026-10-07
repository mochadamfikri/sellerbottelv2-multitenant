import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, LoaderCircle, X, AlertCircle, ShoppingBag } from "lucide-react";

export function CartToast({ item, onClose }) {
  useEffect(() => { if (!item) return undefined; const timer = setTimeout(onClose, 5000); return () => clearTimeout(timer); }, [item, onClose]);
  if (!item) return null;
  return <div role="status" className="store-toast fixed bottom-5 left-4 right-4 z-[70] mx-auto flex max-w-md items-center gap-3 rounded-2xl border border-emerald-200 bg-white p-4 shadow-xl sm:left-auto sm:right-6"><span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-emerald-50 text-emerald-800"><CheckCircle2 size={26}/></span><div className="min-w-0 flex-1"><p className="text-sm font-bold text-slate-900">Produk telah ditambahkan di keranjang</p><p className="truncate text-xs text-slate-500">{item.name}</p><Link to="/store/cart" onClick={onClose} className="mt-1 inline-flex items-center gap-1 text-xs font-bold text-emerald-800"><ShoppingBag size={13}/> Lihat keranjang →</Link></div><button aria-label="Tutup notifikasi keranjang" onClick={onClose} className="self-start rounded p-1 text-slate-500"><X size={16}/></button></div>;
}

export function CheckoutFeedback({ feedback, onClose }) {
  const [seconds, setSeconds] = useState(10);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    if (feedback?.status !== "success") return undefined;
    setSeconds(10);
    const timer = setInterval(() => setSeconds((value) => Math.max(0, value - 1)), 1000);
    const dismiss = setTimeout(() => close.current(), 10000);
    return () => { clearInterval(timer); clearTimeout(dismiss); };
  }, [feedback?.status, feedback?.orderId]);
  if (!feedback) return null;
  const success = feedback.status === "success";
  const failed = feedback.status === "error";
  return <div className="fixed inset-0 z-[65] grid place-items-center bg-slate-950/60 p-4 backdrop-blur-sm"><section role="dialog" aria-modal="true" aria-labelledby="checkout-feedback-title" className="store-feedback relative w-full max-w-md rounded-3xl border border-slate-200 bg-white p-7 text-center shadow-2xl">
    <button aria-label="Tutup status checkout" onClick={onClose} className="absolute right-3 top-3 rounded-full p-2 text-slate-500 hover:bg-slate-100"><X size={20}/></button>
    {success ? <div className="store-success mx-auto mt-6 grid h-28 w-28 place-items-center rounded-full bg-emerald-50 text-emerald-800"><CheckCircle2 size={68} strokeWidth={1.7}/></div> : failed ? <AlertCircle size={72} className="mx-auto my-6 text-rose-700"/> : <div className="relative mx-auto my-6 h-44 w-44"><div className="store-processing-orbit absolute inset-0 rounded-full border-2 border-dashed border-emerald-200">{(feedback.products || []).slice(0, 3).map((product, index) => <div key={product._id} className="absolute left-1/2 top-1/2 h-14 w-14" style={{ transform: `translate(-50%, -50%) rotate(${index * 120}deg) translateY(-80px)` }}><img src={product.image_url} alt={product.name} className="h-full w-full rounded-xl border border-slate-200 bg-white object-contain p-1 shadow-md"/></div>)}</div><div className="absolute inset-0 grid place-items-center"><LoaderCircle size={46} className="animate-spin text-emerald-800"/></div></div>}
    <h2 id="checkout-feedback-title" className="mt-5 text-xl font-bold text-slate-900">{success ? "Pesanan berhasil diproses" : failed ? "Pesanan belum berhasil diproses" : feedback.status === "pending" ? "Pembayaran berhasil, pesanan diproses" : "Memproses pesanan Anda"}</h2>
    <p className="mt-3 text-sm leading-6 text-slate-500">{feedback.message || (success ? "Detail produk dapat dilihat melalui menu Pesanan." : "Mohon tunggu. Kami sedang memeriksa pembayaran dan menyiapkan pesanan Anda.")}</p>
    {success && <><Link to="/store/orders" onClick={onClose} className="mt-5 inline-block rounded-lg bg-emerald-800 px-5 py-3 text-sm font-semibold text-white">Lihat detail pesanan</Link><p role="status" className="mt-4 text-xs text-slate-500">Popup akan ditutup otomatis dalam {seconds} detik.</p></>}
  </section></div>;
}
