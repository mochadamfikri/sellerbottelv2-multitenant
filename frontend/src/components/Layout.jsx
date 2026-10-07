import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Package, Wallet, Users, Settings, LogOut, Bot, Megaphone,
  Percent, MessageSquareText, ClipboardList, Boxes, BarChart3, Menu, X, ShieldOff,
  ChevronDown, ChevronRight, Radio, ChartNoAxesCombined, Building2
} from "lucide-react";
import { useAuth } from "../context/AuthContext";

const nav = [
  { to: "/admin", label: "Ringkasan", icon: LayoutDashboard },
  { to: "/analytics", label: "Analytics & Traffic", icon: ChartNoAxesCombined },
  { to: "/platform-control", label: "Platform Control", icon: Building2 },
  { to: "/promo-config", label: "Landing Page", icon: Megaphone },
  {
    label: "Catalog & Inventory", icon: Boxes,
    children: [
      { to: "/catalogs", label: "Catalog", icon: Boxes },
      { to: "/products", label: "Products", icon: Package },
      { to: "/inventory", label: "Inventory", icon: Boxes },
    ],
  },
  {
    label: "Orders & Reports", icon: ClipboardList,
    children: [
      { to: "/orders", label: "Orders", icon: ClipboardList },
      { to: "/reports", label: "Reports", icon: BarChart3 },
    ],
  },
  { to: "/deposits", label: "Deposit", icon: Wallet },
  { to: "/users", label: "Pengguna", icon: Users },
  { to: "/discounts", label: "Discount", icon: Percent },
  {
    label: "Broadcast & Communication", icon: Radio,
    children: [
      { to: "/broadcasts", label: "Broadcast", icon: Megaphone },
      { to: "/central-broadcasts", label: "Broadcast Terpusat", icon: Radio },
    ],
  },
  { to: "/promotions", label: "Promotion & Customer Acquisition", icon: Megaphone },
  { to: "/resellers", label: "Bot Reseller", icon: Bot },
  { to: "/messages", label: "Bot Messages", icon: MessageSquareText },
  { to: "/bot-moderation", label: "Tindak Lanjut Bot", icon: ShieldOff },
  { to: "/settings", label: "Pengaturan", icon: Settings },
];

