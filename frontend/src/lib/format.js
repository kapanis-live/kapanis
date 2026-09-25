// Sayı biçimi: 84 350.25 (binlik ayıracı ince boşluk, ondalık nokta)
const THIN = "\u2009";

export function formatNumber(value, opts = {}) {
  const { decimals = 2, sign = false } = opts;
  if (value === null || value === undefined || value === "" || isNaN(Number(value))) return "—";
  const n = Number(value);
  const neg = n < 0;
  const fixed = Math.abs(n).toFixed(decimals);
  let [intPart, decPart] = fixed.split(".");
  intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, THIN);
  let out = decPart ? `${intPart}.${decPart}` : intPart;
  if (neg) out = "-" + out;
  else if (sign) out = "+" + out;
  return out;
}

export function formatPrice(value) {
  const n = Number(value);
  if (isNaN(n)) return "—";
  const decimals = Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 2 : 4;
  return formatNumber(n, { decimals });
}

export function formatPct(value, opts = {}) {
  const { decimals = 2, sign = true } = opts;
  if (value === null || value === undefined || isNaN(Number(value))) return "—";
  return formatNumber(Number(value), { decimals, sign }) + "%";
}

export function formatCurrency(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(Number(value))) return "—";
  return "$" + formatNumber(Number(value), { decimals });
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
