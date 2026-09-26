import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { createChart, createSeriesMarkers, CandlestickSeries, LineSeries, HistogramSeries, CrosshairMode } from "lightweight-charts";
import { K } from "@/ds";
import { sendAction } from "@/lib/actions";
import { splitAi, relDay } from "@/lib/dsmap";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { LoadingState, ErrorState } from "@/components/states";
import { AssetLogo } from "@/components/AssetLogo";
import { Segmented, Chip, SearchField, ChangeBadge, SignalCard } from "@/components/kp";
import { useTheme } from "@/lib/theme";
import { formatApiErrorDetail } from "@/lib/api";
import { formatNumber, formatCompact } from "@/lib/format";
import { px, baseCode, MARKET_LABEL } from "@/lib/portfolio";
import { cn } from "@/lib/utils";

const TFS = [["15m", "15 dk"], ["1h", "1 saat"], ["4h", "4 saat"], ["1d", "Günlük"], ["1w", "Haftalık"]];
const MARKETS = ["KRIPTO", "BIST", "ABD"];
const LINES = [["sma20", "SMA 20"], ["sma50", "SMA 50"], ["sma200", "SMA 200"], ["vwap", "VWAP"]];
const DEFAULT_ON = { sma20: true, sma50: true, sma200: true, vwap: false, seviye: true, bolge: true, sinyal: true };
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
function CandleChart({ data, on, overlay }) {
  const ref = useRef(null);
  const [hover, setHover] = useState(null);
  const { colors: c, theme } = useTheme();
  useEffect(() => {
    if (!ref.current || !data?.candles?.length) return undefined;
    const intraday = ["15m", "1h", "4h"].includes(data.tf);
    const prec = precisionFor(data.last?.price);
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: "solid", color: "transparent" }, textColor: c.axis, fontSize: 13,
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
    const level = (price, color, title, style = 2) =>
      price && candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
    if (on.seviye && overlay) {
      level(overlay.entry, c.info, "Alış ort.", 0);
      level(overlay.plan?.tetik, c.wait, "Tetik");
      level(overlay.plan?.iptal, c.down, "İptal");
      level(overlay.plan?.hedef, c.up, "Hedef");
    }
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
      s.setData(data.candles.map((k, i) => (data[key][i] == null ? { time: k.t } : { time: k.t, value: data[key][i] })));
      return s;
    };
    LINES.forEach(([k]) => on[k] && line(k, c[k]));
    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "custom", minMove: 1, formatter: (v) => formatCompact(v) }, priceLineVisible: false, lastValueVisible: false }, 1);
    vol.setData(data.candles.map((k) => ({ time: k.t, value: k.v, color: `${k.c >= k.o ? c.up : c.down}80` })));
    const vma = chart.addSeries(LineSeries, { color: c.line, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      priceFormat: { type: "custom", minMove: 1, formatter: (v) => formatCompact(v) } }, 1);
    vma.setData(data.candles.map((k, i) => (data.vol_ma[i] == null ? { time: k.t } : { time: k.t, value: data.vol_ma[i] })));
    const rsi = chart.addSeries(LineSeries, { color: c.rsi, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false,
      priceFormat: { type: "custom", minMove: 1, formatter: (v) => String(Math.round(v)) } }, 2);
    rsi.setData(data.candles.map((k, i) => (data.rsi[i] == null ? { time: k.t } : { time: k.t, value: data.rsi[i] })));
    rsi.createPriceLine({ price: 70, color: c.down, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
    rsi.createPriceLine({ price: 30, color: c.up, lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
    chart.panes().forEach((p, i) => p.setStretchFactor([65, 17, 18][i] || 17));
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, data.candles.length - 140), to: data.candles.length + 3 });

    const index = new Map(data.candles.map((k, i) => [k.t, i]));
    chart.subscribeCrosshairMove((param) => {
      const i = param?.time != null ? index.get(param.time) : undefined;
      setHover(i === undefined ? null : i);
    });
    return () => chart.remove();
  }, [data, on, c, theme, overlay]);

  const i = hover ?? data.candles.length - 1;
  const k = data.candles[i];
  const up = k.c >= k.o;
  return (
    <div className="relative w-full select-none">
      <div className="pointer-events-none absolute left-1 top-1 z-10 flex flex-col gap-1 text-sm text-t-2">
        <div className="num flex flex-wrap gap-x-3.5 gap-y-1">
          <span className="text-t-3">{trTime(k.t, ["15m", "1h", "4h"].includes(data.tf))}</span>
          {[["A", k.o], ["Y", k.h], ["D", k.l], ["K", k.c]].map(([l, v]) => (
            <span key={l}><b className="font-semibold text-t-3">{l}</b> <span className={cn("font-semibold", up ? "text-up" : "text-down")}>{px(v)}</span></span>
          ))}
          <span><b className="font-semibold text-t-3">Hacim</b> {formatCompact(k.v)}</span>
        </div>
        <div className="num flex flex-wrap gap-x-3.5 gap-y-1">
          {LINES.filter(([key]) => on[key]).map(([key, label]) => (
            <span key={key} className="inline-flex items-center gap-1.5">
              <i className="h-0.5 w-3.5" style={{ background: c[key] }} />
              {label} <b className="font-semibold text-t-1">{data[key][i] == null ? "—" : px(data[key][i])}</b>
            </span>
          ))}
          <span><span className="text-t-3">RSI</span> <b className="font-semibold text-rsi">{data.rsi[i] == null ? "—" : Math.round(data.rsi[i])}</b></span>
        </div>
      </div>
      <div ref={ref} style={{ height: 620 }} className="w-full" data-testid="tv-chart" />
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
  const latest = (q.data || [])[0];
  const waiting = asked && (!latest || new Date(latest.zaman).getTime() < asked);
  const ask = async () => {
    if (await sendAction("analysis.request", { kodlar: list, piyasa: market }, `${list.join(", ")} için analiz istendi.`)) setAsked(Date.now());
  };
  const started = useRef(false);
  useEffect(() => {
    // Takip listesinden "Yapay zekâ analizi" ile açılınca isteği hemen gönder (bir kez)
    if (auto && !started.current) { started.current = true; ask(); }
  }, [auto]); // eslint-disable-line react-hooks/exhaustive-deps
  const ai = latest ? splitAi(latest.metin) : null;
  return (
    <K.Card title="Yapay zekâ analizi" actions={<K.Button variant="primary" onClick={ask} disabled={!!waiting}>{waiting ? "Hazırlanıyor…" : "Analiz et"}</K.Button>}>
      {waiting && <p className="kp-note">Bot analizi hazırlıyor (genelde 20–60 sn). Sonuç Telegram'a da gelir.</p>}
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
  const [draft, setDraft] = useState(code);
  const [on, setOn] = useState(DEFAULT_ON);
  const { colors: c } = useTheme();
  useEffect(() => setDraft(code), [code]);

  const q = useData(["chart", code, market, tf], `/chart/${encodeURIComponent(code)}?tf=${tf}&market=${market}`,
    { retry: false, refetchInterval: 60_000, placeholderData: (prev) => prev });
  const extras = useData("extras", "/extras", LIVE);
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
  const sigQ = useData("signals", "/signals");
  const overlay = useMemo(() => {
    const ex = extras.data || {};
    const g = (ex.portfoy || []).find((x) => baseCode(x.ad) === code && x.piyasa === market);
    const plan = (ex.planlar || []).find((x) => x.kod === code && x.piyasa === market && x.plan);
    const signals = (sigQ.data || []).filter((s) => baseCode(s.symbol) === code && (s.market || "KRIPTO") === market)
      .map((s) => {
        const v = String(s.analysis?.bot_decision?.verdict || "").toUpperCase();
        return { t: Math.floor(new Date(s.created_at).getTime() / 1000), verdict: v.includes("AL") ? "AL" : v.includes("BEKLE") ? "BEKLE" : v.includes("TUT") ? "TUT" : "PAS" };
      });
    return { entry: g && g.adet ? g.maliyet / g.adet : null, plan, signals };
  }, [extras.data, sigQ.data, code, market]);

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
          <Segmented ariaLabel="Zaman dilimi" value={tf} onChange={(v) => set({ tf: v })} options={TFS.map(([v, label]) => ({ value: v, label }))} />
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
              <div className="flex flex-wrap gap-2">
                {LINES.map(([k, label]) => (
                  <Chip key={k} color={c[k]} active={on[k]} onClick={() => setOn((o) => ({ ...o, [k]: !o[k] }))}>{label}</Chip>
                ))}
                <span className="mx-1 w-px self-stretch bg-hairline" />
                {OVERLAYS.map(([k, label]) => (
                  <Chip key={k} active={on[k]} onClick={() => setOn((o) => ({ ...o, [k]: !o[k] }))}>{label}</Chip>
                ))}
              </div>
              <CandleChart data={d} on={on} overlay={overlay} />
              <p className="m-0 text-sm text-t-3">
                Saatler İstanbul saati. {d.note} VWAP: {d.vwap_note}. Alt bölmeler: hacim (20'lik ortalama ince çizgi) ve RSI 14 (70 kırmızı, 30 yeşil kesikli çizgi).
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
