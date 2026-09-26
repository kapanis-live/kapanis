// Botun panel verisini tasarım sistemi bileşenlerinin beklediği biçime çevirir.
import { U } from "@/ds";
import { marketTotals, baseCode } from "@/lib/portfolio";
import "@/components/AssetLogo"; // window.KapanisLogo kaydı

export const MARKET_UI = {
  BIST: { label: "BIST", cur: "TRY", color: "var(--cat-1)" },
  KRIPTO: { label: "Kripto", cur: "USD", color: "var(--cat-2)" },
  ABD: { label: "ABD", cur: "USD", color: "var(--cat-3)" },
  DIGER: { label: "Altın/Döviz", cur: "TRY", color: "var(--cat-4)" },
};
export const MARKET_KEYS = ["BIST", "KRIPTO", "ABD", "DIGER"];
export const curOf = (c) => (c === "TL" || c === "TRY" ? "TRY" : "USD");
// Tasarım sistemi Ticker'ına verilen logo: tek bileşen (AssetLogo) kod + piyasaya göre çizer
export const logo = (code, market) => ({ code: baseCode(code), market });

// Piyasa başına toplamlar: MarketCard ve PulseList için
export function marketRows(portfoy) {
  const totals = marketTotals(portfoy || []);
  return MARKET_KEYS.filter((m) => totals[m]).map((m) => {
    const t = totals[m];
    return {
      key: m, label: MARKET_UI[m].label, cur: MARKET_UI[m].cur, color: MARKET_UI[m].color,
      value: t.deger, cost: t.maliyet, pl: t.kz, day: t.gun_yuzde ?? 0, total: t.kz_yuzde ?? 0, count: t.adet,
    };
  });
}

// Imza: "+%1,2" / "−%0,4"
export const signedPct = (v, d = 1) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}%${U.fmtNum(Math.abs(v), d)}`);

export function istTime(iso, withDay = false) {
  if (!iso) return "—";
  const d = new Date(iso);
  const opts = { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit", ...(withDay ? { day: "numeric", month: "short" } : {}) };
  return d.toLocaleString("tr-TR", opts);
}

// Bugün / Dün / 24 Eyl + saat
export function relDay(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const key = (x) => x.toLocaleDateString("tr-TR", { timeZone: "Europe/Istanbul" });
  const now = new Date();
  const y = new Date(now.getTime() - 86400000);
  const hm = d.toLocaleTimeString("tr-TR", { timeZone: "Europe/Istanbul", hour: "2-digit", minute: "2-digit" });
  if (key(d) === key(now)) return `Bugün ${hm}`;
  if (key(d) === key(y)) return `Dün ${hm}`;
  return `${d.toLocaleDateString("tr-TR", { timeZone: "Europe/Istanbul", day: "numeric", month: "short" })} ${hm}`;
}

// Yapay zekâ metninin sonundaki "🧠 Model" satırını ayır; metindeki emojileri temizle (sistem: emoji yok)
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F000}-\u{1F2FF}\u{FE0F}]/gu;
export function splitAi(text) {
  if (!text) return { body: "", model: null };
  const lines = String(text).trim().split("\n");
  let model = null;
  const last = lines[lines.length - 1] || "";
  if (last.includes("🧠")) {
    model = last.replace("🧠", "").replace(/\(yedek.*\)/, "").trim();
    lines.pop();
  }
  return { body: lines.join("\n").replace(EMOJI, "").replace(/\*\*/g, "").trim(), model };
}

// Çok küçük fiyatlar (SHIB 0,00000592) kısalmasın
export const priceFmt = (v, cur) => (v == null ? "—" : U.fmtPrice(v, cur, Math.abs(v) > 0 && Math.abs(v) < 0.01 ? 8 : undefined));
