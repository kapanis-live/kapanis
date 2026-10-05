import { useFlash } from "@/lib/smooth";
// Kapanış tasarım sistemi bileşenleri (Claude Design "Kapanış" sistemi: tokens + bundle.css karşılıkları).
// Bütün ölçüler rem: tarayıcı yakınlaştırması bütün arayüzü birlikte büyütür.
import { cn } from "@/lib/utils";
import { formatPct } from "@/lib/format";
import { px } from "@/lib/portfolio";
import { Search } from "lucide-react";

// Segmented: piyasa, zaman dilimi, sekme seçimi
export function Segmented({ options, value, onChange, ariaLabel, className }) {
  return (
    <div role="tablist" aria-label={ariaLabel}
      className={cn("inline-flex max-w-full gap-0.5 overflow-x-auto rounded-[10px] border border-hairline bg-ink p-[3px]", className)}>
      {options.map((o) => {
        const opt = typeof o === "string" ? { value: o, label: o } : o;
        const active = opt.value === value;
        return (
          <button key={opt.value} role="tab" aria-selected={active} onClick={() => onChange?.(opt.value)}
            className={cn("h-9 whitespace-nowrap rounded-[7px] px-3.5 text-[0.9375rem] font-semibold transition-colors duration-150",
              active ? "bg-raised text-t-1 ring-1 ring-inset ring-strong" : "text-t-2 hover:text-t-1")}>
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// Gösterge çipi: renkli çizgi (swatch) + ad; kapalıyken soluk
export function Chip({ active, color, onClick, children }) {
  return (
    <button onClick={onClick} aria-pressed={!!active}
      className={cn("inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-[0.9375rem] font-semibold transition-colors duration-150",
        active ? "border-strong bg-raised text-t-1" : "border-hairline text-t-3 hover:bg-raised hover:text-t-2")}>
      {color && <span className="w-4 rounded-sm" style={{ background: color, height: active ? 3 : 2, opacity: active ? 1 : 0.35 }} />}
      {children}
    </button>
  );
}

export function SearchField({ value, onChange, onSubmit, placeholder = "Kod ara", list, className }) {
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit?.(value); }}
      className={cn("inline-flex h-11 min-w-[14rem] items-center gap-2.5 rounded-[10px] border border-hairline bg-ink px-3.5 text-t-3 transition-colors duration-150 focus-within:border-info", className)}>
      <Search className="h-[1.125rem] w-[1.125rem] shrink-0" aria-hidden />
      <input value={value} onChange={(e) => onChange?.(e.target.value)} placeholder={placeholder} list={list}
        className="min-w-0 flex-1 border-0 bg-transparent text-base uppercase text-t-1 outline-none placeholder:normal-case placeholder:text-t-3" />
    </form>
  );
}

const BTN = {
  primary: "border-brand bg-brand text-on-brand hover:brightness-110",
  secondary: "border-hairline bg-surface text-t-1 hover:border-strong hover:bg-raised",
  ghost: "border-transparent bg-transparent text-t-2 hover:bg-raised hover:text-t-1",
};

export function KButton({ variant = "secondary", className, icon, children, ...rest }) {
  return (
    <button {...rest}
      className={cn("inline-flex h-11 items-center justify-center gap-2 whitespace-nowrap rounded-[10px] border px-[1.125rem] text-base font-semibold transition-colors duration-150 disabled:cursor-default disabled:opacity-45",
        BTN[variant], className)}>
      {icon}{children}
    </button>
  );
}

// ▲ %2,41 rozeti (yön metin işaretiyle de anlatılır)
export function ChangeBadge({ value, label, size, decimals = 2, className }) {
  if (value === null || value === undefined || isNaN(Number(value))) return <span className="text-t-3">—</span>;
  const n = Number(value);
  const flat = Number(Math.abs(n).toFixed(decimals)) === 0;
  const tone = flat ? "bg-t-2/[0.12] text-t-2" : n > 0 ? "bg-up/15 text-up" : "bg-down/15 text-down";
  return (
    <span className={cn("num inline-flex items-center gap-[0.3125rem] whitespace-nowrap rounded-lg font-semibold leading-[1.375rem]",
      size === "lg" ? "px-2.5 py-[0.3125rem] text-[1.0625rem]" : "px-2 py-1 text-base", tone, className)}>
      {label && <span className="mr-0.5 font-medium text-t-2">{label}</span>}
      {!flat && <span aria-hidden className="text-[0.8125rem]">{n > 0 ? "▲" : "▼"}</span>}
      {formatPct(Math.abs(n), { decimals, sign: false })}
    </span>
  );
}

// Trend: ↗ güçlü (yeşil) · → karışık (gri) · ↘ zayıf (kırmızı)
export function Trend({ label }) {
  const t = String(label || "");
  const dir = t.startsWith("↗") ? "up" : t.startsWith("↘") ? "down" : t.startsWith("→") ? "flat" : null;
  const text = t.replace(/^[↗↘→]\s*/, "") || (dir === "up" ? "yükseliş" : dir === "down" ? "düşüş" : "");
  if (!dir) return <span className="text-t-3">{t || "—"}</span>;
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold", dir === "up" ? "text-up" : dir === "down" ? "text-down" : "text-t-2")}>
      <span className="text-[1.375rem] leading-none" aria-hidden>{dir === "up" ? "↗" : dir === "down" ? "↘" : "→"}</span>
      {text}
    </span>
  );
}

// RSI: sayı + çubuk (70 üstü ısınmış, 30 altı çok satılmış)
export function RsiMeter({ value }) {
  if (value === null || value === undefined) return <span className="text-t-3">—</span>;
  const v = Math.round(value);
  const hot = v >= 70;
  const cold = v <= 30;
  return (
    <span className="inline-flex items-center gap-2.5" title={hot ? "Isınmış" : cold ? "Çok satılmış" : "Normal"}>
      <span className={cn("num min-w-[1.75rem] text-right font-semibold", hot ? "text-wait" : cold ? "text-info" : "text-t-1")}>{v}</span>
      <span className="relative h-1.5 w-[4.5rem] overflow-hidden rounded-[3px] bg-hairline">
        <span className={cn("absolute inset-y-0 left-0 rounded-[3px]", hot ? "bg-wait" : cold ? "bg-info" : "bg-t-3")} style={{ width: `${Math.min(100, v)}%` }} />
        <span className="absolute inset-y-0 w-px bg-ink" style={{ left: "30%" }} />
        <span className="absolute inset-y-0 w-px bg-ink" style={{ left: "70%" }} />
      </span>
    </span>
  );
}

// Destek → direnç arasında fiyatın konumu
export function RangeBar({ support, supportPct, resistance, resistancePct, price }) {
  const has = support != null && resistance != null && resistance > support;
  const pos = has ? Math.min(100, Math.max(0, ((price - support) / (resistance - support)) * 100)) : null;
  const pct = (v) => (v == null ? "" : ` (${formatPct(v, { decimals: 1 })})`);
  return (
    <span className="inline-flex min-w-[10rem] flex-col gap-1.5">
      <span className="num flex flex-wrap items-center gap-x-1.5 text-[0.9375rem] text-t-2">
        <span>{support != null ? px(support) + pct(supportPct) : "—"}</span>
        <span className="text-t-3">→</span>
        <span>{resistance != null ? px(resistance) + pct(resistancePct) : "—"}</span>
      </span>
      {has && (
        <span className="relative h-1.5 rounded-[3px] bg-hairline">
          <span className="absolute top-1/2 -ml-1.5 -mt-1.5 h-3 w-3 rounded-full bg-t-1 shadow-[0_0_0_2px_rgb(var(--c-surface))]" style={{ left: `${pos}%` }} />
        </span>
      )}
    </span>
  );
}

// Grafik altındaki düz Türkçe sinyal kartı
const SIG_DOT = { up: "bg-up", down: "bg-down", warn: "bg-wait", info: "bg-info", flat: "bg-t-3" };
export function SignalCard({ title, verdict, detail, tone = "flat" }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-hairline bg-surface px-[1.375rem] py-5">
      <div className="text-sm font-semibold tracking-[0.02em] text-t-3">{title}</div>
      <div className="flex items-center gap-2.5 text-xl font-bold leading-snug text-t-1">
        <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", SIG_DOT[tone])} />{verdict}
      </div>
      {detail && <p className="m-0 text-base leading-normal text-t-2">{detail}</p>}
    </div>
  );
}

// Kart içindeki küçük bilgi kutucuğu (Yatırdığın / Şimdiki değeri ...)
export function Tile({ label, children }) {
  return (
    <div className="flex flex-col gap-1 rounded-[10px] border border-hairline bg-ink px-4 py-3.5">
      <span className="text-sm font-medium text-t-3">{label}</span>
      <span className="num text-lg font-bold text-t-1">{children}</span>
    </div>
  );
}

// Sayı değişince kısa yeşil/kırmızı parlama (fiyat, değer); hareket azaltma ayarında kapalı
export function FlashValue({ value, children, className }) {
  const ref = useFlash(value);
  return <span ref={ref} className={className} style={{ padding: "0 0.15em", margin: "0 -0.15em" }}>{children}</span>;
}
