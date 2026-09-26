import { formatNumber, trDecimal } from "@/lib/format";

export const MARKET_LABEL = { BIST: "BIST", KRIPTO: "Kripto", ABD: "ABD", DIGER: "Altın/Döviz" };
export const MARKET_ORDER = ["BIST", "KRIPTO", "ABD", "DIGER"];
export const MARKET_TONE = { KRIPTO: "brand", BIST: "wait", ABD: "info", DIGER: "violet" };

// 0,00000594 okunur kalır, 416,28 kuruşunu korur
export function px(v) {
  if (v === null || v === undefined || isNaN(Number(v))) return "—";
  const a = Math.abs(v);
  if (a > 0 && a < 0.01) return trDecimal(Number(v).toFixed(10).replace(/0+$/, ""));
  return formatNumber(v, { decimals: a < 1 ? 4 : 2 });
}

// 5.047.971 · 46,198 (kesirli adet yuvarlanmaz)
export function qty(v) {
  if (v === null || v === undefined) return "—";
  if (Number.isInteger(v)) return formatNumber(v, { decimals: 0 });
  return formatNumber(v, { decimals: 6 }).replace(/0+$/, "").replace(/,$/, "");
}

export function money(v, cur) {
  return v === null || v === undefined ? "—" : `${formatNumber(v, { decimals: 2 })} ${cur || ""}`.trim();
}

export function isWeekendTR() {
  const d = new Intl.DateTimeFormat("en-US", { timeZone: "Europe/Istanbul", weekday: "short" }).format(new Date());
  return d === "Sat" || d === "Sun";
}

// BIST/ABD için "bugün" etiketi; hafta sonu son seans, kripto 24 saat
export function dayLabel(market) {
  if (market === "KRIPTO") return "24 saat";
  return isWeekendTR() ? "Son seans" : "Bugün";
}

// Portföy satırlarından piyasa başına toplam (değer, maliyet, günlük tutar)
export function marketTotals(rows) {
  const out = {};
  for (const g of rows || []) {
    if (!out[g.piyasa]) out[g.piyasa] = { para: g.para, deger: 0, maliyet: 0, gun: 0, adet: 0 };
    const t = out[g.piyasa];
    t.deger += g.deger;
    t.maliyet += g.maliyet;
    t.adet += 1;
    if (g.gun_yuzde !== null && g.gun_yuzde !== undefined) t.gun += g.deger - g.deger / (1 + g.gun_yuzde / 100);
  }
  for (const t of Object.values(out)) {
    const start = t.deger - t.gun;
    t.gun_yuzde = start ? (t.gun / start) * 100 : null;
    t.kz = t.deger - t.maliyet;
    t.kz_yuzde = t.maliyet ? (t.kz / t.maliyet) * 100 : null;
  }
  return out;
}

// "KTLEV", "SHIB/USDT", "NVDA.US" -> takip listesindeki kod
export function baseCode(name) {
  return String(name || "").split("/")[0].replace(/\.(IS|US)$/i, "").toUpperCase();
}
