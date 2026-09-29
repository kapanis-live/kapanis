import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate, Link } from "react-router-dom";
import { usePrefetch, usePullToRefresh, haptic } from "@/lib/smooth";
import { K } from "@/ds";
import { Disclaimer } from "@/components/Disclaimer";
import { useAuth } from "@/context/AuthContext";
import { useData, usePendingCommands } from "@/lib/useData";
import { useTheme, FONT_SIZES } from "@/lib/theme";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  LayoutGrid, Bell, Activity, Wallet, FileBarChart, Globe2, Receipt, LineChart, FlaskConical,
  Settings as SettingsIcon, LogOut, Menu, X, PieChart, Eye, ShieldCheck, Sun, Moon, Zap, Clock, CandlestickChart, Target, ClipboardCheck, UserRound, Briefcase, Users as UsersIcon, HeartPulse,
} from "lucide-react";

const NAV = [
  { group: "Özet", items: [{ to: "/app", label: "Genel Bakış", icon: LayoutGrid, end: true }] },
  {
    group: "Portföy",
    items: [
      { to: "/app/portfoy", label: "Portföy", icon: PieChart },
      { to: "/app/takip", label: "Takip Listem", icon: Eye },
      { to: "/app/pozisyonlar", label: "Pozisyonlar", icon: Wallet },
    ],
  },
  {
    group: "Sinyaller",
    items: [
      { to: "/app/sinyaller", label: "Sinyaller & Analiz", icon: Activity },
      { to: "/app/analizlerim", label: "Son Analizlerim", icon: FileBarChart },
      { to: "/app/stratejiler", label: "Strateji Kurucu", icon: FlaskConical },
      { to: "/app/kriz", label: "Kriz Planı", icon: ShieldCheck },
      { to: "/app/planlar", label: "Planlar & Fırsatlar", icon: Target },
      { to: "/app/kontrol", label: "Kontrol & Karşılaştır", icon: ClipboardCheck },
      { to: "/app/alarmlar", label: "Alarmlar", icon: Bell },
      { to: "/app/alarmlarim", label: "Grafik alarmlarım", icon: Bell },
    ],
  },
  {
    group: "Performans",
    items: [
      { to: "/app/disiplin", label: "Disiplin & Günlük", icon: ShieldCheck },
      { to: "/app/rapor", label: "Rapor & Kural Karnesi", icon: FileBarChart },
      { to: "/app/backtest", label: "Backtest", icon: FlaskConical },
    ],
  },
  {
    group: "Piyasa",
    items: [
      { to: "/app/grafik", label: "Grafik", icon: CandlestickChart },
      { to: "/app/makro", label: "Makro", icon: Globe2 },
      { to: "/app/vadeli", label: "Vadeli", icon: LineChart },
    ],
  },
  {
    group: "Sistem",
    items: [
      { to: "/app/maliyet", label: "Yapay zekâ maliyeti", icon: Receipt },
      { to: "/app/ayarlar", label: "Ayarlar", icon: SettingsIcon },
      { to: "/app/kullanicilar", label: "Kullanıcılar", icon: UsersIcon },
      { to: "/app/hesap", label: "Hesap & Telegram", icon: UserRound },
    ],
  },
];

// Sistem sahibi olmayan kullanıcı: kendi portföyü, piyasa sayfaları, hesabı (botun kişisel verisi kapalı)
const USER_NAV = [
  { group: "Portföy", items: [{ to: "/app/portfoyum", label: "Portföyüm", icon: Briefcase },
    { to: "/app/saglik", label: "Portföy sağlığı", icon: HeartPulse },
    { to: "/app/karnem", label: "Karnem", icon: ClipboardCheck },
    { to: "/app/alarmlarim", label: "Alarmlarım", icon: Bell },
    { to: "/app/kriz", label: "Kriz Planı", icon: ShieldCheck }] },
  {
    group: "Piyasa",
    items: [
      { to: "/app/grafik", label: "Grafik & Analiz", icon: CandlestickChart },
      { to: "/app/analizlerim", label: "Son Analizlerim", icon: FileBarChart },
      { to: "/app/stratejiler", label: "Strateji Kurucu", icon: FlaskConical },
      { to: "/app/makro", label: "Makro", icon: Globe2 },
      { to: "/app/vadeli", label: "Vadeli", icon: LineChart },
    ],
  },
  { group: "Hesap", items: [{ to: "/app/hesap", label: "Hesap & Telegram", icon: UserRound }] },
];

