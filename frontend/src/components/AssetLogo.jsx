import { useState } from "react";
import { cn } from "@/lib/utils";

// Ücretsiz logo kaynakları: kripto CoinCap, hisse (ABD ve BIST .IS) Financial Modeling Prep.
// Logo yoksa kodun baş harfleri gösterilir.
function logoUrl(code, market) {
  const c = String(code || "").toUpperCase();
  if (market === "KRIPTO") return `https://assets.coincap.io/assets/icons/${c.toLowerCase()}@2x.png`;
  if (market === "BIST") return `https://financialmodelingprep.com/image-stock/${c}.IS.png`;
  if (market === "ABD") return `https://financialmodelingprep.com/image-stock/${c}.png`;
  return null;
}

export function AssetLogo({ code, market, size = 40, className }) {
  const [failed, setFailed] = useState(false);
  const url = logoUrl(code, market);
  const box = { width: `${size / 16}rem`, height: `${size / 16}rem`, borderRadius: size >= 48 ? 10 : 9 };
  if (!url || failed) {
    return (
      <span style={box} className={cn("inline-grid shrink-0 place-items-center border border-hairline bg-raised font-bold tracking-[0.02em] text-t-2",
        size >= 48 ? "text-sm" : "text-[0.8125rem]", className)}>
        {String(code || "?").slice(0, 2)}
      </span>
    );
  }
  return (
    <span style={box} className={cn("inline-grid shrink-0 place-items-center overflow-hidden border border-hairline bg-white", className)}>
      <img src={url} alt="" loading="lazy" onError={() => setFailed(true)} className="h-[78%] w-[78%] object-contain" />
    </span>
  );
}

// Grafik sayfasına bağlantı
export function chartHref(code, market) {
  return `/app/grafik?kod=${encodeURIComponent(String(code).replace(/\.(IS|US)$/i, "").split("/")[0])}&piyasa=${market || "KRIPTO"}`;
}
