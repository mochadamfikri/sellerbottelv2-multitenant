import "@/App.css";
import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import api from "./lib/api";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { Layout } from "./components/Layout";
import Login from "./pages/Login";
import PromoLanding from "./pages/PromoLanding";
import RegisterStore from "./pages/RegisterStore";
import VerifyOtp from "./pages/VerifyOtp";
import SelectPackage from "./pages/SelectPackage";
import DnsVerify from "./pages/DnsVerify";
import RegisterSuccess from "./pages/RegisterSuccess";
import TenantPanel from "./pages/TenantPanel";
import TenantAdmin from "./pages/TenantAdmin";
import PromoConfig from "./pages/PromoConfig";
import Overview from "./pages/Overview";
import Products from "./pages/Products";
import Deposits from "./pages/Deposits";
import UsersPage from "./pages/Users";
import SettingsPage from "./pages/SettingsPage";
import Broadcasts from "./pages/Broadcasts";
import CentralBroadcasts from "./pages/CentralBroadcasts";
import Discounts from "./pages/Discounts";
import Messages from "./pages/Messages";
import Orders from "./pages/Orders";
import Inventory from "./pages/Inventory";
import Reports from "./pages/Reports";
import Promotions from "./pages/Promotions";
import Resellers from "./pages/Resellers";
import BotModeration from "./pages/BotModeration";
import Storefront from "./pages/Storefront";
import Catalogs from "./pages/Catalogs";
import Analytics from "./pages/Analytics";
import PlatformControl from "./pages/PlatformControl";

function Protected({ children, title }) {
  const { user } = useAuth();
  if (user === null) return <div className="min-h-screen bg-[#0B0F17] flex items-center justify-center text-slate-500">Memuat...</div>;
  if (user === false) return <Navigate to="/login" replace />;
  return <Layout title={title}>{children}</Layout>;
}

function HomeRoute() {
  // Keep the existing admin landing page on the maintenance hostname.
  if (window.location.hostname === "idsedm.duckdns.org") {
    return <Protected title="Ringkasan"><Overview /></Protected>;
  }
  return <Storefront />;
}

function PromoDomainRoute() {
  // If the hostname matches the configured promo domain (e.g. idseconnect.my.id),
  // serve the promo landing at / instead of the storefront.
  const [isPromo, setIsPromo] = useState(null);
  useEffect(() => {
    api.get("/public/promo-config")
      .then((r) => {
        const d = (r.data?.promo_domain || "").trim().toLowerCase();
        setIsPromo(!!d && window.location.hostname.toLowerCase() === d);
      })
      .catch(() => setIsPromo(false));
  }, []);
  if (isPromo === null) return <div className="min-h-screen bg-slate-950" />;
  if (isPromo) return <PromoLanding />;
  return <HomeRoute />;
}

function AdminRoute() {
  // /admin: di tenant subdomain → panel tenant,
  // di idsestock.my.id → panel owner
  const host = window.location.hostname.toLowerCase();
  const isTenantHost = host.endsWith(".idseconnect.my.id")
    && host !== "idseconnect.my.id"
    && !host.startsWith("panel.");
  if (isTenantHost) {
    return <TenantAdmin />;
  }
  return <Protected title="Ringkasan"><Overview /></Protected>;
}

