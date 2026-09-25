import { useState } from "react";
import { NavLink, useLocation, useNavigate, Link } from "react-router-dom";
import { Logo, LogoMark } from "@/components/Logo";
import { Disclaimer } from "@/components/Disclaimer";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";
import {
  LayoutGrid, Bell, Activity, Wallet, FileBarChart, Globe2,
  Receipt, LineChart, FlaskConical, Settings as SettingsIcon, LogOut, Menu, X,
} from "lucide-react";

const NAV = [
  { to: "/app", label: "Genel Bakış", icon: LayoutGrid, end: true },
  { to: "/app/alarmlar", label: "Alarmlar", icon: Bell },
  { to: "/app/sinyaller", label: "Sinyaller & Analiz", icon: Activity },
  { to: "/app/pozisyonlar", label: "Pozisyonlar", icon: Wallet },
  { to: "/app/rapor", label: "Rapor", icon: FileBarChart },
  { to: "/app/makro", label: "Makro", icon: Globe2 },
  { to: "/app/maliyet", label: "Maliyet", icon: Receipt },
  { to: "/app/vadeli", label: "Vadeli", icon: LineChart },
  { to: "/app/backtest", label: "Backtest", icon: FlaskConical },
  { to: "/app/ayarlar", label: "Ayarlar", icon: SettingsIcon },
];

export function PanelLayout({ children }) {
  const [open, setOpen] = useState(false);
  const { user, logout } = useAuth();
  const loc = useLocation();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/giris");
  };

  const NavItems = ({ onClick }) => (
    <nav className="flex flex-col gap-0.5">
      {NAV.map((n) => {
        const Icon = n.icon;
        return (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            onClick={onClick}
            data-testid={`side-nav-${n.to === "/app" ? "overview" : n.to.split("/").pop()}`}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors duration-150",
                isActive ? "bg-secondary text-t-1" : "text-t-2 hover:text-t-1 hover:bg-secondary/50"
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {n.label}
          </NavLink>
        );
      })}
    </nav>
  );

  return (
    <div className="min-h-screen bg-ink text-t-1">
      {/* Sidebar (desktop) */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-hairline bg-ink lg:flex">
        <div className="flex h-16 items-center border-b border-hairline px-5">
          <Link to="/app"><Logo /></Link>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-4">
          <NavItems />
        </div>
        <div className="border-t border-hairline p-3">
          <div className="mb-2 px-2 text-xs text-t-3 truncate">{user?.email}</div>
          <button
            onClick={handleLogout}
            data-testid="logout-btn"
            className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-t-2 transition-colors duration-150 hover:bg-secondary hover:text-t-1"
          >
            <LogOut className="h-4 w-4" /> Çıkış Yap
          </button>
        </div>
      </aside>

      {/* Topbar (mobile) */}
      <header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b border-hairline bg-ink/90 px-5 backdrop-blur-sm lg:hidden">
        <Link to="/app"><Logo /></Link>
        <button onClick={() => setOpen(true)} data-testid="panel-menu-toggle" aria-label="Menü">
          <Menu className="h-5 w-5 text-t-1" />
        </button>
      </header>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/70" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-hairline bg-ink animate-fade-in">
            <div className="flex h-16 items-center justify-between border-b border-hairline px-5">
              <Logo />
              <button onClick={() => setOpen(false)} aria-label="Kapat"><X className="h-5 w-5 text-t-1" /></button>
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-4">
              <NavItems onClick={() => setOpen(false)} />
            </div>
            <div className="border-t border-hairline p-3">
              <button onClick={handleLogout} className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-t-2 hover:bg-secondary hover:text-t-1">
                <LogOut className="h-4 w-4" /> Çıkış Yap
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="lg:pl-60">
        <main key={loc.pathname} className="mx-auto max-w-6xl px-5 py-8 animate-fade-in">
          {children}
          <div className="mt-12">
            <Disclaimer />
          </div>
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, action, testid }) {
  return (
    <div className="mb-6 flex items-start justify-between gap-4" data-testid={testid}>
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-t-1">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-t-2">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
