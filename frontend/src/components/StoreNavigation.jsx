import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { Home, PackageSearch, ShoppingBag, CreditCard, ClipboardList, Clock3, UserRound, Menu, X, LogIn, LogOut, UserPlus, ChevronRight } from "lucide-react";
import { fmtIDR } from "../lib/api";

const links = [
  ["Beranda", "/store", Home, "Pilihan dan panduan belanja"],
  ["Katalog", "/store/products", PackageSearch, "Layanan, varian, dan harga"],
  ["Keranjang", "/store/cart", ShoppingBag, "Periksa pilihan sebelum bayar"],
  ["Pesanan", "/store/orders", ClipboardList, "Status dan detail akun produk"],
  ["Deposit", "/store/deposit", CreditCard, "Isi saldo dengan QRIS"],
  ["Transaksi", "/store/transactions", Clock3, "Riwayat belanja dan deposit"],
  ["Profil", "/store/profile", UserRound, "Identitas dan akun terhubung"],
];

export default function StoreNavigation({ count, profile, onLogout, theme, resolvedTheme, setTheme, storeName = "IDSE Marketplace", storeTagline = "" }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);
  const active = (href) => pathname === href || (href === "/store/products" && pathname.startsWith("/store/product/")) || (href === "/store" && pathname === "/");
  return <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur-xl">
    <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
      <Link to="/store" className="flex min-w-0 items-center gap-2.5"><img src="/idse-logo.svg" alt="" className="h-10 w-10 shrink-0"/><span className="text-xs font-bold leading-tight text-slate-900 sm:text-base">{storeName}{storeTagline ? <span className="mt-0.5 hidden text-[10px] font-medium tracking-widest text-slate-500 sm:block">{storeTagline}</span> : null}</span></Link>
      <nav aria-label="Navigasi utama" className="hidden items-center gap-1 xl:flex">{links.filter(([, href]) => ["/store", "/store/products", "/store/orders", "/store/deposit"].includes(href)).map(([label, href, Icon]) => <Link key={href} to={href} aria-current={active(href) ? "page" : undefined} className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${active(href) ? "bg-emerald-50 text-emerald-800" : "text-slate-600 hover:bg-slate-50"}`}><Icon size={17}/>{label}</Link>)}</nav>
      <div className="flex shrink-0 items-center gap-1.5 sm:gap-2"><select aria-label="Tema tampilan" value={theme} onChange={(e) => setTheme(e.target.value)} className="w-16 rounded-lg border border-slate-200 bg-white px-1 py-2 text-xs text-slate-700 sm:w-20"><option value="auto">Auto</option><option value="light">Terang</option><option value="dark">Gelap</option></select><Link to="/store/cart" aria-label={`Keranjang, ${count} item`} className="relative rounded-xl p-2.5 text-slate-700 hover:bg-emerald-50"><ShoppingBag size={21}/><span className="absolute -right-1 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-emerald-800 px-1 text-[9px] font-bold text-white">{count}</span></Link>
        {profile ? <Link to="/store/profile" className="hidden items-center gap-2 rounded-xl border border-slate-200 py-2 pl-2 pr-3 text-sm sm:flex"><UserRound size={19} className="text-emerald-800"/><span className="hidden max-w-24 truncate font-semibold text-slate-700 lg:block">{profile.display_name || profile.first_name || "Akun saya"}</span></Link> : <Link to="/store/login" className="hidden rounded-lg bg-emerald-800 px-4 py-2 text-sm font-semibold text-white sm:block">Masuk</Link>}
        <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Trigger aria-label="Buka menu" className="rounded-lg p-2 text-slate-700 hover:bg-slate-100 xl:hidden"><Menu size={22}/></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-40 bg-slate-950/50 backdrop-blur-sm xl:hidden"/><Dialog.Content data-theme={resolvedTheme} className="storefront-theme fixed bottom-3 left-3 right-3 top-3 z-50 flex flex-col overflow-y-auto rounded-3xl border border-slate-200 bg-white p-5 text-slate-900 shadow-2xl outline-none sm:bottom-auto sm:left-auto sm:max-h-[90dvh] sm:w-[400px] xl:hidden"><div className="flex items-center justify-between"><Dialog.Title className="flex items-center gap-2 text-lg font-bold"><img src="/idse-logo.svg" alt="" className="h-8 w-8"/> Jelajahi {storeName}</Dialog.Title><Dialog.Close aria-label="Tutup menu" className="rounded-full bg-slate-50 p-2"><X size={20}/></Dialog.Close></div><Dialog.Description className="mt-2 text-sm text-slate-500">Semua kebutuhan belanja dan akun Anda.</Dialog.Description>
          {profile && <Link to="/store/profile" onClick={() => setOpen(false)} className="mt-5 flex items-center gap-3 rounded-2xl bg-emerald-50 p-4"><span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-emerald-800 text-white"><UserRound size={22}/></span><span className="min-w-0 flex-1"><b className="block truncate text-sm">{profile.display_name || profile.first_name || profile.email}</b><span className="mt-1 block text-xs text-slate-500">Saldo {fmtIDR(profile.balance_idr)}</span></span><ChevronRight size={18}/></Link>}
          <nav aria-label="Menu mobile" className="mt-4 space-y-1">{links.map(([label, href, Icon, description]) => <Link key={href} to={href} onClick={() => setOpen(false)} aria-current={active(href) ? "page" : undefined} className={`flex items-center gap-3 rounded-xl p-3 ${active(href) ? "bg-emerald-50 text-emerald-900" : "hover:bg-slate-50"}`}><span className="rounded-xl border border-slate-200 bg-white p-2 text-emerald-800"><Icon size={19}/></span><span className="flex-1"><span className="block text-sm font-semibold">{label}</span><span className="mt-0.5 block text-xs text-slate-500">{description}</span></span><ChevronRight size={15} className="text-slate-400"/></Link>)}</nav>
          <div className="mt-4 border-t border-slate-200 pt-4">{profile ? <button onClick={() => { setOpen(false); onLogout(); }} className="flex w-full items-center gap-3 rounded-xl p-3 text-sm font-semibold text-rose-700"><LogOut size={19}/> Keluar dari akun</button> : <div className="flex gap-2"><Link to="/store/login" onClick={() => setOpen(false)} className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-800 p-3 text-sm font-semibold text-white"><LogIn size={17}/> Masuk</Link><Link to="/store/register" onClick={() => setOpen(false)} className="flex flex-1 items-center justify-center gap-2 rounded-xl border border-slate-200 p-3 text-sm font-semibold"><UserPlus size={17}/> Daftar</Link></div>}</div>
        </Dialog.Content></Dialog.Portal></Dialog.Root>
      </div>
    </div>
    <nav aria-label="Akses cepat mobile" className="mx-auto flex max-w-7xl justify-between gap-1 border-t border-slate-100 px-4 py-1.5 sm:px-6 xl:hidden">{links.filter(([, href]) => ["/store/products", "/store/orders", "/store/transactions", "/store/profile"].includes(href)).map(([label, href, Icon]) => <Link key={href} to={href} aria-current={active(href) ? "page" : undefined} className={`flex items-center gap-1.5 rounded-lg px-2 py-2 text-[11px] font-semibold ${active(href) ? "bg-emerald-50 text-emerald-800" : "text-slate-500"}`}><Icon size={15}/>{label}</Link>)}</nav>
  </header>;
}
