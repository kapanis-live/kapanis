import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { createChart, createSeriesMarkers, CandlestickSeries, LineSeries, HistogramSeries, CrosshairMode } from "lightweight-charts";
import { K } from "@/ds";
import { sendAction } from "@/lib/actions";
import { useAuth } from "@/context/AuthContext";
import { Quota } from "@/pages/panel/Account";
import { useQueryClient } from "@tanstack/react-query";
import { splitAi, relDay } from "@/lib/dsmap";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { LoadingState, ErrorState } from "@/components/states";
import { AssetLogo } from "@/components/AssetLogo";
import { Segmented, Chip, SearchField, ChangeBadge, SignalCard } from "@/components/kp";
import { useTheme } from "@/lib/theme";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { formatNumber, formatCompact } from "@/lib/format";
import { px, baseCode, MARKET_LABEL } from "@/lib/portfolio";
import { cn } from "@/lib/utils";

const TFS = [["15m", "15 dk"], ["1h", "1 saat"], ["4h", "4 saat"], ["1d", "Günlük"], ["1w", "Haftalık"]];
// Dönem düğmeleri (TradingView gibi): gösterilecek zaman aralığı + o aralığa uygun mum
const DAY = 86400;
const RANGES = [["1G", "1 gün", DAY, "15m"], ["1H", "1 hafta", 7 * DAY, "1h"], ["1A", "1 ay", 30 * DAY, "4h"],
  ["3A", "3 ay", 91 * DAY, "1d"], ["6A", "6 ay", 182 * DAY, "1d"], ["YTD", "yıl başından beri", "ytd", "1d"],
  ["1Y", "1 yıl", 365 * DAY, "1d"], ["5Y", "5 yıl", 5 * 365 * DAY, "1w"]];
const rangeStart = (key, lastT) => {
  const r = RANGES.find(([k]) => k === key);
  if (!r) return null;
  if (r[2] === "ytd") return Date.UTC(new Date(lastT * 1000).getUTCFullYear(), 0, 1) / 1000;
  return lastT - r[2];
};
const MARKETS = ["KRIPTO", "BIST", "ABD"];
const LINES = [["sma5", "SMA 5"], ["sma10", "SMA 10"], ["sma20", "SMA 20"], ["sma50", "SMA 50"],
  ["sma100", "SMA 100"], ["sma200", "SMA 200"], ["ema5", "EMA 5"], ["ema9", "EMA 9"], ["ema10", "EMA 10"],
  ["ema20", "EMA 20"], ["ema21", "EMA 21"], ["ema50", "EMA 50"], ["ema100", "EMA 100"], ["ema200", "EMA 200"], ["vwap", "VWAP"]];
const INDICATORS = [
  { title: "Trend ve fiyat", items: [...LINES, ["bollinger", "Bollinger Bantları 20,2"]] },
  { title: "Momentum", items: [["rsi", "RSI 14"], ["macd", "MACD 12,26,9"], ["stoch", "Stokastik 14,3"],
    ["stoch_rsi", "Stokastik RSI 14"], ["cci", "CCI 20"], ["roc", "ROC 12"],
    ["williams_r", "Williams %R 14"], ["ultimate", "Ultimate Oscillator"]] },
  { title: "Hacim ve oynaklık", items: [["atr", "ATR 14"], ["adx", "ADX 14"], ["obv", "OBV"],
    ["mfi", "MFI 14"], ["bull_bear", "Bull / Bear Power"]] },
];
const INDICATOR_COLORS = { sma5: "#8cb7e0", sma10: "#8bd0b3", sma20: "#d99d56", sma50: "#4eabdb", sma100: "#c7a0df", sma200: "#b18be5",
  ema5: "#f0a971", ema9: "#ef7062", ema10: "#d189bf", ema20: "#8cad76", ema21: "#e7bf59", ema50: "#57bdab", ema100: "#8c9dec", ema200: "#cf85c3", vwap: "#c9a851",
  bollinger: "#8099d6", macd: "#6d9de7", stoch: "#d1a457", atr: "#8db9a2", cci: "#d38da0",
  roc: "#a5a0dd", obv: "#83bcda", mfi: "#b6a67b", williams_r: "#92b888", stoch_rsi: "#df8bce",
  ultimate: "#7cc2a5", adx: "#e8ad69", bull_bear: "#c29edd" };