export const Layout = ({ children, title }) => {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  // Menu berdasarkan domain:
  // - idsestock.my.id → khusus kelola stok (sembunyikan Platform Control & Landing Page)
  // - idsehub.my.id → khusus platform control (sembunyikan semua fitur stok)
  const host = typeof window !== "undefined" ? window.location.hostname.toLowerCase() : "";
  const isHub = host === "idsehub.my.id";
  const isStock = host === "idsestock.my.id";

  const STOCK_PATHS = [
    "/admin", "/analytics", "/catalogs", "/products", "/inventory",
    "/orders", "/reports", "/deposits", "/users", "/discounts",
    "/broadcasts", "/central-broadcasts", "/promotions",
    "/bot-reseller", "/bot-messages", "/settings",
  ];

  const visibleNav = nav.filter((item) => {
    const checkPath = (path) => {
      if (!path) return true;
      if (isHub && STOCK_PATHS.includes(path)) return false;
      if (isStock && (path === "/platform-control" || path === "/promo-config")) return false;
      return true;
    };
    if (item.to && !checkPath(item.to)) return false;
    if (item.children) {
      item = { ...item, children: item.children.filter((c) => checkPath(c.to)) };
      if (item.children.length === 0) return false;
    }
    return true;
  });
  const [openGroups, setOpenGroups] = useState({
    "Catalog & Inventory": true,
    "Orders & Reports": true,
    "Broadcast & Communication": false,
  });

  const toggleGroup = (groupLabel) => {
    setOpenGroups((prev) => ({
      ...prev,
      [groupLabel]: !prev[groupLabel],
    }));
  };

  useEffect(() => {
    setMenuOpen(false);
  }, [title]);

  return (
    <div className="min-h-screen bg-[#0B0F17] text-slate-100">
      {menuOpen && (
        <button
          aria-label="Tutup menu"
          onClick={() => setMenuOpen(false)}
          className="fixed inset-0 z-40 bg-black/45 backdrop-blur-[1px] cursor-default"
        />
      )}

      <aside className={
        "fixed inset-y-0 left-0 z-50 w-[290px] bg-[#0D1220] border-r border-slate-800 shadow-2xl transition-transform duration-200 " +
        (menuOpen ? "translate-x-0" : "-translate-x-full")
      }>
        <div className="flex items-center justify-between gap-2.5 px-5 h-16 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center">
              <Bot className="text-cyan-400" size={18} />
            </div>
            <div>
              <p className="font-heading font-bold text-sm tracking-tight">TokoBot</p>
              <p className="text-[10px] text-slate-500 font-mono uppercase tracking-widest">Admin Panel</p>
            </div>
          </div>
          <button onClick={() => setMenuOpen(false)} className="p-2 rounded-lg text-slate-500 hover:text-slate-100 hover:bg-slate-800"><X size={18} /></button>
        </div>

        <nav className="p-3 space-y-1 overflow-y-auto h-[calc(100vh-120px)]">
          {visibleNav.map(({ to, label, icon: Icon, children: subItems }) => {
            if (subItems) {
              const expanded = openGroups[label];
              return (
                <div key={label} className="space-y-1">
                  <button
                    type="button"
                    aria-expanded={expanded}
                    data-testid={"nav-group-" + label.toLowerCase().replace(/\s+/g, "-")}
                    onClick={() => toggleGroup(label)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors text-slate-300 hover:text-slate-100 hover:bg-slate-800/60"
                  >
                    <Icon size={17} />
                    <span className="flex-1 text-left">{label}</span>
                    {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                  </button>
                  {expanded && (
                    <div className="ml-4 pl-3 border-l border-slate-800 space-y-1">
                      {subItems.map(({ to: childTo, label: childLabel, icon: ChildIcon }) => (
                        <NavLink
                          key={childTo}
                          to={childTo}
                          data-testid={"nav-" + childLabel.toLowerCase().replace(/\s+/g, "-")}
                          onClick={() => setMenuOpen(false)}
                          className={({ isActive }) =>
                            "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors " +
                            (isActive
                              ? "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20"
                              : "text-slate-400 hover:text-slate-100 hover:bg-slate-800/60")
                          }
                        >
                          <ChildIcon size={15} />
                          {childLabel}
                        </NavLink>
                      ))}
                    </div>
                  )}
                </div>
              );
            }
            return (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                data-testid={"nav-" + label.toLowerCase().replace(/\s+/g, "-")}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors " +
                  (isActive
                    ? "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20"
                    : "text-slate-400 hover:text-slate-100 hover:bg-slate-800/60")
                }
              >
                <Icon size={17} />
                {label}
              </NavLink>
            );
          })}
        </nav>

        <button
          onClick={async () => { await logout(); navigate("/login"); }}
          className="absolute bottom-0 left-0 right-0 flex items-center gap-3 px-6 py-4 text-sm text-slate-400 hover:text-rose-400 border-t border-slate-800 bg-[#0D1220]"
        >
          <LogOut size={17} /> Keluar
        </button>
      </aside>

      <div className="min-h-screen">
        <header className="sticky top-0 z-30 h-16 flex items-center gap-3 px-4 sm:px-6 bg-slate-900/90 backdrop-blur-md border-b border-slate-800">
          <button
            aria-label="Buka menu"
            onClick={() => setMenuOpen(true)}
            className="p-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800"
          >
            <Menu size={21} />
          </button>

          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center">
              <Bot className="text-cyan-400" size={15} />
            </div>
            <span className="font-heading font-bold text-sm hidden sm:block">TokoBot</span>
          </div>

          <div className="ml-auto">
            <span className="text-xs text-slate-500 font-mono">{title}</span>
          </div>
        </header>

        <main className="p-4 sm:p-6 lg:p-8 space-y-6 max-w-7xl mx-auto">{children}</main>
      </div>
    </div>
  );
};
