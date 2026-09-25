import { cn } from "@/lib/utils";
import { formatPct } from "@/lib/format";

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

// R/R eşiklerine göre renk: <1.5 kırmızı, 1.5–2 sarı, ≥2 yeşil
export function rrTone(rr) {
  if (rr === null || rr === undefined || isNaN(rr)) return "muted";
  if (rr >= 2) return "up";
  if (rr >= 1.5) return "wait";
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

export function DeltaText({ value, suffix = "%", className }) {
  const up = Number(value) >= 0;
  return (
    <span className={cn("num font-semibold", up ? "text-up" : "text-down", className)}>
      {suffix === "%" ? formatPct(value) : (up ? "+" : "") + Number(value).toFixed(2)}
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