const DEFAULT_ON = { sma20: true, sma50: true, sma200: true, rsi: true, seviye: true, bolge: true, sinyal: true };
const OVERLAYS = [["seviye", "Alış + plan"], ["bolge", "Destek / direnç"], ["sinyal", "Bot sinyalleri"]];

function precisionFor(p) {
  const a = Math.abs(p || 0);
  if (a >= 1) return 2;
  if (a >= 0.01) return 4;
  return a ? Math.min(10, Math.ceil(-Math.log10(a)) + 3) : 2;
}

const trTime = (t, withTime) =>
  new Date(t * 1000).toLocaleString("tr-TR", {
    timeZone: "Europe/Istanbul", day: "2-digit", month: "short",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : { year: "2-digit" }),
  });

// Fiyat %65 · hacim %17 · RSI %18; fareyle üzerine gelince açılış/yüksek/düşük/kapanış ve gösterge değerleri
function CandleChart({ data, on, overlay, onPick, range }) {
  const narrow = typeof window !== "undefined" && window.innerWidth < 640;
  const ref = useRef(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  const [hover, setHover] = useState(null);
  const { colors: c, theme } = useTheme();
  useEffect(() => {
    if (!ref.current || !data?.candles?.length) return undefined;
    const intraday = ["15m", "1h", "4h"].includes(data.tf);
    const prec = precisionFor(data.last?.price);
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: "solid", color: "transparent" }, textColor: c.axis, fontSize: narrow ? 11 : 13,
        fontFamily: '"SF Pro Display", -apple-system, Inter, "Segoe UI", sans-serif', panes: { separatorColor: c.sep } },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      rightPriceScale: { borderColor: c.sep },
      timeScale: { borderColor: c.sep, timeVisible: intraday, tickMarkFormatter: (t) => trTime(t, intraday) },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { locale: "tr-TR", timeFormatter: (t) => trTime(t, intraday), priceFormatter: (v) => formatNumber(v, { decimals: prec }) },
    });
    const fmt = { type: "price", precision: prec, minMove: 1 / 10 ** prec };
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down, borderVisible: false, priceFormat: fmt,
    });
    candles.setData(data.candles.map((k) => ({ time: k.t, open: k.o, high: k.h, low: k.l, close: k.c })));
    // Seviyeler: alış ortalaman, planın tetik / iptal / hedef çizgileri
    // telefonda çizgi adları grafiği kapatır: yalnız eksen etiketi (ve bölgelerde o da yok)
    const level = (price, color, title, style = 2, axis = true) =>
      price && candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: narrow ? axis && style !== 1 : axis, title: narrow ? "" : title });
    if (on.seviye && overlay) {
      level(overlay.entry, c.info, "Alış ort.", 0);
      level(overlay.plan?.tetik, c.wait, "Tetik");
      level(overlay.plan?.iptal, c.down, "İptal");
      level(overlay.plan?.hedef, c.up, "Hedef");
    }
    // Kullanıcının bu koddaki aktif alarmları
    (overlay?.alarms || []).forEach((a) => level(a.seviye, c.wait, `Alarm ${a.yon === "ustu" ? "▲" : "▼"}`, 3));
    if (on.bolge && data.zones) {
      data.zones.destek.forEach((z) => level(z.orta, `${c.up}b0`, `Destek (${z.dokunma})`, 1));
      data.zones.direnc.forEach((z) => level(z.orta, `${c.down}b0`, `Direnç (${z.dokunma})`, 1));
    }
    // Bot sinyalleri: sinyalin geldiği mumun üstünde/altında işaret
    if (on.sinyal && overlay?.signals?.length) {
      const times = data.candles.map((k) => k.t);
      const marks = overlay.signals.map((sg) => {
        let t = null;
        for (const x of times) { if (x <= sg.t) t = x; else break; }
        if (t == null) return null;
        const buy = sg.verdict === "AL";
        return { time: t, position: buy ? "belowBar" : "aboveBar", shape: buy ? "arrowUp" : "circle",
          color: buy ? c.up : sg.verdict === "PAS" ? c.axis : c.wait, text: sg.verdict };
      }).filter(Boolean).sort((a, b) => a.time - b.time);
      if (marks.length) createSeriesMarkers(candles, marks);
    }
    const line = (key, color, pane = 0, width = 2) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: width, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        ...(pane ? {} : { priceFormat: fmt }) }, pane);
      s.setData(data.candles.map((k, i) => (data[key]?.[i] == null ? { time: k.t } : { time: k.t, value: data[key][i] })));
      return s;
    };
    LINES.forEach(([k]) => on[k] && line(k, c[k] || INDICATOR_COLORS[k]));
    if (on.bollinger) {
      line("bb_upper", INDICATOR_COLORS.bollinger, 0, 1);
      line("bb_mid", INDICATOR_COLORS.bollinger, 0, 1);
      line("bb_lower", INDICATOR_COLORS.bollinger, 0, 1);
    }
    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "custom", minMove: 1, formatter: (v) => formatCompact(v) }, priceLineVisible: false, lastValueVisible: false }, 1);
    vol.setData(data.candles.map((k) => ({ time: k.t, value: k.v, color: `${k.c >= k.o ? c.up : c.down}80` })));
    const vma = chart.addSeries(LineSeries, { color: c.line, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      priceFormat: { type: "custom", minMove: 1, formatter: (v) => formatCompact(v) } }, 1);
    vma.setData(data.candles.map((k, i) => (data.vol_ma[i] == null ? { time: k.t } : { time: k.t, value: data.vol_ma[i] })));
    let pane = 2;
    if (on.rsi) {
      const rsi = line("rsi", c.rsi, pane);
      rsi.createPriceLine({ price: 70, color: c.down, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
      rsi.createPriceLine({ price: 30, color: c.up, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
      pane += 1;
    }
    if (on.macd) {
      line("macd", INDICATOR_COLORS.macd, pane);
      line("macd_signal", c.down, pane, 1);
      const hist = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      hist.setData(data.candles.map((k, i) => data.macd_hist?.[i] == null ? { time: k.t } :
        { time: k.t, value: data.macd_hist[i], color: data.macd_hist[i] >= 0 ? `${c.up}99` : `${c.down}99` }));
      pane += 1;
    }
    if (on.stoch) { line("stoch_k", INDICATOR_COLORS.stoch, pane); line("stoch_d", c.down, pane, 1); pane += 1; }
    ["atr", "adx", "cci", "roc", "williams_r", "stoch_rsi", "ultimate", "obv", "mfi"].forEach((key) => {
      if (on[key]) { line(key, INDICATOR_COLORS[key], pane); pane += 1; }
    });
    if (on.bull_bear) {
      line("bull_power", c.up, pane);
      line("bear_power", c.down, pane, 1);
      pane += 1;
    }
    chart.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 65 : i === 1 ? 17 : 18));
    const lastT = data.candles[data.candles.length - 1].t;
    const from = range ? rangeStart(range, lastT) : null;
    const firstIdx = from == null ? -1 : data.candles.findIndex((k) => k.t >= from);
    if (firstIdx >= 0) chart.timeScale().setVisibleLogicalRange({ from: firstIdx, to: data.candles.length + 1 });
    else chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, data.candles.length - 140), to: data.candles.length + 3 });

    const index = new Map(data.candles.map((k, i) => [k.t, i]));
    // Grafiğe tıklayınca o fiyat alarm seviyesi olarak seçilir
    chart.subscribeClick((param) => {
      if (!param?.point || !pickRef.current) return;
      const price = candles.coordinateToPrice(param.point.y);
      if (price != null && Number.isFinite(price) && price > 0) pickRef.current(price);
    });
    chart.subscribeCrosshairMove((param) => {
      const i = param?.time != null ? index.get(param.time) : undefined;
      setHover(i === undefined ? null : i);
    });
    return () => chart.remove();
  }, [data, on, c, theme, overlay, range, narrow]);

  const i = hover ?? data.candles.length - 1;
  const k = data.candles[i];
  const up = k.c >= k.o;
  return (
    <div className="relative w-full select-none">
      <div className={cn("pointer-events-none absolute left-1 top-1 z-10 flex flex-col gap-1 text-t-2", narrow ? "text-[0.6875rem]" : "text-sm")}>
        <div className="num flex flex-wrap gap-x-3.5 gap-y-1">
          <span className="text-t-3">{trTime(k.t, ["15m", "1h", "4h"].includes(data.tf))}</span>
          {[["A", k.o], ["Y", k.h], ["D", k.l], ["K", k.c]].map(([l, v]) => (
            <span key={l}><b className="font-semibold text-t-3">{l}</b> <span className={cn("font-semibold", up ? "text-up" : "text-down")}>{px(v)}</span></span>
          ))}
          {!narrow && <span><b className="font-semibold text-t-3">Hacim</b> {formatCompact(k.v)}</span>}
        </div>
        {!narrow && <div className="num flex flex-wrap gap-x-3.5 gap-y-1">
          {LINES.filter(([key]) => on[key]).map(([key, label]) => (
            <span key={key} className="inline-flex items-center gap-1.5">
              <i className="h-0.5 w-3.5" style={{ background: c[key] || INDICATOR_COLORS[key] }} />
              {label} <b className="font-semibold text-t-1">{data[key]?.[i] == null ? "—" : px(data[key][i])}</b>
            </span>
          ))}
          {on.rsi && <span><span className="text-t-3">RSI</span> <b className="font-semibold text-rsi">{data.rsi[i] == null ? "—" : Math.round(data.rsi[i])}</b></span>}
        </div>}
      </div>
      <div ref={ref} style={{ height: (narrow ? 360 : 440) + (narrow ? 110 : 150) * (Number(!!on.rsi) + Number(!!on.macd) + Number(!!on.stoch) + Number(!!on.bull_bear) +
        ["atr", "adx", "cci", "roc", "williams_r", "stoch_rsi", "ultimate", "obv", "mfi"].filter((key) => on[key]).length) }} className="w-full" data-testid="tv-chart" />
    </div>
  );
}