const USER_MOBILE_NAV = [
  { to: "/app/portfoyum", label: "Portföy", icon: Briefcase },
  { to: "/app/grafik", label: "Grafik", icon: CandlestickChart },
  { to: "/app/alarmlarim", label: "Alarm", icon: Bell },
  { to: "/app/hesap", label: "Hesap", icon: UserRound },
];

const MOBILE_NAV = [
  { to: "/app", label: "Özet", icon: LayoutGrid, end: true },
  { to: "/app/portfoy", label: "Portföy", icon: PieChart },
  { to: "/app/takip", label: "Takip", icon: Eye },
  { to: "/app/grafik", label: "Grafik", icon: CandlestickChart },
  { to: "/app/sinyaller", label: "Sinyal", icon: Activity },
];

const BOT_FRESH_MINUTES = 20;

// Saat dilimindeki hafta günü (0 = pazar) ve günün dakikası
function zoned(tz) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date());
  const get = (t) => parts.find((p) => p.type === t)?.value;
  const day = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(get("weekday"));
  return { day, minutes: Number(get("hour")) * 60 + Number(get("minute")) };
}

// Resmi tatiller hesaba katılmaz; bot tarafındaki kapanış kontrolü asıl kaynaktır.
export function marketStatus() {
  const tr = zoned("Europe/Istanbul");
  const ny = zoned("America/New_York");
  const weekday = (z) => z.day >= 1 && z.day <= 5;
  return {
    BIST: weekday(tr) && tr.minutes >= 600 && tr.minutes < 1080,
    ABD: weekday(ny) && ny.minutes >= 570 && ny.minutes < 960,
    weekendTR: !weekday(tr),
  };
}

function useMarketStatus() {
  const [s, setS] = useState(marketStatus);
  useEffect(() => {
    const id = setInterval(() => setS(marketStatus()), 60_000);
    return () => clearInterval(id);
  }, []);
  return s;
}

function Dot({ tone }) {
  return <span className={cn("inline-block h-2 w-2 rounded-full", tone === "up" ? "bg-up" : tone === "down" ? "bg-down" : "bg-t-3")} />;
}

function StatusStrip() {
  const bot = useData("bot-status", "/bot/status", { refetchInterval: 30_000 });
  const m = useMarketStatus();
  const last = bot.data?.last_ingest;
  const online = last && Date.now() - new Date(last).getTime() < BOT_FRESH_MINUTES * 60_000;
  const closedNote = m.weekendTR ? "kapalı · son seans Cuma" : "kapalı";
  return (
    <div className="flex min-w-0 items-center gap-3 overflow-x-auto whitespace-nowrap text-sm text-t-2" data-testid="status-strip">
      <span className={cn("inline-flex items-center gap-1.5 font-medium", online ? "text-up" : "text-down")} title={last ? `Son veri: ${relativeTime(last)}` : "Bot henüz veri göndermedi"}>
        <Dot tone={online ? "up" : "down"} />
        {online ? "Bot çevrimiçi" : `Bot yanıt vermiyor${last ? ` (son veri ${relativeTime(last)})` : ""}`}
      </span>
      <span className="text-hairline">|</span>
      <span className="inline-flex items-center gap-1.5"><Dot tone={m.BIST ? "up" : "none"} />BIST {m.BIST ? "açık" : closedNote}</span>
      <span className="hidden items-center gap-1.5 sm:inline-flex"><Dot tone={m.ABD ? "up" : "none"} />NYSE {m.ABD ? "açık" : closedNote}</span>
      <span className="hidden items-center gap-1.5 md:inline-flex"><Dot tone="up" />Kripto 7/24</span>
    </div>
  );
}

