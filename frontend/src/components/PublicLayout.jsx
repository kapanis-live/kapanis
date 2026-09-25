import { useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { Disclaimer } from "@/components/Disclaimer";
import { Button } from "@/components/ui/button";
import { Menu, X } from "lucide-react";

const NAV = [
  { to: "/", label: "Ana Sayfa", end: true },
  { to: "/ozellikler", label: "Özellikler" },
  { to: "/nasil-calisir", label: "Nasıl Çalışır" },
  { to: "/kurallar", label: "Kurallar" },
  { to: "/sss", label: "SSS" },
  { to: "/iletisim", label: "İletişim" },
];

export function PublicLayout({ children }) {
  const [open, setOpen] = useState(false);
  const loc = useLocation();

  return (
    <div className="min-h-screen bg-ink text-t-1 flex flex-col">
      <header className="sticky top-0 z-40 border-b border-hairline bg-ink/90 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <Link to="/" data-testid="nav-home-logo">
            <Logo />
          </Link>
          <nav className="hidden items-center gap-1 md:flex">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                data-testid={`nav-link-${n.to === "/" ? "home" : n.to.slice(1)}`}
                className={({ isActive }) =>
                  `rounded-md px-3 py-2 text-sm transition-colors duration-150 ${
                    isActive ? "text-t-1 bg-secondary" : "text-t-2 hover:text-t-1"
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="hidden md:block">
            <Button asChild size="sm" data-testid="nav-login-btn">
              <Link to="/giris">Panele Gir</Link>
            </Button>
          </div>
          <button className="md:hidden text-t-1" onClick={() => setOpen(!open)} data-testid="nav-mobile-toggle" aria-label="Menü">
            {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
        {open && (
          <div className="border-t border-hairline bg-ink md:hidden">
            <nav className="mx-auto flex max-w-6xl flex-col px-5 py-3">
              {NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    `rounded-md px-3 py-2.5 text-sm ${isActive ? "text-t-1 bg-secondary" : "text-t-2"}`
                  }
                >
                  {n.label}
                </NavLink>
              ))}
              <Button asChild size="sm" className="mt-2">
                <Link to="/giris" onClick={() => setOpen(false)}>Panele Gir</Link>
              </Button>
            </nav>
          </div>
        )}
      </header>

      <main key={loc.pathname} className="flex-1 animate-fade-in">{children}</main>

      <footer className="border-t border-hairline">
        <div className="mx-auto max-w-6xl px-5 py-10">
          <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
            <div className="max-w-sm">
              <Logo />
              <p className="mt-3 text-sm text-t-2">
                Dokunma değil, kapanış. Kurala bağlı, kapanış teyitli bir karar akışı.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-x-12 gap-y-2 text-sm">
              {NAV.slice(1).map((n) => (
                <Link key={n.to} to={n.to} className="text-t-2 transition-colors duration-150 hover:text-t-1">
                  {n.label}
                </Link>
              ))}
            </div>
          </div>
          <div className="mt-8">
            <Disclaimer />
          </div>
          <p className="mt-4 text-xs text-t-3">© 2026 Kapanış. Tüm hakları saklıdır.</p>
        </div>
      </footer>
    </div>
  );
}