const ALARM_TFS = { KRIPTO: ["1h", "4h", "1d"], BIST: ["1d"], ABD: ["1d"] };
const ALARM_TF_LABEL = { "1h": "1 saatlik", "4h": "4 saatlik", "1d": "Günlük" };

// Grafikten alarm: tıkla ya da bölge seç, seviye gelsin; yön şimdiki fiyata göre kendiliğinden
function AlarmBar({ d, code, market, chartTf, picked, setPicked, alarms }) {
  const qc = useQueryClient();
  const tfs = ALARM_TFS[market] || ["1d"];
  const [tf, setTf] = useState(tfs.includes(chartTf) ? chartTf : "1d");
  const [busy, setBusy] = useState(false);
  useEffect(() => setTf(tfs.includes(chartTf) ? chartTf : "1d"), [chartTf, market]); // eslint-disable-line react-hooks/exhaustive-deps
  const price = d.last?.price;
  const level = picked ?? "";
  const n = typeof level === "number" ? level : Number(String(level).replace(/\./g, "").replace(",", "."));
  const yon = Number.isFinite(n) && price ? (n >= price ? "ustu" : "alti") : "ustu";
  const zones = [...(d.zones?.direnc || []).slice(0, 2).map((z) => ["Direnç", z.orta]), ...(d.zones?.destek || []).slice(0, 2).map((z) => ["Destek", z.orta])];
  const save = async () => {
    if (!Number.isFinite(n) || n <= 0) return toast.error("Grafiğe tıkla ya da seviye yaz.");
    setBusy(true);
    try {
      await api.post("/alarms", { piyasa: market, kod: code, tur: "fiyat", yon, seviye: Number(n.toPrecision(8)), tf });
      qc.invalidateQueries({ queryKey: ["my-alarms"] });
      toast.success(`${code} ${px(n)} ${yon === "ustu" ? "üstünde" : "altında"} ${ALARM_TF_LABEL[tf].toLowerCase()} kapanışta haber vereceğim.`);
      setPicked(null);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  };
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-hairline bg-raised p-4" data-testid="chart-alarm">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1.5 text-sm font-medium text-t-2">⏰ Alarm seviyesi
          <input inputMode="decimal" value={typeof level === "number" ? px(level) : level} placeholder="Grafiğe tıkla"
            onChange={(e) => setPicked(e.target.value)}
            className="num h-10 w-40 rounded-lg border border-strong bg-ink px-3 font-bold text-t-1 outline-none focus:border-info" />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium text-t-2">Mum
          <select value={tf} onChange={(e) => setTf(e.target.value)} className="h-10 rounded-lg border border-strong bg-ink px-3 text-t-1">
            {tfs.map((t) => <option key={t} value={t}>{ALARM_TF_LABEL[t]}</option>)}
          </select>
        </label>
        <K.Button variant="primary" disabled={busy} onClick={save}>
          {Number.isFinite(n) && n > 0 ? `${yon === "ustu" ? "Üstünde" : "Altında"} kapanırsa haber ver` : "Alarm kur"}
        </K.Button>
      </div>
      {zones.length > 0 && <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-t-3">Hızlı seç:</span>
        {zones.map(([label, v]) => <button key={label + v} type="button" onClick={() => setPicked(v)}
          className="rounded-lg border border-hairline px-2.5 py-1 font-semibold text-t-2 hover:bg-surface">{label} {px(v)}</button>)}
      </div>}
      <p className="m-0 text-xs text-t-3">Grafikte bir fiyata tıkla, seviye buraya gelir. Yalnız mum kapanışı sayılır; bir kez çalışır ve
        bağlı Telegram'ına gelir. {alarms.length ? `Bu kodda ${alarms.length} aktif alarmın var (grafikte sarı çizgi).` : ""} Tümü: Alarmlarım.</p>
    </div>
  );
}

