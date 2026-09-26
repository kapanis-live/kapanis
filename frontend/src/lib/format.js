// Sayı biçimi tr-TR: 84.350,25 (binlik nokta, ondalık virgül), negatifte gerçek eksi
export const MINUS = "−";

export function formatNumber(value, opts = {}) {
  const { decimals = 2, sign = false } = opts;
  if (value === null || value === undefined || value === "" || isNaN(Number(value))) return "—";
  const n = Number(value);
  const fixed = Math.abs(n).toFixed(decimals);
  const zero = Number(fixed) === 0;
  let [intPart, decPart] = fixed.split(".");
  intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  let out = decPart ? `${intPart},${decPart}` : intPart;
  if (n < 0 && !zero) out = MINUS + out;
  else if (sign && !zero) out = "+" + out;
  return out;
}

// Serbest ondalıklı sayı metnini (ör. "0.00000594") Türkçe yaz
export function trDecimal(str) {
  const s = String(str);
  const neg = s.startsWith("-");
  const [i, d] = s.replace("-", "").split(".");
  const int = i.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return (neg ? MINUS : "") + (d ? `${int},${d}` : int);
}

export function formatPrice(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (isNaN(n)) return "—";
  const decimals = Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 2 : 4;
  return formatNumber(n, { decimals });
}

// Yüzde işareti önde: +%2,41 · −%0,85 · %12,0 (sign: false)
export function formatPct(value, opts = {}) {
  const { decimals = 2, sign = true } = opts;
  if (value === null || value === undefined || isNaN(Number(value))) return "—";
  const n = Number(value);
  const body = "%" + formatNumber(Math.abs(n), { decimals });
  if (Number(Math.abs(n).toFixed(decimals)) === 0) return body;
  if (n < 0) return MINUS + body;
  return sign ? "+" + body : body;
}

export function formatCurrency(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(Number(value))) return "—";
  const n = Number(value);
  return (n < 0 ? MINUS : "") + "$" + formatNumber(Math.abs(n), { decimals });
}

export function formatCompact(value) {
  const n = Number(value);
  if (isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return formatNumber(n / 1e9, { decimals: 2 }) + "B";
  if (abs >= 1e6) return formatNumber(n / 1e6, { decimals: 2 }) + "M";
  if (abs >= 1e3) return formatNumber(n / 1e3, { decimals: 1 }) + "K";
  return formatNumber(n, { decimals: 0 });
}

export function formatTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("tr-TR", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

export function relativeTime(iso) {
  if (!iso) return "—";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  const abs = Math.abs(diff);
  const future = diff < 0;
  const fmt = (v, unit) => (future ? `${v} ${unit} sonra` : `${v} ${unit} önce`);
  if (abs < 60) return future ? "birazdan" : "az önce";
  if (abs < 3600) return fmt(Math.round(abs / 60), "dk");
  if (abs < 86400) return fmt(Math.round(abs / 3600), "sa");
  return fmt(Math.round(abs / 86400), "gün");
}