function TopActions({ onLogout }) {
  const { theme, toggle, size, setSize } = useTheme();
  const { user, owner } = useAuth();
  const overview = useData("overview", "/overview", { refetchInterval: 30_000, enabled: owner });
  const pend = usePendingCommands();
  const decisions = overview.data?.pending_decisions || 0;
  return (
    <div className="flex shrink-0 items-center gap-2">
      {pend.pending.length > 0 && (
        <span className="hidden items-center gap-1.5 rounded-lg border border-info/40 bg-info/10 px-2.5 py-1.5 text-xs font-semibold text-info sm:inline-flex" data-testid="pending-commands">
          <Clock className="h-3.5 w-3.5" /> {pend.pending.length} işlem bota iletildi
        </span>
      )}
      {decisions > 0 && (
        <Link to="/app/sinyaller" className="inline-flex items-center gap-1.5 rounded-lg border border-wait/40 bg-wait/10 px-2.5 py-1.5 text-xs font-semibold text-wait hover:bg-wait/15" data-testid="pending-decisions">
          <Zap className="h-3.5 w-3.5" /> {decisions}<span className="hidden sm:inline"> bekleyen karar</span>
        </Link>
      )}
      <div className="hidden items-center rounded-[10px] border border-hairline bg-ink p-[3px] sm:inline-flex" title="Yazı boyutu">
        <button onClick={() => setSize(size - 1)} disabled={size === 0} aria-label="Yazıyı küçült" data-testid="font-smaller"
          className="h-9 w-10 rounded-[7px] text-[0.9375rem] font-bold text-t-2 transition-colors duration-150 hover:bg-raised hover:text-t-1 disabled:opacity-40">A−</button>
        <span className="num min-w-[3.25rem] text-center text-sm text-t-3">{FONT_SIZES[size]}px</span>
        <button onClick={() => setSize(size + 1)} disabled={size === FONT_SIZES.length - 1} aria-label="Yazıyı büyüt" data-testid="font-bigger"
          className="h-9 w-10 rounded-[7px] text-lg font-bold text-t-2 transition-colors duration-150 hover:bg-raised hover:text-t-1 disabled:opacity-40">A+</button>
      </div>
      <button onClick={toggle} aria-label="Temayı değiştir" data-testid="theme-toggle"
        className="rounded-lg p-2 text-t-2 transition-colors duration-150 hover:bg-raised hover:text-t-1">
        {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>
      <button onClick={onLogout} data-testid="logout-btn" title={user?.email}
        className="inline-flex items-center gap-2 rounded-lg border border-hairline bg-surface px-2.5 py-1.5 text-xs font-semibold text-t-1 transition-colors duration-150 hover:bg-raised">
        <span className="grid h-5 w-5 place-items-center rounded-full bg-brand/20 text-[10px] text-brand">{(user?.name || "A")[0].toUpperCase()}</span>
        <span className="hidden sm:inline">{user?.name || "Admin"}</span>
        <LogOut className="h-3.5 w-3.5 text-t-3" />
      </button>
    </div>
  );
}

function SideNav({ onClick }) {
  const prefetch = usePrefetch();
  const { owner } = useAuth();
  return (
    <nav className="space-y-5">
      {(owner ? NAV : USER_NAV).map((g) => (
        <div key={g.group}>
          <p className="eyebrow mb-2 px-3 text-[10px] text-t-3">{g.group}</p>
          <div className="space-y-0.5">
            {g.items.map((n) => {
              const Icon = n.icon;
              return (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  onClick={onClick}
                  onMouseEnter={() => prefetch(n.to)}
                  onTouchStart={() => prefetch(n.to)}
                  data-testid={`side-nav-${n.to === "/app" ? "overview" : n.to.split("/").pop()}`}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-lg border-l-[3px] px-3 py-2 text-[15px] transition-colors duration-150",
                      isActive
                        ? "border-brand bg-brand/10 font-semibold text-t-1"
                        : "border-transparent text-t-2 hover:bg-raised hover:text-t-1"
                    )
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {n.label}
                </NavLink>
              );
            })}
          </div>
        </div>
      ))}
    </nav>
  );
}

function Brand() {
  return (
    <Link to="/app" data-testid="brand-logo" aria-label="Kapanış · Genel bakış">
      <K.BrandMark size="md" />
    </Link>
  );
}