// Göstergelerin herkesin anlayacağı dille özeti (hepsi kodla hesaplandı)
function readings(d) {
  const L = d.last || {};
  const p = L.price;
  const out = [];
  const above = (x) => x != null && p > x;
  if (L.sma50 != null && L.sma200 != null) {
    const strong = p > L.sma50 && L.sma50 > L.sma200;
    const weak = p < L.sma50 && L.sma50 < L.sma200;
    out.push({ title: "Trend", tone: strong ? "up" : weak ? "down" : "flat",
      verdict: strong ? "Yükseliş eğilimi" : weak ? "Düşüş eğilimi" : "Net yön yok",
      detail: `Fiyat SMA 50'nin ${above(L.sma50) ? "üstünde" : "altında"}, SMA 200'ün ${above(L.sma200) ? "üstünde" : "altında"}.` });
  } else if (L.sma20 != null) {
    out.push({ title: "Trend", tone: above(L.sma20) ? "up" : "down", verdict: above(L.sma20) ? "Kısa vadede yukarı" : "Kısa vadede aşağı",
      detail: "Uzun ortalamalar için yeterli mum yok." });
  }
  if (L.rsi != null) {
    const r = Math.round(L.rsi);
    out.push({ title: "RSI", tone: r >= 70 ? "warn" : r <= 30 ? "info" : "flat",
      verdict: r >= 70 ? `Isınmış · ${r}` : r <= 30 ? `Çok satılmış · ${r}` : `Normal · ${r}`,
      detail: r >= 70 ? "Hızlı yükselmiş; kovalamak riskli, geri çekilme olabilir." : r <= 30 ? "Düşüş yorulmuş olabilir; dönüş için teyit bekle." : "30 ile 70 arasında, aşırılık yok." });
  }
  if (L.vol_ma) {
    const x = L.volume / L.vol_ma;
    out.push({ title: "Hacim", tone: x >= 1.2 ? "info" : "flat", verdict: `Ortalamanın ${formatNumber(x, { decimals: 1 })} katı`,
      detail: x >= 1.2 ? "Katılım yüksek; hareket daha güvenilir." : x < 0.6 ? "Ortalamanın çok altında (son mum henüz bitmemiş olabilir)." : "Olağan katılım." });
  }
  if (L.vwap != null) {
    out.push({ title: "VWAP", tone: above(L.vwap) ? "up" : "down", verdict: above(L.vwap) ? "VWAP üstünde" : "VWAP altında",
      detail: `${above(L.vwap) ? "Ortalama alıcı kârda; fiyat güçlü." : "Ortalama alıcı zararda; fiyat zayıf."} (${d.vwap_note})` });
  }
  return out;
}