function PanelDomainRoute() {
  // idseconnect.my.id → promo + pendaftaran tenant.
  // idsestock.my.id → khusus kelola stok owner.
  // idsehub.my.id → platform control (kelola tenant + database).
  // panel.idseconnect.my.id → konfigurator landing page.
  const host = window.location.hostname.toLowerCase();
  if (host === "panel.idseconnect.my.id" || host.startsWith("panel.")) {
    return <Protected title="Konfigurasi Landing Page"><PromoConfig /></Protected>;
  }
  if (host === "idsestock.my.id") {
    return <Protected title="Kelola Stok"><Overview /></Protected>;
  }
  if (host === "idsehub.my.id") {
    return <Protected title="Platform Control Center"><PlatformControl /></Protected>;
  }
  // Tenant subdomain (*.idseconnect.my.id) → storefront tenant
  if (host.endsWith(".idseconnect.my.id") && host !== "idseconnect.my.id") {
    return <Storefront />;
  }
  return <PromoDomainRoute />;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          {/* Public promo + self-service tenant registration (idseconnect.my.id) */}
          <Route path="/promo" element={<PromoLanding />} />
          <Route path="/daftar" element={<RegisterStore />} />
          <Route path="/daftar/verifikasi" element={<VerifyOtp />} />
          <Route path="/daftar/paket" element={<SelectPackage />} />
          <Route path="/daftar/dns" element={<DnsVerify />} />
          <Route path="/daftar/sukses" element={<RegisterSuccess />} />
          <Route path="/panel-tenant" element={<TenantPanel />} />
          <Route path="/admin" element={<AdminRoute />} />
          <Route path="/" element={<PanelDomainRoute />} />
          <Route path="/store" element={<Storefront />} />
          <Route path="/store/products" element={<Storefront view="products" />} />
          <Route path="/store/product/:productId" element={<Storefront view="detail" />} />
          <Route path="/store/cart" element={<Storefront view="cart" />} />
          <Route path="/store/login" element={<Storefront view="login" />} />
          <Route path="/store/register" element={<Storefront view="register" />} />
          <Route path="/store/orders" element={<Storefront view="orders" />} />
          <Route path="/store/transactions" element={<Storefront view="transactions" />} />
          <Route path="/store/deposit" element={<Storefront view="deposit" />} />
          <Route path="/store/profile" element={<Storefront view="profile" />} />
          {/* Per-tenant storefront: each tenant gets their own public store link */}
          <Route path="/store/t/:tenantSlug" element={<Storefront tenantView />} />
          <Route path="/store/t/:tenantSlug/products" element={<Storefront view="products" tenantView />} />
          <Route path="/analytics" element={<Protected title="Analytics & Traffic"><Analytics /></Protected>} />
          <Route path="/platform-control" element={<Protected title="Platform Control Center"><PlatformControl /></Protected>} />
          <Route path="/promo-config" element={<Protected title="Konfigurasi Landing Page"><PromoConfig /></Protected>} />
          <Route path="/products" element={<Protected title="Kelola Produk"><Products /></Protected>} />
          <Route path="/catalogs" element={<Protected title="Kelola Katalog"><Catalogs /></Protected>} />
          <Route path="/orders" element={<Protected title="Orders"><Orders /></Protected>} />
          <Route path="/reports" element={<Protected title="Rekap & Laporan"><Reports /></Protected>} />
          <Route path="/inventory" element={<Protected title="Inventory"><Inventory /></Protected>} />
          <Route path="/deposits" element={<Protected title="Kelola Deposit"><Deposits /></Protected>} />
          <Route path="/users" element={<Protected title="Kelola Pengguna"><UsersPage /></Protected>} />
          <Route path="/settings" element={<Protected title="Pengaturan"><SettingsPage /></Protected>} />
          <Route path="/broadcasts" element={<Protected title="Broadcast"><Broadcasts /></Protected>} />
          <Route path="/central-broadcasts" element={<Protected title="Broadcast Terpusat"><CentralBroadcasts /></Protected>} />
          <Route path="/discounts" element={<Protected title="Discount"><Discounts /></Protected>} />
          <Route path="/messages" element={<Protected title="Bot Messages"><Messages /></Protected>} />
          <Route path="/bot-moderation" element={<Protected title="Tindak Lanjut Bot"><BotModeration /></Protected>} />
          <Route path="/promotions" element={<Protected title="Promosi / Cari Pelanggan"><Promotions /></Protected>} />
          <Route path="/resellers" element={<Protected title="Bot Reseller"><Resellers /></Protected>} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" theme="dark" richColors />
    </AuthProvider>
  );
}

export default App;
