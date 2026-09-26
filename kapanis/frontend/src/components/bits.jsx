import { cn } from "@/lib/utils";
import { formatPct } from "@/lib/format";
import { ChangeBadge } from "@/components/kp";

export function SideBadge({ side }) {
  const long = side === "long";
  return (
    <span
      data-testid="side-badge"
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide",
        long ? "bg-up/12 text-up" : "bg-down/12 text-down"
      )}
    >
      {long ? "LONG" : "SHORT"}
    </span>
  );
}

const STATUS_MAP = {
  armed: { label: "Kurulu", cls: "bg-info/12 text-info" },
  triggered: { label: "Tetiklendi", cls: "bg-up/12 text-up" },
  cancelled: { label: "İptal", cls: "bg-t-3/20 text-t-2" },
  pending: { label: "Beklemede", cls: "bg-wait/12 text-wait" },
  open: { label: "Açık", cls: "bg-up/12 text-up" },
  closed: { label: "Kapandı", cls: "bg-t-3/20 text-t-2" },
  resolved: { label: "Karar verildi", cls: "bg-t-3/20 text-t-2" },
};

export function StatusBadge({ status }) {
  const s = STATUS_MAP[status] || { label: status, cls: "bg-t-3/20 text-t-2" };
  return (
    <span data-testid="status-badge" className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium", s.cls)}>
      {s.label}
    </span>
  );
}

// R/R eşikleri botun kuralıyla aynı: <1 kırmızı (pas), 1–1.5 sarı (RİSK-OFF'ta pas), ≥1.5 yeşil
export function rrTone(rr) {
  if (rr === null || rr === undefined || isNaN(rr)) return "muted";
  if (rr >= 1.5) return "up";
  if (rr >= 1) return "wait";
  return "down";
}

const RR_CLS = {
  up: "border-up/40 bg-up/10 text-up",
  wait: "border-wait/40 bg-wait/10 text-wait",
  down: "border-down/40 bg-down/10 text-down",
  muted: "border-hairline bg-surface text-t-2",
};

export function RRPill({ rr, className, testid = "rr-pill" }) {
  const tone = rrTone(rr);
  return (
    <span
      data-testid={testid}
      className={cn("num inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold", RR_CLS[tone], className)}
    >
      R/R {rr === null || rr === undefined || isNaN(rr) ? "—" : Number(rr).toFixed(2)}
    </span>
  );
}

// Yükseliş/düşüş sadece renkle değil ▲ ▼ işaretiyle de anlatılır.
export function DeltaText({ value, suffix = "%", className, arrow = true }) {
  if (value === null || value === undefined || isNaN(Number(value))) return <span className="num text-t-3">—</span>;
  const n = Number(value);
  const up = n >= 0;
  return (
    <span className={cn("num font-semibold", n === 0 ? "text-t-2" : up ? "text-up" : "text-down", className)}>
      {arrow && n !== 0 ? (up ? "▲ " : "▼ ") : ""}
      {suffix === "%" ? formatPct(n) : (up ? "+" : "") + n.toFixed(2)}
    </span>
  );
}

// Renkli zeminli yüzde rozeti = tasarım sistemindeki ChangeBadge
export function PctBadge({ value, decimals = 2, className, size }) {
  return <ChangeBadge value={value} decimals={decimals} className={className} size={size} />;
}

const MARKET_DOT = { KRIPTO: "bg-brand", BIST: "bg-wait", ABD: "bg-info", DIGER: "bg-violet" };
const MARKET_NAME = { BIST: "BIST", KRIPTO: "Kripto", ABD: "ABD", DIGER: "Altın/Döviz" };

// Piyasa etiketi: renkli nokta + ad (bayrak emojisi Windows'ta görünmüyor)
export function MarketTag({ m, className, label }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span className={cn("inline-block h-2 w-2 shrink-0 rounded-full", MARKET_DOT[m] || "bg-t-3")} />
      {label ?? MARKET_NAME[m] ?? m}
    </span>
  );
}

export function StaleBadge() {
  return (
    <span
      data-testid="stale-badge"
      className="inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium bg-wait/12 text-wait border border-wait/30"
    >
      Bayat veri
    </span>
  );
}
