import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { Search, ShoppingBag, ArrowRight, Plus, Minus, PackageCheck, PackageX, TrendingUp, Sparkles, Headset, CreditCard, Trash2, X, QrCode, LoaderCircle } from "lucide-react";
import api, { fmtIDR, fmtUSD, formatApiErrorDetail } from "../lib/api";
import { catalogKey, catalogHref, groupCatalogs, variantLabel } from "../lib/catalog";
import { CartToast, CheckoutFeedback } from "../components/StoreFeedback";
import OrderDelivery from "../components/OrderDelivery";
import StoreNavigation from "../components/StoreNavigation";
import StoreProductDialog from "../components/StoreProductDialog";
import StoreHome from "../components/StoreHome";
import StoreProfile from "../components/StoreProfile";
import "../storefront.css";

const page = "min-h-screen bg-[#f7f8f6] text-slate-800";
const button = "inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-800 px-5 py-3 font-semibold text-white shadow-sm transition hover:bg-emerald-900 focus:outline-none focus:ring-2 focus:ring-emerald-700 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";
const secondary = "inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 font-semibold text-slate-700 transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-emerald-700 focus:ring-offset-2";
const input = "w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-emerald-700 focus:ring-2 focus:ring-emerald-700/15";

function money(product, currency) {
  const value = product[`price_${currency.toLowerCase()}_current`] ?? product[`price_${currency.toLowerCase()}`];
  return currency === "USD" ? fmtUSD(value) : fmtIDR(value);
}

function productTypeLabel(product) {
  if (product?.product_kind === "service") return "Jasa Payment";
  const kind = String(product?.delivery_type || product?.product_type || "").toLowerCase();
  if (kind.includes("account") || kind.includes("akun")) return "Akun Digital";
  if (kind.includes("session")) return "Session File";
  if (kind.includes("license") || kind.includes("lisensi")) return "Lisensi Digital";
  if (kind.includes("file")) return "File Digital";
  return "Produk Digital";
}

function ProductArtwork({ product, brand = "IDSE Marketplace" }) {
  const isService = product?.product_kind === "service";
  const Icon = isService ? Headset : PackageCheck;
  const initials = String(product?.name || brand).trim().split(/\s+/).slice(0, 2).map((word) => word[0]).join("").toUpperCase();
  return <div aria-hidden="true" className="relative flex h-full w-full items-center justify-center overflow-hidden bg-[#eef4ef]">
    <div className="absolute -right-10 -top-12 h-40 w-40 rounded-full bg-white/70"/>
    <div className="absolute -bottom-14 -left-12 h-44 w-44 rounded-full border-[24px] border-emerald-900/[.04]"/>
    <div className="relative flex max-w-[85%] flex-col items-center text-center">
      <span className="grid h-16 w-16 place-items-center rounded-2xl border border-emerald-900/10 bg-white text-emerald-900 shadow-sm"><Icon size={31} strokeWidth={1.6}/></span>
      <span className="mt-3 max-w-full truncate text-2xl font-black tracking-[.12em] text-emerald-950">{initials || brand}</span>
      <span className="mt-1 max-w-full truncate text-[10px] font-semibold uppercase tracking-[.16em] text-slate-500">{productTypeLabel(product)}</span>
    </div>
  </div>;
}

function ProductCard({ product, add, onOpen, adding = false, brand = "IDSE Marketplace" }) {
  const minimum = Math.max(1, Number(product.minimum_purchase_qty || 1));
  const noStock = product.stock != null && Number(product.stock) < minimum;
  return <article className="group overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
    <Link to={`/store/product/${product._id}`} onClick={(event) => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) { event.preventDefault(); onOpen(product); } }} className="relative block aspect-[4/3] overflow-hidden bg-slate-100">
      <ProductArtwork product={product} brand={brand}/>
      {product.image_url && <img src={product.image_url} alt={product.name} className="absolute inset-0 h-full w-full bg-white object-contain p-3 transition group-hover:scale-[1.02] sm:p-5" loading="lazy" onError={(event) => { event.currentTarget.style.display = "none"; }}/ >}
      <div className="absolute left-3 top-3 flex flex-wrap gap-1.5"><span className="rounded-md border border-slate-200 bg-white/95 px-2.5 py-1 text-[11px] font-semibold text-slate-700">{productTypeLabel(product)}</span><span className={`rounded-md border border-white/70 bg-white/95 px-2.5 py-1 text-[11px] font-semibold ${noStock ? "text-rose-700" : "text-emerald-800"}`}>{noStock ? "Out of Stock" : "Ready Stock"}</span></div>
    </Link>
    <div className="p-4 sm:p-5">
      <Link to={`/store/product/${product._id}`} onClick={(event) => { if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) { event.preventDefault(); onOpen(product); } }} className="line-clamp-1 font-semibold text-slate-900 hover:text-emerald-800">{product.name}</Link>
      <span className="mt-2 inline-block rounded-md bg-emerald-50 px-2 py-1 text-[10px] font-semibold text-emerald-800">{variantLabel(product)}</span><p className="mt-2 line-clamp-2 min-h-10 text-sm leading-5 text-slate-500">{product.description || `Produk pilihan ${brand}.`}</p>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className={`text-xs font-medium ${noStock ? "text-rose-700" : "text-slate-500"}`}>{noStock ? "Stok belum mencukupi" : product.stock == null ? "Stok tersedia" : `Stok ${product.stock}`}</span>
        {minimum > 1 && <span className="text-xs text-slate-500">Min. {minimum} pcs</span>}
      </div>
      <div className="mt-4 flex items-end justify-between gap-3 border-t border-slate-100 pt-3">
        <div><p className="text-[11px] text-slate-500">Harga mulai</p><p className="font-bold text-emerald-900">{money(product, "IDR")}</p></div>
        <button className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-900 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-45" onClick={() => add(product)} disabled={noStock || adding} aria-busy={adding} aria-label={`Tambah ${product.name} ke keranjang`}>{adding ? <LoaderCircle size={16} className="animate-spin"/> : <Plus size={16}/>} {adding ? "Menambah…" : "Tambah"}</button>
      </div>
    </div>
  </article>;
}

function CatalogCard({ catalog }) {
  const representative = catalog.products.find((p) => p.image_url) || catalog.products[0];
  const ready = catalog.products.filter((p) => p.stock == null || Number(p.stock) >= Math.max(1, Number(p.minimum_purchase_qty || 1))).length;
  const price = Math.min(...catalog.products.map((p) => Number(p.price_idr_current ?? p.price_idr ?? 0)));
  return <Link to={catalogHref(catalog.name)} className="group overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
    <div className="relative h-32 overflow-hidden sm:h-40"><ProductArtwork product={{ ...representative, name: catalog.name }}/>{representative.image_url && <img src={representative.catalog_image_url || representative.image_url} alt="" className="absolute inset-0 h-full w-full bg-white object-contain p-4" loading="lazy" onError={(e) => { e.currentTarget.style.display = "none"; }}/>}</div>
    <div className="p-3 sm:p-5"><h3 className="text-base font-bold sm:text-lg text-slate-900">{catalog.name}</h3><p className="mt-2 text-sm text-slate-500">{catalog.products.length} varian · {ready ? `${ready} tersedia` : "Stok habis"}</p><div className="mt-3 flex flex-wrap gap-1">{catalog.products.slice(0,2).map((p) => <span key={p._id} className="rounded-md bg-slate-50 px-2 py-1 text-[9px] font-medium text-slate-600">{variantLabel(p)}</span>)}{catalog.products.length > 2 && <span className="rounded-md bg-slate-50 px-2 py-1 text-[9px] text-slate-500">+{catalog.products.length-2} varian</span>}</div><div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-4"><span className="text-sm text-emerald-900">Mulai <b>{fmtIDR(price)}</b></span><span className="inline-flex items-center gap-1 text-sm font-semibold text-emerald-800">Lihat pilihan <ArrowRight size={16}/></span></div></div>
  </Link>;
}

function statusLabel(value) {
  return ({ delivered: "Selesai", completed: "Selesai", service_waiting: "Diproses", pending_payment: "Menunggu pembayaran", paid: "Dibayar", pending: "Menunggu", approved: "Berhasil", expired: "Kedaluwarsa", failed: "Gagal", delivery_failed: "Perlu bantuan", rejected: "Ditolak", cancelled: "Dibatalkan", refunded: "Dikembalikan" })[value] || value || "—";
}