// Panelden yapay zekâ analizi: bot analiz eder, cevap Telegram'a ve buraya gelir
export function AiPanel({ code, market, codes, auto = false }) {
  const list = codes && codes.length ? codes : [code];
  const q = useData(["analyses", list[0]], `/analyses?kod=${encodeURIComponent(list[0])}`, LIVE);
  const [asked, setAsked] = useState(null);
  const { owner } = useAuth();
  const qc = useQueryClient();
  // Sahip olmayan kullanıcı: günlük hak (kendi anahtarıyla daha fazla)
  const quota = useData("quota", "/quota", { enabled: !owner, refetchInterval: 30_000 });
  const qd = quota.data;
  const limit = qd && !qd.sahip ? (qd.kendi_anahtari ? qd.anahtarla_sinir : qd.sinir) : null;
  const exhausted = limit !== null && (qd.kullanilan >= limit || limit <= 0 || qd.ortak_dolu);
  const latest = (q.data || [])[0];
  const waiting = asked && (!latest || new Date(latest.zaman).getTime() < asked);
  const ask = async () => {
    if (await sendAction("analysis.request", { kodlar: list, piyasa: market }, `${list.join(", ")} için analiz istendi.`)) setAsked(Date.now());
    qc.invalidateQueries({ queryKey: ["quota"] });
  };
  const started = useRef(false);
  useEffect(() => {
    // Takip listesinden "Yapay zekâ analizi" ile açılınca isteği hemen gönder (bir kez)
    if (auto && !started.current) { started.current = true; ask(); }
  }, [auto]); // eslint-disable-line react-hooks/exhaustive-deps
  const ai = latest ? splitAi(latest.metin) : null;
  return (
    <K.Card title="Yapay zekâ analizi" actions={<K.Button variant="primary" onClick={ask} disabled={!!waiting || exhausted}>{waiting ? "Hazırlanıyor…" : "Analiz et"}</K.Button>}>
      {!owner && qd && <div style={{ marginBottom: "1rem" }}><Quota q={qd} /></div>}
      {!owner && exhausted && (
        <K.EmptyState tone="warn" icon="info" title={qd.ortak_dolu ? "Bugünkü ortak analiz kapasitesi doldu" : "Bugünkü analiz hakkın doldu"}
          action={!qd.kendi_anahtari ? <K.Button variant="secondary" icon={<K.Icon name="key" size={18} />} href="/app/hesap">Kendi anahtarını ekle</K.Button> : null}>
          {qd.kendi_anahtari ? "Hakkın son 24 saate göre yenilenir." : `Kendi yapay zekâ anahtarınla günde ${qd.anahtarla_sinir} analiz yapabilirsin.`}
        </K.EmptyState>
      )}
      {waiting && <p className="kp-note">Bot analizi hazırlıyor (genelde 20–60 sn). {owner ? "Sonuç Telegram'a da gelir." : "Telegram'ı bağladıysan sonuç oraya da gelir."}</p>}
      {ai ? (
        <K.AiNote model={ai.model || "Yapay zekâ"} time={relDay(latest.zaman)} title={latest.kodlar?.length > 1 ? `Karşılaştırma: ${latest.kodlar.join(", ")}` : "Son analiz"}>
          {ai.body.split(/\n{2,}/).map((t, i) => <p key={i} style={{ whiteSpace: "pre-wrap" }}>{t}</p>)}
        </K.AiNote>
      ) : !waiting && <p className="kp-note">Bu kod için panelden istenmiş analiz yok. “Analiz et”e bas; kararı yine kod kapısı verir.</p>}
    </K.Card>
  );
}

