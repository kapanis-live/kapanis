import { useState } from "react";
import { cn } from "@/lib/utils";

// Tek logo bileşeni: BIST, ABD ve kripto listelerinin hepsinde bu kullanılır (tasarım sistemindeki Ticker de buna yönlenir).
// Logo kaynakları sırayla denenir:
//   1) kendi indirdiğin dosya: frontend/public/logos/<PİYASA>/<KOD>.png  (BIST, ABD, KRIPTO ayrı klasör: aynı kod iki piyasada olabilir)
//   2) eski konum: frontend/public/logos/<KOD>.png (yalnız BIST)
//   3) ücretsiz kaynak: kripto CoinCap, hisse Financial Modeling Prep
//   4) hiçbiri yoksa kodun baş harfleri
// PNG dosyası değiştirilmez: yuvarlaklık yalnız arayüzde (tam daire, taşan kırpılır, logo ortada, kenarda boşluk).
export function logoUrl(code, market) {
  const c = String(code || "").toUpperCase();
  if (market === "KRIPTO") return `https://assets.coincap.io/assets/icons/${c.toLowerCase()}@2x.png`;
  if (market === "BIST") return `https://financialmodelingprep.com/image-stock/${c}.IS.png`;
  if (market === "ABD") return `https://financialmodelingprep.com/image-stock/${c}.png`;
  return null;
}

export function logoSources(code, market) {
  const c = encodeURIComponent(String(code || "").toUpperCase());
  if (!c) return [];
  return [
    market && `/logos/${market}/${c}.png`,
    market === "BIST" && `/logos/${c}.png`,
    logoUrl(c, market),
  ].filter(Boolean);
}

// Görselin gerçek logo alanını piksellerden bulur (dosyadaki şeffaf ya da beyaz boşluk hariç).
// Sonuç: { fill: true, box } -> dolu, kareye yakın logo: bu alan daireyi tamamen doldurur (köşeler maskelenir)
//        { fill: false }      -> yatay/dikey ya da seyrek sembol: beyaz yuvarlak rozetin içine sığdırılır
const SHAPE = new Map();
const N = 96; // analiz çözünürlüğü

function analyse(img) {
  const w = img.naturalWidth, h = img.naturalHeight;
  if (!w || !h) return { fill: false };
  const c = document.createElement("canvas");
  c.width = N;
  c.height = N;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, N, N);
  const d = ctx.getImageData(0, 0, N, N).data; // farklı kaynaktan (CORS) gelirse hata atar -> çağıran yakalar
  const px = (x, y) => { const k = (y * N + x) * 4; return [d[k], d[k + 1], d[k + 2], d[k + 3]]; };
  const corners = [px(0, 0), px(N - 1, 0), px(0, N - 1), px(N - 1, N - 1)];
  const clear = corners.filter((p) => p[3] < 20).length >= 3;
  const white = !clear && corners.filter((p) => p[3] > 200 && p[0] >= 250 && p[1] >= 250 && p[2] >= 250).length >= 3;
  const empty = (p) => p[3] < 20 || (white && p[0] >= 247 && p[1] >= 247 && p[2] >= 247);
  let x0 = N, y0 = N, x1 = -1, y1 = -1;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    if (!empty(px(x, y))) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  }
  if (x1 < 0) return { fill: false };
  // görüntünün gerçek en-boy oranıyla alan (analiz kare tuvale sıkıştırıldı)
  const bw = ((x1 - x0 + 1) / N) * w, bh = ((y1 - y0 + 1) / N) * h;
  const ratio = bw / bh;
  let solid = 0, total = 0;
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) { total++; if (!empty(px(x, y))) solid++; }
  const cover = solid / total; // dolu karo ~1, zaten yuvarlak ikon ~0,78, ince sembol daha düşük
  if (ratio < 0.8 || ratio > 1.25 || cover < 0.7) return { fill: false };
  return { fill: true, box: { x: x0 / N, y: y0 / N, w: (x1 - x0 + 1) / N, h: (y1 - y0 + 1) / N } };
}

export function AssetLogo({ code, market, size = 40, className }) {
  const sources = logoSources(code, market);
  const [i, setI] = useState(0);
  const src = sources[i];
  const [shape, setShape] = useState(() => (src && SHAPE.get(src)) || null);
  const box = { width: `${size / 16}rem`, height: `${size / 16}rem` };
  const circle = "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full";
  if (i >= sources.length) {
    return (
      <span style={box} aria-hidden className={cn(circle, "border border-hairline bg-raised font-bold tracking-[0.02em] text-t-2",
        size >= 48 ? "text-sm" : "text-[0.8125rem]", className)}>
        {String(code || "?").slice(0, 2)}
      </span>
    );
  }
  const onLoad = (e) => {
    let s = SHAPE.get(src);
    if (!s) {
      const el = e.currentTarget;
      try {
        s = analyse(el);
      } catch {
        // piksel okunamadı (başka sitedeki logo): yalnız dosya oranına bak
        const r = el.naturalWidth / (el.naturalHeight || 1);
        s = r > 0.8 && r < 1.25 ? { fill: true, box: { x: 0, y: 0, w: 1, h: 1 } } : { fill: false };
      }
      SHAPE.set(src, s);
    }
    setShape(s);
  };
  const fill = shape?.fill;
  // Dolu logo: bulunan alan 40px daireyi tam kaplayacak şekilde büyütülüp kaydırılır, daire dışı maskelenir.
  const fillStyle = fill ? {
    position: "absolute", maxWidth: "none",
    width: `${100 / shape.box.w}%`, height: `${100 / shape.box.h}%`,
    left: `${(-shape.box.x / shape.box.w) * 100}%`, top: `${(-shape.box.y / shape.box.h) * 100}%`,
    objectFit: "fill",
  } : undefined;
  return (
    <span style={{ ...box, clipPath: "circle(50%)" }} aria-hidden className={cn(circle, fill ? "bg-transparent" : "bg-white", className)}>
      <img key={src} src={src} alt="" loading="lazy" onLoad={onLoad} onError={() => { setShape(null); setI((n) => n + 1); }}
        style={fillStyle} className={fill ? "" : "h-[78%] w-[78%] object-contain"} />
    </span>
  );
}

// Tasarım sistemi paketindeki TickerLogo bu bileşeni kullanır (aynı görünüm her yerde)
if (typeof window !== "undefined") window.KapanisLogo = AssetLogo;

// Grafik sayfasına bağlantı
export function chartHref(code, market) {
  return `/app/grafik?kod=${encodeURIComponent(String(code).replace(/\.(IS|US)$/i, "").split("/")[0])}&piyasa=${market || "KRIPTO"}`;
}