function dateLabel(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
}

export default function Storefront({ view = "home", tenantView = false }) {
  const { tenantSlug } = useParams();
  // Deteksi apakah di tenant subdomain (*.idseconnect.my.id)
  // Resolusi tenant-nya via backend Host header (domain_registry)
  const isTenantHost = (() => {
    try {
      const host = window.location.hostname.toLowerCase();
      return host.endsWith(".idseconnect.my.id")
        && host !== "idseconnect.my.id"
        && !host.startsWith("panel.");
    } catch (_) { return false; }
  })();
  const effectiveSlug = tenantSlug || null;
  const isTenantStore = (tenantView && !!tenantSlug) || isTenantHost;
  // API path prefix: tenant via URL pakai /api/store/t/{slug},
  // tenant via subdomain pakai /api/store (backend resolve via Host header)
  const apiPrefix = (tenantView && tenantSlug) ? `/store/t/${tenantSlug}` : "/store";
  const [theme, setTheme] = useState(() => { try { const saved = localStorage.getItem("idse_theme"); return ["auto", "light", "dark"].includes(saved) ? saved : "auto"; } catch (_) { return "auto"; } });
  const [systemDark, setSystemDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [addingIds, setAddingIds] = useState([]);
  const [cartToast, setCartToast] = useState(null);
  const [checkoutFeedback, setCheckoutFeedback] = useState(null);
  const addTimers = useRef(new Map());
  const feedbackProducts = useRef([]);
  const closeCartToast = useCallback(() => setCartToast(null), []);
  const [products, setProducts] = useState([]);
  const [productLoading, setProductLoading] = useState(true);
  const [cart, setCart] = useState(() => { try { return JSON.parse(localStorage.getItem("store_cart") || "[]"); } catch { return []; } });
  const cartRef = useRef(cart);
  cartRef.current = cart;
  const [search, setSearch] = useState("");
  const [productFilter, setProductFilter] = useState("all");
  const [catalogPage, setCatalogPage] = useState(1);
  const [profile, setProfile] = useState(null);
  const [orders, setOrders] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const currency = "IDR";
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [botName, setBotName] = useState("");
  const [storeName, setStoreName] = useState("IDSE Marketplace");
  const [storeTagline, setStoreTagline] = useState("");
  const [contactConfig, setContactConfig] = useState({ whatsapp_contact_number: "", telegram_contact_target: "" });
  const [broadcast, setBroadcast] = useState("");
  const [channelGate, setChannelGate] = useState(null);
  const [gateDismissed, setGateDismissed] = useState(() => sessionStorage.getItem("channel_gate_ok") === "1");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [resetMode, setResetMode] = useState(false);
  const [linkCode, setLinkCode] = useState("");
  const [checkoutKey, setCheckoutKey] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("qris");
  const [couponCode, setCouponCode] = useState("");
  const [depositAmount, setDepositAmount] = useState("50000");
  const [deposit, setDeposit] = useState(null);
  const [depositRows, setDepositRows] = useState([]);
  const [quote, setQuote] = useState(null);
  const [quoteError, setQuoteError] = useState("");
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [checkoutPayment, setCheckoutPayment] = useState(null);
  const [qrisDialogOpen, setQrisDialogOpen] = useState(false);
  const [expiryTick, setExpiryTick] = useState(0);
  const [selected, setSelected] = useState(null);
  const [transactionFilter, setTransactionFilter] = useState("all");
  const navigate = useNavigate();
  const location = useLocation();
  const displayView = view === "detail" ? (location.state?.backgroundView || "products") : view;
  const routeSearch = view === "detail" ? (location.state?.backgroundSearch || "") : location.search;
  const selectedCatalog = new URLSearchParams(routeSearch).get("catalog");
  const searchQuery = new URLSearchParams(routeSearch).get("q") || "";
  const resolvedTheme = theme === "auto" ? (systemDark ? "dark" : "light") : theme;
  const openProduct = (product) => {
    setError("");
    api.post("/analytics/track", {
      channel: "web_store", event_type: "click", product_id: product._id, product_name: product.name,
    }).catch(() => {});
    navigate(`/store/product/${product._id}`, { state: view === "detail" ? location.state : { productOrigin: location.pathname + location.search, backgroundView: view, backgroundSearch: location.search }, replace: view === "detail" });
  };
  const closeProduct = () => {
    if (location.state?.productOrigin) navigate(-1);
    else {
      const product = products.find((p) => p._id === productId);
      navigate(product ? catalogHref(product.catalog_name) : "/store/products", { replace: true });
    }
  };
  const { productId } = useParams();

  useEffect(() => { document.title = storeName; try { localStorage.setItem("idse_theme", theme); } catch (_) {} }, [theme, storeName]);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = (event) => setSystemDark(event.matches);
    media.addEventListener("change", listener);
    const timers = addTimers.current;
    return () => { media.removeEventListener("change", listener); timers.forEach(clearTimeout); };
  }, []);

  useEffect(() => {
    const deadlines = [deposit, checkoutPayment, selected]
      .filter((payment) => payment?.status === "pending" || payment?.status === "pending_payment")
      .map((payment) => Date.parse(payment.expires_at || ""))
      .filter((deadline) => Number.isFinite(deadline) && deadline > Date.now());
    if (!deadlines.length) return undefined;
    const timer = window.setTimeout(() => setExpiryTick((value) => value + 1), Math.min(...deadlines) - Date.now() + 25);
    return () => window.clearTimeout(timer);
  }, [deposit, checkoutPayment, selected, expiryTick]);

  const loadProducts = useCallback(async (term = "") => {
    setProductLoading(true);
    try { const { data } = await api.get(`${apiPrefix}/products`, { params: term ? { search: term } : {} }); setProducts(data); setError(""); }
    catch (e) { setError(formatApiErrorDetail(e.response?.data?.detail) || "Katalog belum dapat dimuat."); }
    finally { setProductLoading(false); }
  }, [apiPrefix]);

  const loadProfile = useCallback(async () => {
    const { data } = await api.get("/store/me");
    setProfile(data);
    return data;
  }, []);

  useEffect(() => { loadProducts(); }, [loadProducts]);
  useEffect(() => {
    const channel = view === "profile" ? "web_profile" : "web_store";
    api.post("/analytics/track", { channel, event_type: "page_view", path: location.pathname }).catch(() => {});
  }, [view, location.pathname]);
  useEffect(() => { setSearch(searchQuery); setProductFilter("all"); }, [selectedCatalog, searchQuery]);
  useEffect(() => { setCatalogPage(1); }, [search, productFilter, selectedCatalog]);
  useEffect(() => { localStorage.setItem("store_cart", JSON.stringify(cart)); }, [cart]);
  useEffect(() => { api.get(`${apiPrefix}/config`).then(({data}) => { setBotName(data.telegram_bot_username || ""); setContactConfig(data); setStoreName(data.store_name || data.tenant_name || (isTenantStore ? "Toko" : "IDSE Marketplace")); setStoreTagline(data.store_tagline || ""); setBroadcast(data.broadcast_enabled ? data.broadcast_message : ""); setChannelGate(data.require_channel_join ? { url: data.channel_url, name: data.channel_name || "Channel Telegram" } : null); }).catch(() => {}); }, [apiPrefix, isTenantStore]);
  useEffect(() => { loadProfile().catch(() => setProfile(null)); }, [loadProfile]);
  useEffect(() => {
    if (!["profile", "orders", "deposit", "transactions"].includes(view)) return;
    loadProfile().catch(() => navigate("/store/login", { state: { from: location.pathname } }));
    if (view === "orders") api.get("/store/orders").then(({data}) => setOrders(data)).catch(() => {});
    if (view === "transactions") api.get("/store/transactions").then(({data}) => setTransactions(data)).catch((e) => setError(formatApiErrorDetail(e.response?.data?.detail)));
    if (view === "deposit") api.get("/store/deposits").then(({data}) => setDepositRows(data)).catch(() => {});
  }, [view, loadProfile, navigate, location.pathname]);

  useEffect(() => {
    if (view !== "orders") return undefined;
    const timer = window.setInterval(async () => {
      try { const { data } = await api.get("/store/orders"); setOrders(data); }
      catch (_) {}
    }, 10000);
    return () => window.clearInterval(timer);
  }, [view]);

  useEffect(() => {
    if (selected?.type !== "order") return;
    const current = orders.find((order) => order._id === (selected._id || selected.id));
    if (current && current.status !== selected.status) setSelected({ ...selected, ...current });
  }, [orders, selected]);

  useEffect(() => {
    if (!deposit || deposit.status !== "pending") return undefined;
    const timer = window.setInterval(async () => {
      try {
        const { data } = await api.get("/store/deposits");
        setDepositRows(data);
        const current = data.find((row) => row.deposit_id === deposit.deposit_id);
        if (current && current.status !== "pending") {
          setDeposit((value) => ({ ...value, status: current.status }));
          if (current.status === "approved") loadProfile().catch(() => {});
        }
      } catch (_) {}
    }, 5000);
    return () => window.clearInterval(timer);
  }, [deposit, loadProfile]);

  useEffect(() => {
    if (view !== "cart" || !cart.length) { setQuote(null); setQuoteError(""); setQuoteLoading(false); return undefined; }
    let active = true;
    setQuoteLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const { data } = await api.post("/store/quote", {
          items: cart, currency: "IDR", coupon_code: couponCode.trim() || null,
        });
        if (active) { setQuote(data); setQuoteError(""); }
      } catch (err) {
        if (active) { setQuote(null); setQuoteError(formatApiErrorDetail(err.response?.data?.detail) || "Harga keranjang belum dapat dihitung."); }
      } finally { if (active) setQuoteLoading(false); }
    }, 180);
    return () => { active = false; window.clearTimeout(timer); };
  }, [view, cart, couponCode]);

  useEffect(() => {
    if (!checkoutPayment || !["pending_payment", "paid", "service_waiting", "processing"].includes(checkoutPayment.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const { data } = await api.get("/store/orders");
        setOrders(data);
        const current = data.find((row) => row._id === checkoutPayment._id);
        if (current && current.status !== checkoutPayment.status) {
          if (["delivered", "completed", "delivery_failed"].includes(current.status)) {
            setQrisDialogOpen(false);
            setCheckoutFeedback({ status: current.status === "delivery_failed" ? "error" : "success", orderId: current._id, products: feedbackProducts.current, message: `Invoice ${current.invoice_id} · ${statusLabel(current.status)}` });
          }
          setCheckoutPayment((value) => value ? { ...value, status: current.status } : value);
          if (current.status === "delivered") setNotice("Pembayaran QRIS terverifikasi. Pesanan selesai; periksa email Anda.");
          else if (current.status === "service_waiting") setNotice("Pembayaran terverifikasi. Pesanan layanan sedang diproses.");
          else if (current.status === "delivery_failed") setNotice("Pembayaran terverifikasi, tetapi pengiriman perlu bantuan tim. Hubungi admin.");
        }
      } catch (_) {}
    }, 5000);
    return () => window.clearInterval(timer);
  }, [checkoutPayment]);

  const filteredProducts = useMemo(() => {
    const isOut = (product) => product.stock != null && Number(product.stock) < Math.max(1, Number(product.minimum_purchase_qty || 1));
    let result = products.filter((product) => {
      if (selectedCatalog && catalogKey(product.catalog_name) !== selectedCatalog) return false;
      const term = search.trim().toLocaleLowerCase("id-ID");
      if (term && !`${product.name} ${product.description || ""} ${product.catalog_name || ""}`.toLocaleLowerCase("id-ID").includes(term)) return false;
      if (productFilter === "out") return isOut(product);
      if (productFilter === "ready") return !isOut(product);
      if (productFilter === "service") return product.product_kind === "service";
      return true;
    });
    if (productFilter === "bestseller") {
      return result.sort((a, b) => Number(b.sales_count || 0) - Number(a.sales_count || 0) || Number(isOut(a)) - Number(isOut(b)));
    }
    return result.sort((a, b) => Number(isOut(a)) - Number(isOut(b)) || (selectedCatalog ? a.name.localeCompare(b.name, "id", { numeric: true }) : 0));
  }, [products, productFilter, search, selectedCatalog]);
  const catalogs = useMemo(() => groupCatalogs(filteredProducts), [filteredProducts]);
  const selectedCatalogName = products.find((p) => catalogKey(p.catalog_name) === selectedCatalog)?.catalog_name || "Katalog";
  const listing = selectedCatalog ? filteredProducts : catalogs;
  const pageCount = Math.max(1, Math.ceil(listing.length / 12));
  const currentPage = Math.min(catalogPage, pageCount);
  const visibleListing = listing.slice((currentPage - 1) * 12, currentPage * 12);
  const depositExpired = deposit?.status === "pending" && Number.isFinite(Date.parse(deposit.expires_at || "")) && Date.parse(deposit.expires_at || "") <= Date.now();
  const checkoutExpired = checkoutPayment?.status === "pending_payment" && Number.isFinite(Date.parse(checkoutPayment.expires_at || "")) && Date.parse(checkoutPayment.expires_at || "") <= Date.now();
  const setCartAndResetKey = (next) => { setCheckoutKey(""); setCart(next); };
  const add = (product, quantity) => {
    if (addTimers.current.has(product._id) || busy) return;
    const minimum = Math.max(1, Number(product.minimum_purchase_qty || 1));
    const maximum = Math.min(100, product.stock == null ? 100 : Number(product.stock));
    const increment = quantity == null ? 1 : Math.max(minimum, Number(quantity) || minimum);
    if (maximum < minimum || (cartRef.current.find((item) => item.pid === product._id)?.qty || 0) + increment > maximum) { setError("Jumlah di keranjang sudah mencapai stok tersedia."); return; }
    setAddingIds((ids) => [...ids, product._id]);
    api.post("/analytics/track", {
      channel: "web_store", event_type: "add_to_cart", product_id: product._id, product_name: product.name,
    }).catch(() => {});
    const timer = setTimeout(() => {
      addTimers.current.delete(product._id); setAddingIds((ids) => ids.filter((id) => id !== product._id));
      const items = cartRef.current;
      const existing = items.find((item) => item.pid === product._id);
      const next = existing ? items.map((item) => item.pid === product._id ? { ...item, qty: Math.min(maximum, Math.max(minimum, item.qty + increment)) } : item) : [...items, { pid: product._id, qty: Math.max(minimum, increment) }];
      cartRef.current = next; setCartAndResetKey(next); setCartToast({ name: product.name, key: Date.now() });
    }, 5000);
    addTimers.current.set(product._id, timer);
  };
  const changeQty = (pid, delta) => setCartAndResetKey((items) => items.map((item) => {
    if (item.pid !== pid) return item;
    const product = products.find((row) => row._id === pid);
    const max = product?.stock == null ? 100 : Number(product.stock);
    const minimum = Math.max(1, Number(product?.minimum_purchase_qty || 1));
    return { ...item, qty: Math.max(minimum, Math.min(max, item.qty + delta)) };
  }).filter((item) => item.qty > 0));
  const removeCartItem = (pid) => setCartAndResetKey((items) => items.filter((item) => item.pid !== pid));

  const submitAccountForm = async (event) => {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      if (resetMode) {
        if (!codeSent) { await api.post("/store/password/request-code", {email}); setCodeSent(true); setNotice("Jika email terdaftar, kode reset akan dikirim."); }
        else { await api.post("/store/password/reset", {email, code, password}); setResetMode(false); setCodeSent(false); setCode(""); setPassword(""); setNotice("Kata sandi berhasil diubah. Silakan masuk."); }
      } else if (view === "register") {
        if (!codeSent) { await api.post("/store/register/request-code", {email}); setCodeSent(true); setNotice("Kode verifikasi terkirim. Periksa inbox dan folder spam."); }
        else { await api.post("/store/register/verify", {email, code, password}); await loadProfile(); navigate("/store/profile"); }
      } else { await api.post("/store/login", {email, password}); await loadProfile(); navigate(location.state?.from || "/store/profile"); }
    } catch (e) { setError(formatApiErrorDetail(e.response?.data?.detail) || "Permintaan gagal. Periksa kembali data yang dimasukkan."); }
    finally { setBusy(false); }
  };

  const createLinkCode = async () => {
    try { const {data} = await api.post("/store/link-code"); setLinkCode(data.code); setBotName(data.bot_username || botName); setError(""); }
    catch (e) { setError(formatApiErrorDetail(e.response?.data?.detail)); }
  };

  const checkout = async () => {
    if (busy || addingIds.length) return;
    if (!profile) { navigate("/store/login", { state: { from: "/store/cart" } }); return; }
    const invalid = cart.find((item) => {
      const product = products.find((row) => row._id === item.pid);
      return !product || item.qty < Math.max(1, Number(product.minimum_purchase_qty || 1)) || (product.stock != null && item.qty > product.stock);
    });
    if (invalid) { setError("Periksa minimum pembelian dan stok setiap produk di keranjang."); return; }
    const key = checkoutKey || (window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
    setCheckoutKey(key); setBusy(true); setError("");
    feedbackProducts.current = cart.map((item) => products.find((product) => product._id === item.pid)).filter(Boolean);
    setCheckoutFeedback({ status: "processing", products: feedbackProducts.current });
    try {
      const {data} = await api.post("/store/checkout", {items: cart, currency: "IDR", payment_method: paymentMethod, coupon_code: couponCode.trim() || null, idempotency_key: key});
      setCartAndResetKey([]); setCouponCode(""); setCheckoutKey(""); setQuote(null);
      if (data.status === "pending_payment" && data.qr_image) { setCheckoutFeedback(null); setCheckoutPayment(data); setQrisDialogOpen(true); }
      else { if (["paid", "processing", "service_waiting"].includes(data.status)) setCheckoutPayment(data); setCheckoutFeedback({ status: ["delivered", "completed"].includes(data.status) ? "success" : data.status === "delivery_failed" ? "error" : "pending", orderId: data._id, products: feedbackProducts.current, message: `Invoice ${data.invoice_id} · ${statusLabel(data.status)}` }); setNotice(`Pesanan ${data.invoice_id} berstatus ${statusLabel(data.status)}.`); navigate("/store/orders"); }
    } catch (e) { if (e.response?.status === 409 || (paymentMethod === "balance" && e.response?.status === 400)) setCheckoutKey(""); const message = formatApiErrorDetail(e.response?.data?.detail) || "Checkout gagal. Periksa saldo, stok, atau kupon lalu coba lagi."; setError(message); setCheckoutFeedback({ status: "error", products: feedbackProducts.current, message }); }
    finally { setBusy(false); }
  };

  const createDeposit = async (event) => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const {data} = await api.post("/store/deposits", {amount_idr: Number(depositAmount)});
      setDeposit(data);
      setNotice("QRIS dibuat. Bayar sesuai nominal yang tertera sebelum kedaluwarsa.");
    } catch (e) { setError(formatApiErrorDetail(e.response?.data?.detail) || "QRIS gagal dibuat."); }
    finally { setBusy(false); }
  };

  const logout = async () => { await api.post("/store/logout").catch(() => {}); setProfile(null); navigate("/store"); };
  const cartTotal = cart.reduce((sum, item) => {
    const product = products.find((row) => row._id === item.pid);
    const price = product?.[`price_${currency.toLowerCase()}_current`] ?? product?.[`price_${currency.toLowerCase()}`] ?? 0;
    return sum + Number(price || 0) * Number(item.qty || 0);
  }, 0);
  const focusedProduct = products.find((product) => product._id === productId);
  const contactItems = checkoutPayment?.items?.length
    ? checkoutPayment.items.map((item) => ({ name: item.name || "Produk", qty: Number(item.qty || 1), unit_price: Number(item.unit_price || 0), subtotal: Number(item.subtotal || 0) }))
    : view === "deposit"
      ? [{ name: "Deposit saldo IDR", qty: 1, unit_price: Number(deposit?.amount || depositAmount || 0), subtotal: Number(deposit?.amount || depositAmount || 0) }]
      : view === "detail" && focusedProduct
        ? [{ name: focusedProduct.name, qty: Number(cart.find((item) => item.pid === focusedProduct._id)?.qty || 1), unit_price: Number(focusedProduct.price_idr_current ?? focusedProduct.price_idr ?? 0), subtotal: Number(focusedProduct.price_idr_current ?? focusedProduct.price_idr ?? 0) * Number(cart.find((item) => item.pid === focusedProduct._id)?.qty || 1) }]
        : cart.map((item) => {
          const product = products.find((row) => row._id === item.pid);
          const unit = Number(product?.price_idr_current ?? product?.price_idr ?? 0);
          return { name: product?.name || "Produk", qty: Number(item.qty || 1), unit_price: unit, subtotal: unit * Number(item.qty || 1) };
        });
  const contactName = profile?.display_name || profile?.first_name || profile?.email || "belum masuk";
  const contactQuantity = contactItems.reduce((sum, item) => sum + item.qty, 0);
  const contactTotal = view === "deposit" ? Number(deposit?.amount || depositAmount || 0) : (checkoutPayment?.total || quote?.total || contactItems.reduce((sum, item) => sum + item.subtotal, 0));
  const contactPaymentMethod = view === "deposit" ? "QRIS (deposit saldo)" : checkoutPayment ? `QRIS (${statusLabel(checkoutPayment.status)})` : cart.length ? "QRIS saat checkout" : "Belum dipilih";
  const contactProductText = contactItems.length
    ? contactItems.map((item) => `${item.name} — harga/unit ${fmtIDR(item.unit_price)}, jumlah ${item.qty}, subtotal ${fmtIDR(item.subtotal)}`).join("\n")
    : "Belum dipilih (silakan tulis produk yang ditanyakan)";
  const whatsappMessage = `Halo, saya ${contactName}, ingin menanyakan/memesan product:\n${contactProductText}\nHarga: ${fmtIDR(contactTotal)}\nTotal barang: ${contactQuantity}\nPembayaran: ${contactPaymentMethod}\nTolong segera di cek/di proses ya. Terimakasih.`;
  const reopenQris = async (orderId) => {
    try { const { data } = await api.get(`/store/orders/${orderId}/qris`); setCheckoutPayment(data); setQrisDialogOpen(true); setSelected(null); }
    catch (err) { setError(formatApiErrorDetail(err.response?.data?.detail) || "QRIS pesanan tidak dapat ditampilkan."); }
  };

  const content = (() => {
    if (["login", "register"].includes(view)) {
      const registering = view === "register";
      const title = resetMode ? "Reset kata sandi" : registering ? "Buat akun pengguna" : "Masuk ke akun";
      return <section className="mx-auto max-w-lg px-4 py-10 sm:px-6 sm:py-16">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-9">
          <p className="text-xs font-bold uppercase tracking-[.18em] text-emerald-800">{storeName}</p>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-900">{title}</h1>
          <p className="mt-3 leading-6 text-slate-600">{resetMode ? "Kami akan mengirim kode reset ke email Anda." : registering ? "Daftar menggunakan email terverifikasi dan kata sandi. Telegram dapat dihubungkan nanti dari halaman akun." : `Masuk menggunakan email dan kata sandi akun ${storeName} Anda.`}</p>
          <form className="mt-7 space-y-4" onSubmit={submitAccountForm}>
            <label className="block text-sm font-medium">Email<input className={`${input} mt-1.5`} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
            {(!resetMode || codeSent) && <label className="block text-sm font-medium">{resetMode ? "Kata sandi baru" : "Kata sandi"}<input className={`${input} mt-1.5`} type="password" minLength={8} autoComplete={registering || resetMode ? "new-password" : "current-password"} required value={password} onChange={(e) => setPassword(e.target.value)} /></label>}
            {codeSent && <label className="block text-sm font-medium">Kode 6 digit<input className={`${input} mt-1.5`} inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value)} /></label>}
            {error && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
            {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}
            <button className={`${button} w-full`} disabled={busy}>{busy ? "Memproses…" : resetMode ? (codeSent ? "Simpan kata sandi" : "Kirim kode reset") : registering ? (codeSent ? "Verifikasi dan buat akun" : "Kirim kode verifikasi") : "Masuk"}<ArrowRight size={17}/></button>
          </form>
          {!registering && !resetMode && <button className="mt-4 text-sm font-semibold text-emerald-800 hover:underline" onClick={() => {setResetMode(true);setCodeSent(false);setCode("");setNotice("");setError("");}}>Lupa kata sandi?</button>}
          {resetMode && <button className="mt-4 block text-sm font-semibold text-emerald-800 hover:underline" onClick={() => {setResetMode(false);setCodeSent(false);setCode("");setNotice("");setError("");}}>Kembali ke masuk</button>}
          {!resetMode && <p className="mt-7 border-t border-slate-100 pt-5 text-sm text-slate-600">{registering ? "Sudah punya akun? " : "Belum punya akun? "}<Link className="font-semibold text-emerald-800 hover:underline" to={registering ? "/store/login" : "/store/register"}>{registering ? "Masuk" : "Daftar"}</Link></p>}
        </div>
      </section>;
    }

    if (view === "cart") return <section className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-widest text-emerald-800">Belanja</p><h1 className="mt-2 text-3xl font-bold">Keranjang</h1></div><Link to="/store/products" className="text-sm font-semibold text-emerald-800 hover:underline">Lanjut pilih produk</Link></div>
      {cart.length ? <div className="mt-7 grid gap-6 lg:grid-cols-[1fr_350px]">
        <div className="space-y-3">{cart.map((item) => { const product = products.find((p) => p._id === item.pid); const min = Math.max(1, Number(product?.minimum_purchase_qty || 1)); const low = item.qty < min; return <article key={item.pid} className="grid grid-cols-[76px_1fr] gap-3 rounded-xl border border-slate-200 bg-white p-3 sm:grid-cols-[100px_1fr] sm:gap-5 sm:p-5">
          <div className="relative aspect-square overflow-hidden rounded-lg bg-slate-100"><ProductArtwork product={product}/>{product?.image_url && <img src={product.image_url} alt={product.name} className="absolute inset-0 h-full w-full bg-white object-contain p-1" onError={(e) => {e.currentTarget.style.display="none";}}/>}</div>
          <div className="min-w-0"><div className="flex items-start justify-between gap-2"><div><p className="font-semibold text-slate-900">{product?.name || "Produk tidak tersedia"}</p><p className="mt-1 text-sm text-slate-500">{product ? fmtIDR(product.price_idr_current ?? product.price_idr) + " / unit" : "Produk sudah tidak tersedia"}</p></div><button className="rounded-md p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-700" aria-label="Hapus produk dari keranjang" disabled={busy} onClick={() => removeCartItem(item.pid)}><Trash2 size={17}/></button></div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><button className="rounded-md border border-slate-300 p-2 disabled:opacity-40" aria-label="Kurangi jumlah" onClick={() => changeQty(item.pid, -1)} disabled={busy || item.qty <= min}><Minus size={15}/></button><span className="min-w-8 text-center font-semibold">{item.qty}</span><button className="rounded-md border border-slate-300 p-2 disabled:opacity-40" aria-label="Tambah jumlah" onClick={() => changeQty(item.pid, 1)} disabled={busy || (product?.stock != null && item.qty >= product.stock)}><Plus size={15}/></button></div><p className="font-semibold text-slate-800">{fmtIDR(quote?.items?.find((line) => line.product_id === item.pid)?.subtotal ?? (product?.price_idr_current || 0) * item.qty)}</p></div>
            {low && <p className="mt-2 text-xs font-medium text-rose-700">Minimum pembelian {min} pcs untuk produk ini.</p>}{product?.stock != null && <p className="mt-1 text-xs text-slate-500">Tersedia {product.stock}</p>}
          </div>
        </article>; })}</div>
        <aside className="h-fit rounded-xl border border-slate-200 bg-white p-5 shadow-sm lg:sticky lg:top-24">
          <h2 className="text-lg font-semibold">Ringkasan pesanan</h2><p className="mt-2 text-sm text-slate-500">Pembayaran web menggunakan QRIS dalam Rupiah.</p>
          <fieldset className="mt-4 space-y-2"><legend className="text-sm font-semibold text-slate-700">Metode pembayaran</legend><label className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${paymentMethod === "qris" ? "border-emerald-700 bg-emerald-50" : "border-slate-200 bg-white"}`}><input type="radio" name="store-payment-method" value="qris" checked={paymentMethod === "qris"} onChange={() => setPaymentMethod("qris")} className="mt-1 accent-emerald-800"/><span><b className="block text-sm text-slate-900">QRIS All Payment</b><span className="mt-1 block text-xs text-slate-500">Bayar langsung melalui e-wallet atau mobile banking.</span></span></label><label className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${paymentMethod === "balance" ? "border-emerald-700 bg-emerald-50" : "border-slate-200 bg-white"}`}><input type="radio" name="store-payment-method" value="balance" checked={paymentMethod === "balance"} onChange={() => setPaymentMethod("balance")} className="mt-1 accent-emerald-800"/><span><b className="block text-sm text-slate-900">Saldo IDR</b><span className="mt-1 block text-xs text-slate-500">{profile ? `Tersedia ${fmtIDR(profile.balance_idr || 0)} · ${profile.telegram_linked ? "saldo web dan Telegram digabung" : "menggunakan saldo web"}` : "Masuk untuk membayar dengan saldo akun."}</span></span></label></fieldset>
          <label className="mt-4 block text-sm font-medium">Kode kupon (opsional)<input className={`${input} mt-1.5`} value={couponCode} onChange={(e) => setCouponCode(e.target.value.toUpperCase())} maxLength={32} placeholder="Masukkan kode kupon" /></label>
          <div className="mt-5 space-y-2 border-t border-slate-100 pt-4 text-sm"><div className="flex justify-between"><span className="text-slate-500">Subtotal</span><span>{fmtIDR(quote?.subtotal ?? cartTotal)}</span></div>{Number(quote?.discount_total || 0) > 0 && <div className="flex justify-between text-emerald-800"><span>Diskon</span><span>−{fmtIDR(quote.discount_total)}</span></div>}<div className="flex justify-between border-t border-slate-100 pt-3 text-base font-bold"><span>Total pesanan</span><span>{fmtIDR(quote?.total ?? cartTotal)}</span></div></div>
          {quoteLoading && <p role="status" className="mt-2 text-xs text-slate-500">Memeriksa stok dan harga terbaru…</p>}
          {quoteError && <p role="alert" className="mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{quoteError}</p>}
          {quote?.coupon_error && <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{quote.coupon_error}</p>}
          {error && <p role="alert" className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
          <button className={`${button} mt-5 w-full`} onClick={checkout} disabled={busy || addingIds.length > 0 || quoteLoading || Boolean(quoteError) || Boolean(quote?.coupon_error) || cart.some((item) => {const product = products.find((p) => p._id === item.pid); return !product || item.qty < Math.max(1, Number(product.minimum_purchase_qty || 1)) || (product.stock != null && item.qty > product.stock);})}>{busy ? "Memproses pembayaran…" : paymentMethod === "balance" ? <><CreditCard size={18}/> Bayar dengan Saldo</> : <><QrCode size={18}/> Bayar dengan QRIS</>}<ArrowRight size={17}/></button>
          <Link className="mt-3 flex items-center justify-center gap-2 text-sm font-semibold text-emerald-800" to="/store/deposit"><CreditCard size={16}/> Deposit saldo Telegram melalui QRIS</Link>
          <p className="mt-4 text-xs leading-5 text-slate-500">Checkout saldo memakai saldo web jika Telegram belum ditautkan. Setelah ditautkan, saldo web digabung satu kali ke saldo Telegram dan checkout memakai saldo gabungan. QRIS dibayar langsung dan diverifikasi otomatis.</p>
        </aside>
      </div> : <div className="mt-8 rounded-xl border border-slate-200 bg-white p-10 text-center"><ShoppingBag className="mx-auto text-slate-300" size={35}/><p className="mt-3 text-slate-600">Keranjang Anda masih kosong.</p><Link className={`${button} mt-5`} to="/store/products">Jelajahi produk</Link></div>}
    </section>;

    if (view === "profile") return <StoreProfile profile={profile} onUpdate={setProfile} onRefresh={loadProfile} onLogout={logout} onLink={createLinkCode} linkCode={linkCode} botName={botName} linkError={error}/>;

    if (view === "deposit") return <section className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
      <p className="text-xs font-bold uppercase tracking-widest text-emerald-800">Saldo</p><h1 className="mt-2 text-3xl font-bold">Deposit melalui QRIS</h1><p className="mt-3 max-w-2xl leading-6 text-slate-600">Pembayaran diperiksa otomatis oleh sistem. Saldo hanya ditambahkan setelah transaksi QRIS terverifikasi.</p>
      <div className="mt-7 grid gap-6 lg:grid-cols-[1fr_360px]">
        <div className="rounded-xl border border-slate-200 bg-white p-5 sm:p-7"><h2 className="text-lg font-semibold">Buat permintaan deposit</h2><form className="mt-5" onSubmit={createDeposit}><label className="block text-sm font-medium">Nominal saldo (IDR)<input className={`${input} mt-1.5`} type="number" min="10000" max="10000000" step="1000" required value={depositAmount} onChange={(e) => setDepositAmount(e.target.value)} /></label><p className="mt-2 text-xs text-slate-500">Nominal Rp10.000–Rp10.000.000. QRIS menampilkan total pembayaran termasuk biaya dan kode unik.</p>{error && <p role="alert" className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}{notice && <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">{notice}</p>}<button className={`${button} mt-5 w-full sm:w-auto`} disabled={busy}>{busy ? "Membuat QRIS…" : "Buat QRIS"}<ArrowRight size={17}/></button></form>
          {deposit && <div className="mt-7 rounded-xl border border-emerald-200 bg-emerald-50/50 p-4 sm:p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm font-semibold">QRIS All Payment · {deposit.deposit_id}</p><p className="mt-1 text-xs text-slate-500">Batas waktu {dateLabel(deposit.expires_at)}</p></div><span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900">{statusLabel(depositExpired ? "expired" : deposit.status)}</span></div><div className="mt-4 grid gap-3 sm:grid-cols-2"><div className="rounded-lg bg-white p-3"><p className="text-xs text-slate-500">Saldo ditambahkan</p><p className="mt-1 font-bold">{fmtIDR(deposit.amount)}</p></div><div className="rounded-lg bg-white p-3"><p className="text-xs text-slate-500">Bayar tepat sejumlah</p><p className="mt-1 font-bold text-emerald-900">{fmtIDR(deposit.payment_amount)}</p></div></div>{deposit.status === "pending" && !depositExpired ? <div className="mt-5 flex flex-col items-center rounded-lg bg-white p-4"><img className="h-64 w-64 max-w-full object-contain" src={deposit.qr_image} alt="QRIS All Payment"/><p className="mt-3 text-center text-sm font-semibold">Cara pembayaran</p><p className="mt-1 text-center text-sm text-slate-600">Pindai melalui aplikasi e-wallet atau mobile banking yang mendukung QRIS.</p><p className="mt-3 text-center text-xs font-semibold text-amber-800">⏳ QR hanya berlaku {deposit.expires_in_minutes || 5} menit.</p></div> : depositExpired || deposit.status === "expired" ? <p role="status" className="mt-5 rounded-lg bg-amber-50 p-4 text-sm text-amber-900">Kode QR sudah tidak berlaku karena waktu pembayaran habis. Silakan minta QR baru untuk deposit.</p> : <p role="status" className="mt-5 rounded-lg bg-emerald-50 p-4 text-sm text-emerald-900">Status deposit: {statusLabel(deposit.status)}.</p>}</div>}
        </div>
        <aside className="h-fit rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-semibold">Status deposit terakhir</h2><div className="mt-4 space-y-3">{depositRows.slice(0, 5).map((row) => <div key={row.deposit_id} className="rounded-lg bg-slate-50 p-3"><div className="flex justify-between gap-2"><span className="break-all font-mono text-xs">{row.deposit_id}</span><span className="text-xs font-semibold">{statusLabel(row.status)}</span></div><div className="mt-2 flex justify-between text-sm"><span>{fmtIDR(row.credited_amount || row.amount)}</span><span className="text-slate-500">{dateLabel(row.created_at)}</span></div></div>)}{!depositRows.length && <p className="text-sm text-slate-500">Belum ada deposit.</p>}</div><Link className="mt-5 inline-block text-sm font-semibold text-emerald-800 hover:underline" to="/store/transactions">Lihat semua transaksi →</Link></aside>
      </div>
    </section>;

    if (view === "transactions" || view === "orders") {
      const rows = view === "orders" ? orders.map((order) => ({...order, type: "order", reference: order.invoice_id, amount: order.total})) : transactions.filter((row) => transactionFilter === "all" || row.type === transactionFilter);
      return <section className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-bold uppercase tracking-widest text-emerald-800">Akun</p><h1 className="mt-2 text-3xl font-bold">{view === "orders" ? "Riwayat pesanan" : "Riwayat transaksi"}</h1></div>{view === "transactions" && <div className="flex gap-2">{[["all", "Semua"], ["deposit", "Deposit"], ["order", "Pesanan"]].map(([value, label]) => <button key={value} className={`rounded-lg border px-3 py-2 text-sm font-medium ${transactionFilter === value ? "border-emerald-800 bg-emerald-50 text-emerald-900" : "border-slate-200 bg-white text-slate-600"}`} onClick={() => setTransactionFilter(value)}>{label}</button>)}</div>}</div>
        {notice && <p role="status" className="mt-5 rounded-lg bg-emerald-50 p-4 text-sm text-emerald-900">{notice}</p>}
        <div className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="hidden grid-cols-[1.2fr_1fr_1fr_1fr_1fr] gap-3 border-b border-slate-200 bg-slate-50 px-5 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 sm:grid"><span>Referensi</span><span>Jenis</span><span>Tanggal</span><span>Jumlah</span><span>Status</span></div>
          {rows.map((row) => <button key={row.id || row._id} onClick={() => setSelected(row)} className="grid w-full gap-2 border-b border-slate-100 px-4 py-4 text-left transition hover:bg-slate-50 sm:grid-cols-[1.2fr_1fr_1fr_1fr_1fr] sm:items-center sm:gap-3 sm:px-5"><span className="font-mono text-sm font-semibold text-emerald-900">{row.reference || row.invoice_id || "—"}</span><span className="text-sm text-slate-600">{row.type === "deposit" ? `Deposit · ${row.payment_method || "QRIS"}` : "Pesanan"}</span><span className="text-xs text-slate-500">{dateLabel(row.created_at)}</span><span className="text-sm font-semibold">{row.currency === "USD" ? fmtUSD(row.amount) : fmtIDR(row.amount)}</span><span className="w-fit rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">{statusLabel(row.status)}</span></button>)}
          {!rows.length && <div className="px-5 py-12 text-center text-sm text-slate-500">Belum ada {view === "orders" ? "pesanan" : "transaksi"}.</div>}
        </div>
        {selected && <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/40 p-0 sm:items-center sm:p-4" role="presentation" onClick={(e) => { if (e.target === e.currentTarget) setSelected(null); }}><section role="dialog" aria-modal="true" aria-labelledby="transaction-title" className="max-h-[90vh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:max-w-xl sm:rounded-2xl sm:p-7"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-widest text-emerald-800">Detail transaksi</p><h2 id="transaction-title" className="mt-2 break-all text-xl font-bold">{selected.reference || selected.invoice_id}</h2></div><button className="rounded-lg p-2 hover:bg-slate-100" onClick={() => setSelected(null)} aria-label="Tutup"><X size={18}/></button></div><div className="mt-5 grid gap-3 sm:grid-cols-2"><div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Status</p><p className="mt-1 font-semibold">{statusLabel(selected.status)}</p></div><div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Waktu</p><p className="mt-1 text-sm font-medium">{dateLabel(selected.created_at)}</p></div><div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Jumlah</p><p className="mt-1 font-semibold">{selected.currency === "USD" ? fmtUSD(selected.amount) : fmtIDR(selected.amount)}</p></div><div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Pembayaran</p><p className="mt-1 font-semibold">{selected.payment_method || (selected.type === "deposit" ? "QRIS" : "Saldo")}</p></div></div>{selected.status === "pending_payment" && selected.payment_method === "qris" && <button className={`${button} mt-4 w-full`} onClick={() => reopenQris(selected._id || selected.id)}><QrCode size={17}/> Tampilkan QRIS untuk bayar</button>}{selected.items?.length > 0 && <div className="mt-5"><h3 className="font-semibold">Produk</h3><div className="mt-2 space-y-2">{selected.items.map((item, idx) => <div key={idx} className="rounded-lg border border-slate-200 p-3"><p className="font-medium">{item.name} × {item.qty}</p><p className="mt-1 text-sm text-slate-500">{selected.currency === "USD" ? fmtUSD(item.unit_price) : fmtIDR(item.unit_price)} / unit · Subtotal {selected.currency === "USD" ? fmtUSD(item.subtotal) : fmtIDR(item.subtotal)}</p></div>)}</div></div>}{selected.type === "order" && <OrderDelivery orderId={selected._id || selected.id} status={selected.status}/>} {selected.delivery_email_status && <p className="mt-4 text-sm text-slate-600">Status email produk: {statusLabel(selected.delivery_email_status === "sent" ? "delivered" : selected.delivery_email_status)}</p>}</section></div>}
      </section>;
    }

    if (displayView === "products") return <section className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
      {selectedCatalog && <Link to="/store/products" onClick={() => { setSearch(""); setProductFilter("all"); }} className="text-sm font-semibold text-emerald-800">← Semua katalog</Link>}
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-widest text-emerald-800">Katalog {storeName}</p><h1 className="mt-2 text-3xl font-bold">{selectedCatalog ? selectedCatalogName : "Pilih katalog"}</h1><p className="mt-3 text-slate-500">{selectedCatalog ? "Pilih varian atau durasi yang sesuai kebutuhan Anda." : "Temukan layanan favorit, lalu pilih produk dan durasinya."}</p></div><label className="relative block w-full sm:max-w-sm"><Search className="absolute left-3 top-3.5 text-slate-400" size={18}/><input aria-label="Cari katalog atau produk" className={`${input} pl-10`} placeholder={selectedCatalog ? "Cari varian di katalog ini" : "Cari katalog atau produk"} value={search} onChange={(e) => setSearch(e.target.value)}/></label></div>
      <CatalogFilter value={productFilter} setValue={setProductFilter}/>
      {error && <p role="alert" className="mt-5 rounded-lg bg-rose-50 p-4 text-rose-800">{error}</p>}
      {productLoading ? <p role="status" className="mt-7 rounded-xl bg-white p-8 text-center text-slate-500">Memuat katalog…</p> : <><p className="mt-5 text-sm text-slate-500">{listing.length} {selectedCatalog ? "pilihan produk" : "katalog"}</p><div className={`mt-4 grid gap-4 ${selectedCatalog ? "sm:grid-cols-2" : "grid-cols-2"} lg:grid-cols-3 xl:grid-cols-4`}>{visibleListing.map((item) => selectedCatalog ? <ProductCard key={item._id} product={item} add={add} onOpen={openProduct} adding={addingIds.includes(item._id) || busy} brand={storeName}/> : <CatalogCard key={item.key} catalog={item}/>)}</div></>}
      {!productLoading && !error && !listing.length && <p className="mt-6 rounded-xl bg-white p-8 text-center text-slate-500">Tidak ada pilihan yang sesuai. Coba ubah pencarian atau filter.</p>}
      {!productLoading && pageCount > 1 && <nav aria-label="Halaman katalog" className="mt-8 flex items-center justify-center gap-4"><button className={secondary} disabled={currentPage === 1} onClick={() => setCatalogPage(currentPage - 1)}>Sebelumnya</button><span className="text-sm">{currentPage} / {pageCount}</span><button className={secondary} disabled={currentPage === pageCount} onClick={() => setCatalogPage(currentPage + 1)}>Berikutnya</button></nav>}
    </section>;

    return <StoreHome products={products} loading={productLoading} error={error} search={search} setSearch={setSearch} onOpen={openProduct}
      renderCatalog={(catalog) => <CatalogCard key={catalog.key} catalog={catalog}/>}
      renderProduct={(product) => <ProductCard key={product._id} product={product} add={add} onOpen={openProduct} adding={addingIds.includes(product._id) || busy} brand={storeName}/>}/>;

  })();

  return <div className={`${page} storefront-font storefront-theme`} data-theme={resolvedTheme}>
    <StoreNavigation resolvedTheme={resolvedTheme} theme={theme} setTheme={setTheme} count={cart.reduce((sum, item) => sum + item.qty, 0)} profile={profile} onLogout={logout} storeName={storeName} storeTagline={storeTagline}/>
    {/* Broadcast banner */}
    {broadcast && (
      <div className="bg-gradient-to-r from-amber-500 to-orange-500 px-4 py-2.5 text-center text-sm font-semibold text-white shadow-md">
        📢 {broadcast}
      </div>
    )}
    {/* Wajib join channel gate */}
    {channelGate && !gateDismissed && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
        <div className="w-full max-w-sm rounded-3xl border border-white/15 bg-slate-900/95 p-6 text-center shadow-2xl backdrop-blur-2xl">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-sky-500/15">
            <span className="text-2xl">📢</span>
          </div>
          <h2 className="mt-4 text-lg font-bold text-white">Join Channel Dulu Yuk</h2>
          <p className="mt-2 text-sm text-slate-400">
            Untuk akses {storeName}, kamu wajib join <b className="text-slate-200">{channelGate.name}</b> dulu.
          </p>
          <a
            href={channelGate.url}
            target="_blank"
            rel="noreferrer"
            onClick={() => { setGateDismissed(true); sessionStorage.setItem("channel_gate_ok", "1"); }}
            className="mt-5 block w-full rounded-2xl bg-sky-500 py-3 font-bold text-white shadow-lg transition hover:bg-sky-400"
          >
            Join {channelGate.name}
          </a>
          <button
            onClick={() => { setGateDismissed(true); sessionStorage.setItem("channel_gate_ok", "1"); }}
            className="mt-2 w-full py-2 text-sm text-slate-500 hover:text-slate-300"
          >
            Sudah join, lanjutkan
          </button>
        </div>
      </div>
    )}
    {content}<footer className="border-t border-slate-200 bg-white"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-7 text-sm text-slate-500 sm:px-6 lg:px-8"><span>© {new Date().getFullYear()} {storeName}</span><div className="flex flex-wrap gap-4"><Link to="/store/products">Katalog</Link><Link to="/store/deposit">Deposit</Link><Link to="/store/transactions">Transaksi</Link>{profile && <Link to="/store/profile">Akun</Link>}</div></div></footer>
    {qrisDialogOpen && checkoutPayment && <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/45 p-0 sm:items-center sm:p-4" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) setQrisDialogOpen(false); }}><section role="dialog" aria-modal="true" aria-labelledby="qris-title" className="max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl sm:max-w-lg sm:rounded-2xl sm:p-7"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-widest text-emerald-800">Pembayaran terverifikasi otomatis</p><h2 id="qris-title" className="mt-2 text-xl font-bold text-slate-900">QRIS All Payment</h2></div><button aria-label="Tutup" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" onClick={() => setQrisDialogOpen(false)}><X size={18}/></button></div><div className="mt-4 grid grid-cols-2 gap-3"><div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Invoice</p><p className="mt-1 break-all font-mono text-sm font-semibold">{checkoutPayment.invoice_id}</p></div><div className="rounded-lg bg-slate-50 p-3"><p className="text-xs text-slate-500">Status</p><p className="mt-1 text-sm font-semibold">{statusLabel(checkoutExpired ? "expired" : checkoutPayment.status)}</p></div></div>
      {checkoutPayment.status === "pending_payment" && !checkoutExpired ? <><div className="mt-4 flex justify-between rounded-lg border border-emerald-100 bg-emerald-50 p-4"><span className="text-sm text-slate-600">Bayar tepat sejumlah</span><b className="text-lg text-emerald-950">{fmtIDR(checkoutPayment.payment_amount)}</b></div><p className="mt-2 text-xs text-slate-500">QR hanya berlaku {checkoutPayment.expires_in_minutes || 5} menit, sampai {dateLabel(checkoutPayment.expires_at)}. Nominal sudah termasuk biaya layanan dan kode unik.</p>{checkoutPayment.qr_image && <div className="mt-4 flex flex-col items-center rounded-xl border border-slate-200 p-4"><img className="h-64 w-64 max-w-full object-contain" src={checkoutPayment.qr_image} alt="QRIS All Payment"/><p className="mt-3 text-center text-sm font-medium text-slate-800">Cara pembayaran</p><p className="mt-1 text-center text-sm text-slate-600">Pindai melalui aplikasi e-wallet atau mobile banking yang mendukung QRIS.</p><p className="mt-1 text-center text-xs text-slate-500">Status pembayaran akan diperiksa otomatis.</p></div>}</> : checkoutExpired || checkoutPayment.status === "expired" ? <p role="status" className="mt-4 rounded-lg bg-amber-50 p-4 text-sm text-amber-900">Kode QR sudah tidak berlaku karena waktu pembayaran habis. Silakan buat checkout baru untuk meminta QRIS baru.</p> : <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-4 text-sm text-emerald-900">{checkoutPayment.status === "delivered" ? "Pembayaran terverifikasi. Rincian pesanan dikirim ke email." : checkoutPayment.status === "service_waiting" ? "Pembayaran terverifikasi. Pesanan layanan sedang diproses." : checkoutPayment.status === "delivery_failed" ? "Pembayaran terverifikasi, tetapi tim perlu memeriksa pengiriman." : `Status pembayaran: ${statusLabel(checkoutPayment.status)}.`}</p>}
      <div className="mt-5 flex flex-wrap justify-end gap-2"><button className={secondary} onClick={() => { setQrisDialogOpen(false); navigate("/store/orders"); }}>Lihat pesanan</button><button className={button} onClick={() => setQrisDialogOpen(false)}>Tutup</button></div></section></div>}
    <StoreProductDialog open={view === "detail"} product={products.find((p) => p._id === productId)} products={products} loading={productLoading} theme={resolvedTheme} adding={addingIds.includes(productId) || busy} onSelect={openProduct} onAdd={add} onClose={closeProduct} error={error}/>
    <CartToast item={cartToast} onClose={closeCartToast}/>
    <CheckoutFeedback feedback={checkoutFeedback} onClose={() => setCheckoutFeedback(null)}/>
    <ContactBubbles whatsappNumber={contactConfig.whatsapp_contact_number} telegramTarget={contactConfig.telegram_contact_target} message={whatsappMessage} />
  </div>;
}

function CatalogFilter({ value, setValue }) {
  const options = [["all", "Semua", Sparkles], ["bestseller", "Terlaris", TrendingUp], ["ready", "Ready Stock", PackageCheck], ["out", "Out of Stock", PackageX], ["service", "Jasa Payment", Headset]];
  return <div className="mt-5 flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Filter produk"><div className="flex min-w-max gap-2">{options.map(([key, label, Icon]) => <button key={key} onClick={() => setValue(key)} aria-pressed={value === key} className={`inline-flex shrink-0 items-center gap-2 rounded-full border px-4 py-2 text-sm font-medium transition ${value === key ? "border-emerald-800 bg-emerald-800 text-white" : "border-slate-200 bg-white text-slate-600 hover:border-emerald-300 hover:text-emerald-900"}`}><Icon size={15}/>{label}</button>)}</div></div>;
}

function ContactBubbles({ whatsappNumber, telegramTarget, message }) {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    if (!whatsappNumber && !telegramTarget) return undefined;
    const expiryKey = "idse_contact_bubbles_expires_at";
    const dismissedKey = "idse_contact_bubbles_dismissed_until";
    const now = Date.now();
    let expiry = 0;
    let dismissedUntil = 0;
    try {
      expiry = Number(window.localStorage.getItem(expiryKey) || 0);
      dismissedUntil = Number(window.localStorage.getItem(dismissedKey) || 0);
      if (!expiry || expiry <= now) {
        expiry = now + 2 * 60 * 1000;
        window.localStorage.setItem(expiryKey, String(expiry));
        window.localStorage.removeItem(dismissedKey);
        dismissedUntil = 0;
      }
    } catch (_) { expiry = now + 2 * 60 * 1000; }
    if (dismissedUntil > now) { setVisible(false); return undefined; }
    setVisible(true);
    const timer = window.setTimeout(() => {
      setVisible(false);
      try { window.localStorage.removeItem(expiryKey); window.localStorage.removeItem(dismissedKey); } catch (_) {}
    }, Math.max(0, expiry - now));
    return () => window.clearTimeout(timer);
  }, [whatsappNumber, telegramTarget]);

  const close = () => {
    setVisible(false);
    try {
      const expiry = Number(window.localStorage.getItem("idse_contact_bubbles_expires_at") || 0);
      window.localStorage.setItem("idse_contact_bubbles_dismissed_until", String(expiry || (Date.now() + 2 * 60 * 1000)));
    } catch (_) {}
  };
  if (!visible) return null;
  const digits = String(whatsappNumber || "").replace(/\D/g, "");
  const waNumber = digits.startsWith("0") ? `62${digits.slice(1)}` : digits;
  const waHref = waNumber ? `https://wa.me/${waNumber}?text=${encodeURIComponent(message)}` : "";
  let tgHref = String(telegramTarget || "").trim();
  if (/^@?[A-Za-z0-9_]{5,32}$/.test(tgHref)) tgHref = `https://t.me/${tgHref.replace(/^@/, "")}`;
  if (!/^https:\/\/(t\.me|telegram\.me)\//i.test(tgHref)) tgHref = "";
  if (!waHref && !tgHref) return null;
  return <div className="fixed bottom-5 right-4 z-40 flex flex-col items-end gap-2 sm:bottom-7 sm:right-7" aria-label="Kontak toko">
    <button type="button" aria-label="Tutup tombol kontak" title="Tutup" onClick={close} className="grid h-8 w-8 place-items-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-md transition hover:bg-slate-100"><X size={16}/></button>
    {waHref && <a href={waHref} target="_blank" rel="noreferrer" aria-label={`Hubungi ${storeName} melalui WhatsApp`} title="WhatsApp" className="grid h-14 w-14 place-items-center rounded-full bg-[#25D366] text-white shadow-lg transition hover:scale-105 hover:shadow-xl focus:outline-none focus:ring-4 focus:ring-emerald-300"><WhatsAppLogo/></a>}
    {tgHref && <a href={tgHref} target="_blank" rel="noreferrer" aria-label={`Hubungi ${storeName} melalui Telegram`} title="Telegram" className="grid h-14 w-14 place-items-center rounded-full bg-[#229ED9] text-white shadow-lg transition hover:scale-105 hover:shadow-xl focus:outline-none focus:ring-4 focus:ring-sky-300"><TelegramLogo/></a>}
  </div>;
}

function WhatsAppLogo() {
  return <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true" fill="currentColor"><path d="M16.04 3.2A12.7 12.7 0 0 0 5.19 22.5L3.5 28.7l6.35-1.67A12.7 12.7 0 1 0 16.04 3.2Zm0 23.08a10.35 10.35 0 0 1-5.27-1.44l-.38-.22-3.77.99 1-3.67-.25-.38a10.37 10.37 0 1 1 8.67 4.72Zm5.69-7.77c-.31-.16-1.83-.9-2.12-1s-.49-.16-.7.16c-.2.31-.8 1-1 1.21-.19.2-.36.23-.67.08-.31-.16-1.3-.48-2.47-1.52-.91-.81-1.53-1.81-1.71-2.12-.18-.31-.02-.48.14-.64.14-.14.31-.36.47-.54.15-.18.2-.31.31-.52.1-.2.05-.39-.03-.54-.08-.16-.7-1.68-.96-2.3-.25-.6-.5-.52-.7-.53h-.6c-.2 0-.54.08-.82.39-.28.31-1.08 1.05-1.08 2.56s1.1 2.97 1.26 3.18c.15.2 2.16 3.3 5.24 4.63.73.31 1.3.5 1.75.64.73.23 1.4.2 1.93.12.59-.09 1.82-.75 2.08-1.48.25-.72.25-1.35.18-1.48-.08-.13-.28-.21-.59-.36Z"/></svg>;
}

function TelegramLogo() {
  return <svg viewBox="0 0 24 24" width="29" height="29" aria-hidden="true" fill="currentColor"><path d="M21.7 4.2 18.5 20c-.24 1.12-.9 1.4-1.82.87l-5.03-3.7-2.43 2.34c-.27.28-.5.5-1.03.5l.36-5.1 9.28-8.39c.4-.36-.09-.56-.62-.2L5.75 13.55.78 12c-1.08-.34-1.1-1.08.23-1.6L20.45 2.8c.9-.33 1.68.22 1.25 1.4Z"/></svg>;
}