function SideFooter() {
  return (
    <div className="rounded-lg border border-hairline bg-ink/60 p-3">
      <p className="text-[11px] leading-4 text-t-2">Bu panel fikir üretir; karar senindir. Bot işlem yapmaz.</p>
    </div>
  );
}

export function PanelLayout({ children }) {
  const [open, setOpen] = useState(false);
  const { logout, owner } = useAuth();
  const myPortfolio = useData("my-portfolio", "/portfolio", { refetchInterval: 8000 });
  const loc = useLocation();
  const navigate = useNavigate();
  const prefetch = usePrefetch();
  const mainRef = useRef(null);
  usePullToRefresh(mainRef);

  const handleLogout = async () => {
    await logout();
    navigate("/giris");
  };

  return (
    <div className={cn("min-h-screen bg-ink text-t-1", myPortfolio.data?.risk_mode === "defansif" && "kp-defensive")}>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-hairline bg-side lg:flex">
        <div className="px-5 pb-6 pt-5"><Brand /></div>
        <div className="flex-1 overflow-y-auto px-3 pb-4"><SideNav /></div>
        <div className="p-4"><SideFooter /></div>
      </aside>

      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-ink/80 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-72 flex-col border-r border-hairline bg-side animate-fade-in">
            <div className="flex items-center justify-between px-5 pb-6 pt-5">
              <Brand />
              <button onClick={() => setOpen(false)} aria-label="Kapat"><X className="h-5 w-5 text-t-1" /></button>
            </div>
            <div className="flex-1 overflow-y-auto px-3 pb-4"><SideNav onClick={() => setOpen(false)} /></div>
            <div className="p-4"><SideFooter /></div>
          </div>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-40 flex h-16 items-center justify-between gap-3 border-b border-hairline bg-ink/90 px-4 backdrop-blur md:px-7">
          <div className="flex min-w-0 items-center gap-3">
            <button onClick={() => setOpen(true)} data-testid="panel-menu-toggle" aria-label="Menü" className="rounded-lg p-2 hover:bg-raised lg:hidden">
              <Menu className="h-5 w-5 text-t-1" />
            </button>
            <StatusStrip />
          </div>
          <TopActions onLogout={handleLogout} />
        </header>

        {myPortfolio.data?.risk_mode === "defansif" && <Link to="/app/kriz" className="kp-defensive-banner block px-4 py-2 text-sm font-semibold md:px-7">
          Defansif mod açık · risk hedefi %{myPortfolio.data.risk_target_pct} · Planı gör →
        </Link>}

        <main ref={mainRef} key={loc.pathname} className="kp-main kp-page-enter mx-auto max-w-[1400px] px-4 pb-24 pt-7 md:px-7 lg:px-10 lg:pb-10">
          {children}
          <Disclaimer />
        </main>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 flex h-16 items-center justify-around border-t border-hairline bg-surface/95 backdrop-blur lg:hidden">
        {(owner ? MOBILE_NAV : USER_MOBILE_NAV).map((n) => {
          const Icon = n.icon;
          return (
            <NavLink key={n.to} to={n.to} end={n.end} onTouchStart={() => prefetch(n.to)} onClick={haptic}
              className={({ isActive }) => cn("flex flex-col items-center gap-1 px-3 py-1 text-[11px] transition-transform duration-100 active:scale-95", isActive ? "text-brand" : "text-t-2")}>
              <Icon className="h-4 w-4" />{n.label}
            </NavLink>
          );
        })}
      </nav>
    </div>
  );
}

export function PageHeader({ title, subtitle, action, testid }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4 pb-6" data-testid={testid}>
      <div>
        <h1 className="m-0 text-[1.875rem] font-bold leading-[1.15] tracking-[-0.01em] text-t-1 sm:text-[2.125rem]">{title}</h1>
        {subtitle && <p className="mb-0 mt-1.5 text-[1.0625rem] text-t-2">{subtitle}</p>}
      </div>
      {action && <div className="flex flex-wrap items-center gap-3">{action}</div>}
    </div>
  );
}