export default function ChartPage() {
  const [params, setParams] = useSearchParams();
  const code = (params.get("kod") || "BTC").toUpperCase();
  const market = MARKETS.includes(params.get("piyasa")) ? params.get("piyasa") : "KRIPTO";
  const tf = TFS.some(([k]) => k === params.get("tf")) ? params.get("tf") : "1d";
  const range = RANGES.some(([k]) => k === params.get("donem")) ? params.get("donem") : null;
  const [draft, setDraft] = useState(code);
  const [on, setOn] = useState(() => {
    try { return { ...DEFAULT_ON, ...JSON.parse(localStorage.getItem("kapanis.chart.indicators") || "{}") }; }
    catch { return DEFAULT_ON; }
  });
  const [showIndicators, setShowIndicators] = useState(false);
  const [indicatorSearch, setIndicatorSearch] = useState("");
  useEffect(() => localStorage.setItem("kapanis.chart.indicators", JSON.stringify(on)), [on]);
  const { colors: c } = useTheme();
  useEffect(() => setDraft(code), [code]);

  const q = useData(["chart", code, market, tf], `/chart/${encodeURIComponent(code)}?tf=${tf}&market=${market}`,
    { retry: false, refetchInterval: 60_000, placeholderData: (prev) => prev });
  const { owner } = useAuth();
  // botun portföy/plan/sinyal verisi yalnız sistem sahibinde: diğer kullanıcılar sadece grafiği ve kendi analizini görür
  const extras = useData("extras", "/extras", { ...LIVE, enabled: owner });
  const set = (patch) => setParams((p) => {
    const n = new URLSearchParams(p);
    Object.entries(patch).forEach(([k, v]) => n.set(k, v));
    return n;
  });
  const quick = useMemo(() => {
    const held = (extras.data?.portfoy || []).map((g) => ({ code: baseCode(g.ad), market: g.piyasa }));
    const list = extras.data?.takip_listesi?.piyasalar || {};
    const watch = Object.entries(list).flatMap(([m, rs]) => rs.map((r) => ({ code: r.kod, market: m })));
    return { held, watch };
  }, [extras.data]);
  const submit = (v) => {
    const c2 = String(v || "").trim().toUpperCase().replace(/\/USDT$/, "").replace(/\.(IS|US)$/, "");
    if (c2) set({ kod: c2 });
  };
  const d = q.data;
  const sigQ = useData("signals", "/signals", { enabled: owner });
  const alarmQ = useData("my-alarms", "/alarms", LIVE);
  const [picked, setPicked] = useState(null);
  useEffect(() => setPicked(null), [code, market]);
  const myAlarms = useMemo(() => (alarmQ.data?.alarmlar || []).filter((a) => a.durum === "aktif" && a.kod === code && a.piyasa === market),
    [alarmQ.data, code, market]);
  const overlay = useMemo(() => {
    const ex = extras.data || {};
    const g = (ex.portfoy || []).find((x) => baseCode(x.ad) === code && x.piyasa === market);
    const plan = (ex.planlar || []).find((x) => x.kod === code && x.piyasa === market && x.plan);
    const signals = (sigQ.data || []).filter((s) => baseCode(s.symbol) === code && (s.market || "KRIPTO") === market)
      .map((s) => {
        const v = String(s.analysis?.bot_decision?.verdict || "").toUpperCase();
        return { t: Math.floor(new Date(s.created_at).getTime() / 1000), verdict: v.includes("AL") ? "AL" : v.includes("BEKLE") ? "BEKLE" : v.includes("TUT") ? "TUT" : "PAS" };
      });
    return { entry: g && g.adet ? g.maliyet / g.adet : null, plan, signals, alarms: myAlarms };
  }, [extras.data, sigQ.data, code, market, myAlarms]);

  return (
    <div>
      <PageHeader title="Grafik" testid="page-chart"
        subtitle="Kripto, BIST ya da ABD: istediğin kodu, istediğin zaman diliminde incele." />

      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented ariaLabel="Piyasa" value={market} onChange={(m) => set({ piyasa: m })}
            options={MARKETS.map((m) => ({ value: m, label: MARKET_LABEL[m] }))} />
          <SearchField value={draft} onChange={setDraft} onSubmit={submit} placeholder="Kod yaz: BTC, THYAO, NVDA" list="chart-codes" />
          <datalist id="chart-codes">{quick.watch.filter((w) => w.market === market).map((w) => <option key={w.code} value={w.code} />)}</datalist>

        </div>

        {quick.held.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-1 text-[0.9375rem] font-medium text-t-3">Portföyüm</span>
            {quick.held.map((h) => (
              <button key={h.market + h.code} onClick={() => set({ kod: h.code, piyasa: h.market })}
                className={cn("inline-flex h-9 items-center gap-2 rounded-lg border px-2.5 text-[0.9375rem] font-semibold transition-colors duration-150",
                  code === h.code && market === h.market ? "border-strong bg-raised text-t-1" : "border-hairline text-t-2 hover:bg-raised hover:text-t-1")}>
                <AssetLogo code={h.code} market={h.market} size={22} /> {h.code}
              </button>
            ))}
          </div>
        )}

        {q.isLoading ? <LoadingState text="Grafik hazırlanıyor..." /> : q.isError ? (
          <ErrorState text={formatApiErrorDetail(q.error?.response?.data?.detail) || "Grafik alınamadı."} onRetry={() => q.refetch()} />
        ) : d && (
          <>
            <section className="flex flex-col gap-5 rounded-xl border border-hairline bg-surface p-6">
              <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
                <div className="flex items-center gap-3">
                  <AssetLogo code={d.symbol} market={d.market} size={48} />
                  <span className="flex flex-col leading-tight">
                    <span className="text-[1.375rem] font-bold tracking-[0.01em] text-t-1">{d.symbol}</span>
                    <span className="text-[0.9375rem] text-t-3">{MARKET_LABEL[d.market]} · {TFS.find(([k]) => k === d.tf)?.[1]}</span>
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="num text-[2.25rem] font-bold leading-[1.1] tracking-[-0.01em] text-t-1">
                    {d.currency === "TRY" ? "₺" : "$"}{px(d.last.price)}
                  </span>
                  <ChangeBadge value={d.last.change_pct} size="lg" />
                </div>
              </div>
              <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 sm:flex-wrap sm:overflow-visible [&>*]:shrink-0 [&>*]:whitespace-nowrap">
                <button type="button" className="rounded-lg border border-hairline px-3 py-2 text-sm font-semibold text-t-1 hover:bg-raised"
                  aria-expanded={showIndicators} onClick={() => setShowIndicators((v) => !v)}>＋ İndikatör ekle</button>
                {INDICATORS.flatMap((group) => group.items).filter(([key]) => on[key]).map(([key, label]) => (
                  <Chip key={key} color={c[key] || INDICATOR_COLORS[key]} active onClick={() => setOn((o) => ({ ...o, [key]: false }))}>{label} ×</Chip>
                ))}
                <span className="mx-1 w-px self-stretch bg-hairline" />
                {OVERLAYS.map(([k, label]) => (
                  <Chip key={k} active={on[k]} onClick={() => setOn((o) => ({ ...o, [k]: !o[k] }))}>{label}</Chip>
                ))}
              </div>
              {showIndicators && <div className="rounded-xl border border-hairline bg-raised p-4">
                <input aria-label="İndikatör ara" value={indicatorSearch} onChange={(e) => setIndicatorSearch(e.target.value)}
                  placeholder="İndikatör ara: EMA, MACD, ATR..." className="mb-3 w-full rounded-lg border border-hairline bg-surface px-3 py-2 text-t-1" />
                {INDICATORS.map((group) => {
                  const items = group.items.filter(([, label]) => label.toLocaleLowerCase("tr-TR").includes(indicatorSearch.toLocaleLowerCase("tr-TR")));
                  return items.length ? <div key={group.title} className="mb-3">
                    <p className="mb-2 text-sm font-semibold text-t-2">{group.title}</p>
                    <div className="flex flex-wrap gap-2">{items.map(([key, label]) =>
                      <button key={key} type="button" aria-pressed={!!on[key]} onClick={() => setOn((o) => ({ ...o, [key]: !o[key] }))}
                        className={cn("rounded-lg border px-3 py-2 text-sm", on[key] ? "border-strong bg-surface font-semibold text-t-1" : "border-hairline text-t-2 hover:bg-surface")}>
                        {on[key] ? "✓ " : "+ "}{label}
                      </button>)}</div>
                  </div> : null;
                })}
                <p className="m-0 text-xs text-t-3">Seçimlerin bu tarayıcıda saklanır. Göstergeler yalnız grafiği değiştirir; botun karar kurallarını değiştirmez.</p>
              </div>}
              <div className="flex items-center gap-1 overflow-x-auto rounded-xl border border-hairline bg-raised p-1 sm:flex-wrap [&>*]:shrink-0" data-testid="chart-ranges">
                {RANGES.map(([k, title, , rtf]) => (
                  <button key={k} type="button" title={title} onClick={() => set({ donem: k, tf: rtf })}
                    className={cn("h-8 min-w-[2.1rem] rounded-lg px-1.5 text-sm font-semibold transition-colors sm:min-w-[2.5rem] sm:px-2",
                      range === k ? "bg-surface text-t-1 shadow" : "text-t-3 hover:text-t-1")}>{k}</button>
                ))}
                <span className="mx-1 h-5 w-px bg-hairline" />
                <label className="ml-auto flex items-center gap-2 pr-1 text-sm text-t-3">Aralık
                  <select value={tf} onChange={(e) => set({ tf: e.target.value, donem: "" })} aria-label="Mum aralığı"
                    className="h-8 rounded-lg border-0 bg-transparent font-semibold text-t-1 outline-none">
                    {TFS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </label>
              </div>
              <CandleChart data={d} on={on} overlay={overlay} onPick={(v) => setPicked(v)} range={range} />
              <AlarmBar d={d} code={code} market={market} chartTf={tf} picked={picked} setPicked={setPicked} alarms={myAlarms} />
              <p className="m-0 text-sm text-t-3">
                Saatler İstanbul saati. {d.note} VWAP: {d.vwap_note}. Hacim altta gösterilir; seçtiğin diğer göstergeler ayrı bölmelerde açılır.
              </p>
            </section>
            <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(14rem, 1fr))" }}>
              {readings(d).map((r) => <SignalCard key={r.title} {...r} />)}
            </div>
            <AiPanel code={code} market={market} />
          </>
        )}
      </div>
    </div>
  );
}
