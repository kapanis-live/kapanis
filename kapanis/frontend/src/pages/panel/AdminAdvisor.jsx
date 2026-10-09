import { useState } from "react";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { useData } from "@/lib/useData";
import api, { formatApiErrorDetail } from "@/lib/api";
import { relDay } from "@/lib/dsmap";
import { useLang, translate, currentLang } from "@/lib/i18n";

// Sayfanın sabit metinleri seçili dilde (lib/i18n.jsx). Sunucunun yazdığı metinler (status_tr, notlar, gerekçeler) geldiği gibi kalır.
const tx = (s, v) => translate(currentLang(), s, v);

// Kripto Danışman V2 (yalnız yönetici). Fiyatları kural motoru hesaplar; üç bağımsız AI analizi (Teknik / Risk / Rejim
// rolleri; aynı model olabilir) yalnız yorumlar ve konsensüs (düz kurallar) planın verilip verilmeyeceğine karar verir.
// Bu sayfa hiçbir yere emir göndermez.
const RUN_TIMEOUT_MS = 180000; // sunucudaki sert sınırların (makro 40 sn + analistler 100 sn + mumlar) üstünde
const TABS = ["Özet", "Analiz", "AL planı", "SAT / Koruma", "Tarayıcı", "Portföy", "Makro", "Paper", "Konsensüs kaydı"];
const NUM = new Intl.NumberFormat("tr-TR", { maximumSignificantDigits: 7 });
const n = (v) => (v == null || Number.isNaN(Number(v)) ? "—" : NUM.format(v));
const pct = (v, d = 2) => (v == null ? "—" : `%${U.fmtNum(v, d)}`);
const zone = (z) => (!z ? "—" : Array.isArray(z) ? `${n(z[0])} – ${n(z[1])}` : `${n(z.low)} – ${n(z.high)}`);
const ARROW = { STRONG_UP: "↑↑ güçlü yükseliş", UP: "↑ yükseliş", RANGE: "→ yatay", DOWN: "↓ düşüş", STRONG_DOWN: "↓↓ güçlü düşüş", INSUFFICIENT_HISTORY: "veri yetersiz" };
const UP = "kp-num-up", DOWN = "kp-num-down", WAIT = "text-wait", FLAT = "text-t-2";
const TONE = {
  BUY: UP, APPROVE: UP, ALLOW: UP, HOLD: UP, BUY_SETUP: UP, OK: UP, RISK_ON: UP,
  WAIT: FLAT, WAIT_FOR_BREAKOUT: FLAT, WAIT_FOR_RETEST: FLAT, RECLAIM_WATCH: FLAT, PULLBACK_SETUP: FLAT, NO_SETUP: FLAT, NEUTRAL: FLAT, NOT_REQUESTED: FLAT,
  CAUTION: WAIT, REDUCE_RISK: WAIT, PROTECT: WAIT, REDUCE: WAIT, DEGRADED: WAIT, DEGRADED_CONSENSUS: WAIT, CONSENSUS_DISAGREEMENT: WAIT, BLOCKED_SETUP: WAIT,
  REJECT: DOWN, BLOCK: DOWN, EXIT: DOWN, EXITED: DOWN, AVOID: DOWN, NO_TRADE: DOWN, RISK_OFF: DOWN, UNAVAILABLE: DOWN,
};
const tone = (v) => TONE[v] || FLAT;
const trendTone = (t) => (t?.includes("UP") ? UP : t?.includes("DOWN") ? DOWN : FLAT);

async function call(fn) {
  try {
    return (await fn()).data;
  } catch (e) {
    toast.error(e.code === "ECONNABORTED" ? tx("Zaman aşımı: sunucu süresinde cevap vermedi. Tekrar dene.")
      : formatApiErrorDetail(e.response?.data?.detail) || tx("Danışman cevap vermedi."));
    return null;
  }
}

function Row({ label, children, strong }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-hairline py-2 text-[0.9375rem] last:border-0">
      <span className="text-t-3">{label}</span>
      <span className={`num text-right ${strong ? "text-lg font-bold text-t-1" : "text-t-1"}`}>{children}</span>
    </div>
  );
}

function Codes({ items, cls = WAIT }) {
  if (!items?.length) return null;
  return (
    <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-[0.9375rem]">
      {items.map((x, i) => (
        <li key={i}><b className={cls}>{x.code || "•"}</b> <span className="text-t-2">{x.text ?? x}</span></li>
      ))}
    </ul>
  );
}

function Stamp({ run }) {
  const s = run.snapshot;
  return (
    <p className="kp-note">
      {tx("Piyasa verisi: {m} (son kapanan 15m mum) · üretildi: {g} · veri yaşı {a} dk", { m: s.market_timestamp, g: relDay(run.generated_at), a: Math.round(s.data_age_seconds / 60) })}
      {s.stale ? ` · ${tx("VERİ ESKİ")}` : ""} · {tx("kural seti")} {run.ruleset_hash} · {tx("sürüm")} {run.advisor_version}
    </p>
  );
}

function Controls({ form, setForm, busy, onRun, label, position }) {
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <K.Card title="Coin" actions={<K.Button variant="primary" disabled={busy} onClick={onRun}>{busy ? tx("Hesaplanıyor…") : label}</K.Button>}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <K.Field label={tx("Parite")}><K.TextInput value={form.symbol} placeholder="BTC/USDT" onChange={set("symbol")} onKeyDown={(e) => e.key === "Enter" && onRun()} /></K.Field>
        <K.Field label={tx("Portföy (USDT)")} hint={tx("boş: botun portföyü okunur")}><K.TextInput prefix="$" inputMode="decimal" value={form.portfolio} placeholder="—" onChange={set("portfolio")} /></K.Field>
        {position && <K.Field label={tx("Giriş fiyatı")} hint={tx("boş: bottaki kayıt")}><K.TextInput inputMode="decimal" value={form.entry} placeholder="—" onChange={set("entry")} /></K.Field>}
        {position && <K.Field label={tx("İlk stop")} hint={tx("R birimi buna göre")}><K.TextInput inputMode="decimal" value={form.initialStop} placeholder="—" onChange={set("initialStop")} /></K.Field>}
      </div>
      <div className="mt-3 flex flex-wrap gap-5 text-[0.9375rem] text-t-2">
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.ai} onChange={set("ai")} /> {tx("3 bağımsız AI analizi: Teknik / Risk / Rejim (kapalıysa AL planı verilmez)")}</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.usePortfolio} onChange={set("usePortfolio")} /> {tx("Botun portföyünü kullan")}</label>
      </div>
    </K.Card>
  );
}

function TimeframeCard({ tf, f }) {
  const i = f.indicators;
  if (!i) return <K.Card title={tf.toUpperCase()}><p className="kp-note">{tx("Veri yetersiz ({n} mum).", { n: f.bars })}</p></K.Card>;
  return (
    <K.Card title={tf.toUpperCase()}>
      <Row label="Trend"><b className={trendTone(f.trend)}>{tx(ARROW[f.trend])}</b></Row>
      <Row label="RSI14">{n(i.rsi14)}</Row>
      <Row label="ATR14">{n(i.atr14)} <span className="text-t-3">({pct(i.atr_pct)})</span></Row>
      <Row label="VWAP">{n(i.vwap)}</Row>
      <Row label={tx("Hacim / ort.")}>{i.volume_ratio == null ? "—" : `${U.fmtNum(i.volume_ratio, 2)}×`}</Row>
      <Row label="SMA20 / 50 / 200">{n(i.sma20)} / {n(i.sma50)} / {n(i.sma200)}</Row>
    </K.Card>
  );
}

function Zones({ title, zones }) {
  return (
    <K.Card title={title}>
      {!zones?.length ? <p className="kp-note">{tx("Kayıtlı bölge yok.")}</p> : zones.map((z, i) => (
        <Row key={i} label={`${z.touch_count} ${tx("temas")} · ${z.timeframe.join("+")}`}>{zone(z)} <span className="text-t-3">({pct(z.distance_pct)})</span></Row>
      ))}
    </K.Card>
  );
}

const AGENT_TITLE = { TECHNICAL: "Teknik analist", RISK: "Risk / uygulama", REGIME: "Rejim / şüpheci" };
const AGENT_LISTS = {
  TECHNICAL: [["evidence", "Kanıt"], ["counter_evidence", "Karşı kanıt"], ["levels_to_watch", "İzlenecek seviyeler (bilgi; emir fiyatı değil)"]],
  RISK: [["risk_flags", "Risk"], ["portfolio_flags", "Portföy"], ["execution_flags", "Uygulama"]],
  REGIME: [["macro_risks", "Makro riskler"], ["market_risks", "Piyasa riskleri"], ["data_quality_flags", "Veri kalitesi"]],
};

function AgentCard({ role, v }) {
  if (!v) return <K.Card title={tx(AGENT_TITLE[role])}><p className="kp-note">{tx("Çağrılmadı.")}</p></K.Card>;
  const failed = v.status !== "OK";
  return (
    <K.Card title={tx(AGENT_TITLE[role])} actions={<span className="text-sm text-t-3">{v.model || tx("ayarlı değil")}</span>}>
      <div className="flex items-baseline justify-between gap-3">
        <b className={`text-[1.375rem] ${failed ? FLAT : tone(v.verdict)}`}>{failed ? tx("CEVAP YOK") : v.verdict}</b>
        {!failed && <span className="num text-t-2">{tx("güven")} {U.fmtNum(v.confidence * 100, 0)}%</span>}
      </div>
      {failed ? <p className="kp-note">{tx("Sebep")}: {v.error}. {tx("Eksik analist varken AL planı verilmez.")}</p> : (
        <>
          {v.setup && <p className="kp-note">{tx("Kurulum")}: {v.setup}</p>}
          <p className="mt-3 text-[0.9375rem] leading-relaxed text-t-2">{v.reason}</p>
          {AGENT_LISTS[role].map(([key, label]) => v[key]?.length > 0 && (
            <div key={key} className="mt-3">
              <div className="text-sm font-semibold text-t-3">{tx(label)}</div>
              <ul className="m-0 mt-1 list-disc pl-5 text-[0.9375rem] text-t-2">{v[key].map((x, i) => <li key={i}>{x}</li>)}</ul>
            </div>
          ))}
        </>
      )}
    </K.Card>
  );
}

function Consensus({ run }) {
  const c = run.consensus;
  const models = new Set(Object.values(run.models || {}).filter((m) => m?.model).map((m) => `${m.provider}/${m.model}`)).size;
  return (
    <K.Card title={tx("Final konsensüs")} actions={<b className={tone(c.consensus)}>{c.consensus_tr}</b>}>
      <div className="kp-grid kp-g-4">
        <K.StatCard label="Final" value={<span className={tone(run.final)}>{run.final}</span>} sub={run.mode === "POSITION" ? tx("pozisyon var") : tx("yeni pozisyon")} />
        <K.StatCard label={tx("Teknik")} value={<span className={tone(c.technical_verdict)}>{c.technical_verdict || "—"}</span>} />
        <K.StatCard label="Risk (veto)" value={<span className={tone(c.risk_verdict)}>{c.risk_verdict || "—"}</span>} />
        <K.StatCard label={tx("Rejim (veto)")} value={<span className={tone(c.regime_verdict)}>{c.regime_verdict || "—"}</span>} />
      </div>
      <p className="kp-note">
        {tx("Karar kodda: Teknik BUY + Risk APPROVE + Rejim BLOCK değil + kural motorunda uygulanabilir plan. Risk ve rejim vetosu çoğunlukla aşılamaz; eksik analist = AL yok.")}{" "}
        {models === 1 ? `${tx("3 bağımsız analiz, tek model: bu üç modelli bir konsensüs değildir.")} ` : models > 1 ? `${tx("3 bağımsız analiz, {n} farklı model.", { n: models })} ` : ""}
        {c.reasons.join(" · ")}
      </p>
    </K.Card>
  );
}

function WhyNot({ run }) {
  if (run.buy_plan || !run.why_not_trade?.length) return null;
  return (
    <K.Callout tone="warn" title={tx("Neden işlem yok")}>
      <ul className="m-0 list-disc pl-5">{run.why_not_trade.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </K.Callout>
  );
}

function AnalyzeView({ run }) {
  const s = run.snapshot, st = s.structure, e = run.engine, m = s.macro || {};
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={`${s.symbol}/${s.quote_asset} fiyat`} value={n(s.current_price)} sub={s.live ? tx("açık mum (yalnız gösterim)") : tx("son kapanış")} />
        <K.StatCard label={tx("Kural motoru")} value={<span className={tone(e.status)}>{e.status}</span>} sub={`${e.status_tr} · ${tx("kurulum")} ${e.setup}`} />
        <K.StatCard label={tx("BTC rejimi")} value={<span className={tone(s.btc.regime)}>{s.btc.regime}</span>} sub={`1h ${s.btc.trend_1h} · 4h ${s.btc.trend_4h}`} />
        <K.StatCard label="Makro" value={<span className={tone(m.macro_status)}>{m.macro_status}</span>} sub={m.caution ? `${tx("temkin")}: ${m.next_high_impact_event}` : m.risk_context || tx("risk filtresi")} />
      </div>
      <Stamp run={run} />
      <div className="kp-grid kp-g-4">{["15m", "1h", "4h", "1d"].map((tf) => <TimeframeCard key={tf} tf={tf} f={s.timeframes[tf]} />)}</div>
      <div className="kp-grid kp-g-3">
        <Zones title={tx("Direnç")} zones={st.resistances} />
        <Zones title={tx("Destek")} zones={st.supports} />
        <K.Card title={tx("Kırılım durumu")}>
          <Row label={tx("Durum")}><b>{st.breakout_status}</b></Row>
          <Row label={tx("Kontrol seviyesi")}>{n(st.control_level)}</Row>
          <Row label={tx("Seviyeye uzaklık")}>{st.distance_from_control_level_atr == null ? "—" : `${U.fmtNum(st.distance_from_control_level_atr, 2)} ATR(15m)`}</Row>
          <Row label={tx("Kırılan direnç")}>{n(st.broken_resistance)}</Row>
          <Row label={tx("Geri test bölgesi")}>{zone(st.retest_zone)}</Row>
          <Row label={tx("Geri alış")}>{st.reclaim ? (st.reclaim.confirmed ? tx("tutundu ({n} mum)", { n: st.reclaim.held_bars }) : tx("bekleniyor ({n} mum)", { n: st.reclaim.held_bars })) : "—"}</Row>
          <p className="kp-note">{tx("Teyit yalnız kapanmış 15m mumla.")} {st.open_candle_above ? tx("Açık mum direncin üstünde: kapanmadan sayılmaz.") : ""}</p>
        </K.Card>
      </div>
      {(e.blocks.length > 0 || e.waits.length > 0 || e.warnings.length > 0) && (
        <K.Card title={tx("Kural motoru notları")}>
          <Codes items={e.blocks} cls={DOWN} />
          <Codes items={e.waits} cls={FLAT} />
          <Codes items={e.warnings} cls={WAIT} />
        </K.Card>
      )}
      <div className="kp-grid kp-g-3">{["TECHNICAL", "RISK", "REGIME"].map((r) => <AgentCard key={r} role={r} v={run.agents?.[r]} />)}</div>
      <Consensus run={run} />
      <WhyNot run={run} />
    </>
  );
}

function PlanCard({ plan, quote, released }) {
  const pos = plan.position;
  return (
    <K.Card title={released ? tx("STOP-LIMIT AL") : tx("Kural motorunun seviyeleri (onaylanmadı)")}
      actions={<span className={`kp-alarm__status ${released ? "" : "is-flat"}`}>{released ? tx("Konsensüs onayı var") : tx("Plan değil, bilgi")}</span>}>
      <div className="kp-grid kp-g-2">
        <div>
          <Row label={tx("Kurulum")}>{plan.setup} · {plan.kind}</Row>
          {plan.resistance && <Row label={tx("Direnç")}>{zone(plan.resistance)}</Row>}
          {plan.retest_zone && <Row label={tx("Geri test bölgesi")}>{zone(plan.retest_zone)}</Row>}
          {plan.trigger != null && <Row label={tx("Tetik (stop)")} strong>{n(plan.trigger)}</Row>}
          {plan.limit != null && <Row label="Limit" strong>{n(plan.limit)}</Row>}
          {plan.confirmation_price != null && <Row label={tx("Teyit fiyatı")}>{n(plan.confirmation_price)}</Row>}
        </div>
        <div>
          <Row label={tx("İlk teknik stop")} strong>{n(plan.technical_stop)}</Row>
          <Row label={tx("Geçersizlik")}>{n(plan.technical_invalidation)}</Row>
          <Row label={tx("Stop mesafesi")}>{pct(plan.stop_distance_pct)} · {U.fmtNum(plan.stop_distance_atr15, 2)} ATR(15m)</Row>
          {plan.take_profit_reference != null && <Row label={tx("Kâr al referansı")}>{n(plan.take_profit_reference)} <span className="text-t-3">({plan.take_profit_source})</span></Row>}
          {plan.trigger != null && <Row label={tx("Önerilen pozisyon")}>{pos ? `${n(pos.suggested_notional)} ${quote}` : `— (${plan.position_note})`}</Row>}
          {pos && <Row label={tx("Stop olursa kayıp")}>{n(pos.loss_at_stop)} {quote} · {tx("portföyün {p}'i", { p: pct(pos.risk_of_portfolio_pct, 3) })}</Row>}
        </div>
      </div>
      <p className="kp-note">
        {plan.stop_source}. {plan.confirmation_rule || ""} {tx("Kanıt durumu: ARAŞTIRMA (15m kırılım kuralı geçmiş testte işlem başına yaklaşık −0,21R verdi; bu plan kazanç kanıtı değildir).")}{" "}
        {plan.take_profit_is_research_fallback ? `${tx("Üstte direnç yok: hedef 2,5R araştırma varsayımıdır.")} ` : ""}
        {pos ? `${tx("Sınırlayan")}: ${pos.limited_by}${pos.limit_basis ? ` (${pos.limit_basis})` : ""}. ` : ""}{tx("Emir gönderilmedi.")}
      </p>
    </K.Card>
  );
}

function BuyView({ run }) {
  const e = run.engine, plan = run.buy_plan || run.unreleased_plan || e.withheld_plan, s = run.snapshot;
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={`${s.symbol}/${s.quote_asset}`} value={n(s.current_price)} sub={tx("şimdi")} />
        <K.StatCard label="Final" value={<span className={tone(run.final)}>{run.final}</span>} sub={e.status_tr} />
        <K.StatCard label={tx("Kurulum")} value={e.setup} sub={`${tx("sonuç")}: ${e.result}`} />
        <K.StatCard label={tx("Konsensüs")} value={<span className={tone(run.consensus.consensus)}>{run.consensus.consensus}</span>} sub={run.consensus.consensus_tr} />
      </div>
      {plan ? <PlanCard plan={plan} quote={s.quote_asset} released={!!run.buy_plan} /> : (
        <K.EmptyState icon="alert" title={tx("AL planı yok")}>{tx("Kural motorunda fiyatlanabilir bir kurulum yok.")}</K.EmptyState>
      )}
      {e.retest && (
        <K.Card title={tx("Geri test durumu")}>
          <Row label={tx("Kırılan direnç")}>{n(e.retest.broken_resistance)}</Row>
          <Row label={tx("Geri test bölgesi")}>{n(e.retest.zone_low)} – {n(e.retest.zone_high)}</Row>
          <Row label={tx("Bölgeye uzaklık")}>{U.fmtNum(e.retest.current_distance_atr15, 2)} ATR(15m)</Row>
          <Row label={tx("Bölgeye girdi mi")}>{e.retest.entered_zone ? tx("evet") : tx("hayır")}</Row>
          <Row label={tx("Teyit mumu")}>{e.retest.confirmation ? `${e.retest.confirmation.time} · ${tx("kapanış")} ${n(e.retest.confirmation.close)}` : tx("yok")}</Row>
          <p className="kp-note">{tx("Teyit: bir 15m mum bölgeye girip {p} üstünde KAPANMALI. Açık mum teyit sayılmaz.", { p: n(e.retest.broken_resistance) })}</p>
        </K.Card>
      )}
      <WhyNot run={run} />
      {e.next_review && <p className="kp-note">{tx("Sonraki kontrol")}: {e.next_review}</p>}
      <Stamp run={run} />
    </>
  );
}

function SellView({ run }) {
  const p = run.sell_plan, s = run.snapshot;
  if (!p || p.error) {
    return <K.EmptyState icon="portfolio" title={tx("Pozisyon yok")}>{tx("Bu coinde kayıtlı pozisyon yok. Giriş fiyatını (ve varsa ilk stopunu) yazıp “Koruma planı”na bas.")}</K.EmptyState>;
  }
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={`${s.symbol}/${s.quote_asset}`} value={n(p.current_price)} sub={`${tx("giriş")} ${n(p.entry_price)}`} />
        <K.StatCard label={tx("Öneri§eylem")} value={<span className={tone(p.action)}>{p.action}</span>} sub={p.action_tr} />
        <K.StatCard label={p.current_R_estimated ? tx("Şu an (tahmini R)") : tx("Şu an")}
          value={`${p.current_R_estimated ? "~" : ""}${p.current_R > 0 ? "+" : ""}${U.fmtNum(p.current_R, 2)}R`}
          tone={p.current_R > 0 ? "up" : p.current_R < 0 ? "down" : undefined}
          sub={p.current_R_estimated ? `ESTIMATED_R · ${tx("ilk stop kayıtlı değil")} · ${tx("durum")} ${p.state}` : `${tx("durum")} ${p.state}`} />
        <K.StatCard label={tx("Nefes payı")} value={p.breathing_room_atr15 == null ? "—" : `${U.fmtNum(p.breathing_room_atr15, 2)} ATR`} sub={tx("fiyat − stop, 15m ATR")} />
      </div>
      <K.Card title={tx("Pozisyon koruma")} actions={<span className="kp-alarm__status is-flat">{tx("Piyasa satışı değil")}</span>}>
        <div className="kp-grid kp-g-2">
          <div>
            <Row label={tx("Kâr al")} strong>{n(p.take_profit)}</Row>
            <Row label={tx("Kâr al kaynağı")}>{p.take_profit_source}</Row>
            <Row label={tx("Zarar durdur")} strong>{n(p.stop_loss)}</Row>
            <Row label={tx("Stop kaynağı")}>{p.stop_source}</Row>
            <Row label={tx("Teknik geçersizlik")}>{n(p.technical_invalidation)}</Row>
          </div>
          <div>
            <Row label={tx("İlk stop")}>{n(p.initial_stop)}{p.initial_stop_assumed ? tx(" (varsayım)") : p.initial_stop_source === "V2_PLAN" ? tx(" (V2 planından)") : ""}</Row>
            <Row label={tx("Başa baş + masraf")}>{n(p.break_even_level)}</Row>
            <Row label={tx("3 ATR iz süren referans")}>{n(p.trailing_reference_3atr)}</Row>
            <Row label={tx("Önceki stop")}>{n(p.previous_stop)}</Row>
            <Row label={tx("Açık K/Z")}>{pct(p.unrealized_pnl_pct)}</Row>
          </div>
        </div>
        <p className="kp-note">{tx("Stop yalnız yukarı taşınır. +1R öncesi ilk yapısal stop korunur.")} {p.trailing_note}. {tx("Sonraki kontrol")}: {p.next_review}. {tx("Emir gönderilmedi.")}</p>
      </K.Card>
      {p.exit_reasons.length > 0 && <K.Callout tone="down" title={tx("Çıkış nedenleri")}><Codes items={p.exit_reasons} cls={DOWN} /></K.Callout>}
      {(p.reasons.length > 0 || p.warnings.length > 0) && (
        <K.Card title={tx("Gerekçe ve uyarılar")}>
          {p.reasons.length > 0 && <ul className="m-0 mb-3 list-disc pl-5 text-[0.9375rem] text-t-2">{p.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>}
          <Codes items={p.warnings} />
        </K.Card>
      )}
      <Stamp run={run} />
    </>
  );
}

function Overview() {
  const q = useData("advisor-v2-health", "/admin/advisor/health");
  const h = q.data;
  if (!h) return <K.Skeleton rows={4} label={tx("Durum okunuyor…")} />;
  const rules = Object.entries(h.thresholds);
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={tx("Sürüm")} value={h.advisor_version} sub={`${tx("kural seti")} ${h.ruleset_hash}`} />
        <K.StatCard label={tx("Kod§yazılım")} value={(h.git_commit || "—").slice(0, 10)} sub={h.working_tree_dirty ? tx("yerel değişiklik var") : tx("temiz")} />
        <K.StatCard label="OpenBB" value={h.openbb.mode} sub={tx("makro / çapraz varlık")} />
        <K.StatCard label={tx("Otomatik işlem")} value={tx("YOK")} sub={tx("hiçbir uç nokta emir göndermez")} />
      </div>
      <K.Card title={tx("Analistler")}>
        {Object.entries(h.analysts).map(([role, a]) => (
          <Row key={role} label={tx(AGENT_TITLE[role])}>{a ? `${a.provider} · ${a.model}` : <span className={WAIT}>{tx("anahtar yok (AL planı verilmez)")}</span>}</Row>
        ))}
        <p className="kp-note">
          {tx("Üç analist ROLÜ aynı anlık görüntüyü birbirinden bağımsız okur: 3 bağımsız AI analizi.")}{" "}
          {h.model_diversity.distinct_models <= 1 ? tx("Üç rol de aynı modeli kullanıyor; bu üç farklı modelin konsensüsü değildir.") : tx("{n} farklı model kullanılıyor.", { n: h.model_diversity.distinct_models })}{" "}
          {tx("Sert süre sınırı: analist başına {a} sn, üçü birlikte {b} sn; aşan analist FAILED sayılır ve AL planı verilmez. Anahtarlar yalnız sunucuda durur; bu sayfaya hiçbir anahtar gelmez.", { a: h.timeouts.AI_TIMEOUT_SECONDS, b: h.timeouts.AI_TOTAL_TIMEOUT_SECONDS })}
        </p>
      </K.Card>
      <K.Card title={tx("Akış")}>
        <p className="m-0 text-[0.9375rem] leading-relaxed text-t-2">
          {tx("Binance mumları (15m / 1h / 4h / 1d, yalnız kapanmış) → MarketSnapshot → kural motoru (destek/direnç, kırılım, geri test, stop, hedef, tutar) → 3 bağımsız AI analizi (Teknik / Risk / Rejim) → deterministik konsensüs → plan. Fiyatların tamamını kod hesaplar; model yalnız “kurulum mantıklı mı?” sorusunu cevaplar. OpenBB yalnız makro risk filtresidir, alım sinyali değildir. Telegram'daki /danis ile aynı metin raporu:")}{" "}
          <a className="underline" href="/app/danisman">{tx("klasik danışman sayfası")}</a>.
        </p>
      </K.Card>
      <K.Card title={tx("Pay sınırları")} actions={<span className="kp-alarm__status is-flat">{h.policy.basis}</span>}>
        {Object.entries(h.policy.limits).map(([k, v]) => <Row key={k} label={k}>%{String(v)}</Row>)}
        <p className="kp-note">{h.policy.note} {tx("Sunucuda ADVISOR_<AD> ile değiştirilir.")}</p>
      </K.Card>
      <K.Card title={tx("Eşikler ({n})", { n: rules.length })}>
        <div className="grid gap-x-8 sm:grid-cols-2">{rules.map(([k, v]) => <Row key={k} label={k}>{Array.isArray(v) ? (v.length ? v.join(", ") : tx("boş")) : String(v)}</Row>)}</div>
        <p className="kp-note">{tx("Sunucuda ADVISOR_<AD> ortam değişkeniyle değiştirilir; değişen eşik kural seti kimliğini değiştirir. Yeterli paper örneği olmadan ayar yapılmaz.")}</p>
      </K.Card>
    </>
  );
}

function Scanner({ form }) {
  const [busy, setBusy] = useState(false);
  const [scan, setScan] = useState(null);
  const run = async () => {
    setBusy(true);
    const body = { use_portfolio: form.usePortfolio, ...(form.portfolio.trim() ? { portfolio_usdt: U.parseTr(form.portfolio) } : {}) };
    const out = await call(() => api.post("/admin/advisor/scan", body, { timeout: RUN_TIMEOUT_MS }));
    if (out) setScan(out);
    setBusy(false);
  };
  return (
    <>
      <K.Card title={tx("Fırsat taraması")} actions={<K.Button variant="primary" disabled={busy} onClick={run}>{busy ? tx("Taranıyor…") : tx("60 pariteyi tara")}</K.Button>}>
        <p className="kp-note">{tx("En çok işlem gören USDT pariteleri kural motorundan geçer (yapay zekâ çağrılmaz). Satırdaki seviyeler adaydır; onay için coini Analiz sekmesinden geçir.")}</p>
        {busy && <p className="kp-note">{tx("Bir dakikaya yakın sürebilir.")}</p>}
      </K.Card>
      {scan && (
        <>
          <div className="kp-grid kp-g-4">
            {["READY_TO_WATCH", "WAIT_FOR_RETEST", "WAIT_FOR_BREAKOUT", "BLOCKED_SETUP"].map((g) => (
              <K.StatCard key={g} label={g} value={String(scan.groups[g]?.length || 0)} sub={(scan.groups[g] || []).slice(0, 6).join(", ") || "—"} />
            ))}
          </div>
          <K.Card title={tx("Sonuçlar ({a} / {b})", { a: scan.results.length, b: scan.scanned })}>
            <K.DataTable rows={scan.results} rowKey="symbol" columns={[
              { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}{r.held ? tx(" · portföyde") : ""}</b> },
              { key: "group", label: tx("Grup"), render: (r) => <span className={tone(r.status)}>{r.group}</span> },
              { key: "setup", label: tx("Kurulum"), mobile: false },
              { key: "current_price", label: tx("Fiyat"), num: true, render: (r) => n(r.current_price) },
              { key: "trigger", label: tx("Tetik / limit"), num: true, render: (r) => (r.trigger ? `${n(r.trigger)} / ${n(r.limit)}` : r.retest_zone ? `${tx("bölge")} ${zone(r.retest_zone)}` : "—") },
              { key: "technical_stop", label: "Stop", num: true, render: (r) => (r.technical_stop ? `${n(r.technical_stop)} (${pct(r.stop_distance_pct)})` : "—") },
              { key: "trend", label: "1h / 4h", mobile: false, render: (r) => `${r.trend_1h} / ${r.trend_4h}` },
              { key: "why", label: tx("Not"), mobile: false, render: (r) => <span className="text-t-2">{r.why_not[0] || r.rank_reasons.join("; ")}</span> },
            ]} />
            <p className="kp-note">{tx("Sıra")}: {scan.ranking.join(" → ")}. {tx("Tek bir birleşik puan yok.")} {scan.note}</p>
          </K.Card>
        </>
      )}
    </>
  );
}

function Portfolio() {
  const q = useData("advisor-v2-portfolio", "/admin/advisor/portfolio");
  const d = q.data;
  if (!d) return <K.Skeleton rows={4} label={tx("Portföy okunuyor…")} />;
  const p = d.portfolio;
  if (!p) return <K.EmptyState icon="portfolio" title={tx("Portföy verisi yok")}>{tx("Bot henüz portföyü göndermedi; analizde tutarı elle yazabilirsin.")}</K.EmptyState>;
  const L = d.limits;
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={tx("Portföy değeri (USD)")} value={n(p.portfolio_value)} sub={p.total_known ? tx("bütün piyasalar + nakit") : tx("yalnız bilinen kısım")} />
        <K.StatCard label={tx("Kripto payı")} value={pct(p.portfolio_crypto_exposure)} sub={`${tx("politika sınırı")} %${L.MAX_TOTAL_CRYPTO_EXPOSURE_PCT}`} />
        <K.StatCard label={tx("Altcoin payı")} value={pct(p.portfolio_alt_exposure)} sub={`${tx("politika sınırı")} %${L.MAX_ALT_EXPOSURE_PCT}`} />
        <K.StatCard label={tx("Memecoin payı")} value={pct(p.portfolio_meme_exposure)} sub={`${tx("politika sınırı")} %${L.MAX_MEME_EXPOSURE_PCT}`} />
      </div>
      {d.warnings.length > 0 && <K.Callout tone="warn" title={tx("Yoğunlaşma uyarıları")}><Codes items={d.warnings} /></K.Callout>}
      <K.Card title={tx("Kripto varlıklar ({n})", { n: p.holdings.length })}>
        <K.DataTable rows={p.holdings} rowKey="symbol" columns={[
          { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}</b> },
          { key: "asset_class", label: tx("Sınıf") },
          { key: "value", label: tx("Değer"), num: true, render: (r) => n(r.value) },
          { key: "share", label: tx("Pay"), num: true, render: (r) => (p.portfolio_value ? pct((r.value / p.portfolio_value) * 100) : "—") },
        ]} />
        <p className="kp-note">
          {tx("Sınırlar paya göredir (kaç coin olduğuna göre değil) ve {b}: {n} Yeni pozisyon: risk %{r}, en fazla portföyün %{m}'i.", { b: d.policy.basis, n: d.policy.note, r: L.RISK_PER_TRADE_PCT, m: L.MAX_NEW_POSITION_PCT })}
        </p>
      </K.Card>
      <K.Card title={tx("Kayıtlı işlem durumları ({n})", { n: d.position_states.length })}>
        {!d.position_states.length ? <p className="kp-note">{tx("Henüz koruma planı çalıştırılmadı.")}</p> : (
          <K.DataTable rows={d.position_states} rowKey="symbol" columns={[
            { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}</b> },
            { key: "state", label: tx("Durum") },
            { key: "entry_price", label: tx("Giriş"), num: true, render: (r) => n(r.entry_price) },
            { key: "initial_stop", label: tx("İlk stop"), num: true, render: (r) => `${n(r.initial_stop)}${r.initial_stop_assumed ? " *" : ""}` },
            { key: "last_stop", label: tx("Son stop"), num: true, render: (r) => n(r.last_stop) },
            { key: "max_R", label: tx("En yüksek R"), num: true, render: (r) => U.fmtNum(r.max_R, 2) },
          ]} />
        )}
      </K.Card>
    </>
  );
}

function Macro() {
  const q = useData("advisor-v2-macro", "/admin/advisor/macro");
  const m = q.data;
  if (!m) return <K.Skeleton rows={4} label={tx("OpenBB okunuyor (ilk okuma yarım dakika sürebilir)…")} />;
  const flat = (o) => Object.entries(o || {}).flatMap(([k, v]) => Object.entries(v || {}).filter(([f]) => !["date", "unit"].includes(f)).map(([f, x]) => [`${k} · ${f}`, x, v.date]));
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={tx("Makro durumu")} value={<span className={tone(m.macro_status)}>{m.macro_status}</span>} sub={`OpenBB: ${m.openbb_mode || "—"}`} />
        <K.StatCard label={tx("Yüksek etkili veri (2s)")} value={m.high_impact_event_within_2h == null ? tx("bilinmiyor") : m.high_impact_event_within_2h ? tx("VAR") : tx("yok")} sub={m.next_high_impact_event || "—"} />
        <K.StatCard label={tx("Yeni giriş")} value={<span className={m.block_new_entry ? DOWN : m.caution ? WAIT : UP}>{m.block_new_entry ? tx("ENGEL") : m.caution ? tx("TEMKİN") : tx("serbest")}</span>} sub={tx("makro yalnız risk filtresi")} />
        <K.StatCard label={tx("Bağlam")} value={m.equity_market?.vix ? `VIX ${n(m.equity_market.vix.last)}` : "—"} sub={m.risk_context || tx("veri yok")} />
      </div>
      {m.macro_status !== "OK" && (
        <K.Callout tone="warn" title={tx("Makro eksik çalışıyor")}>
          {tx("OpenBB okunamayan alanlar boş bırakıldı; teknik danışman etkilenmez.")} {m.unavailable_fields.map((u) => `${u.field}: ${u.reason}`).join(" · ")}
        </K.Callout>
      )}
      <K.Card title={tx("Ekonomik takvim ({n})", { n: m.economic_events.length })}>
        {!m.economic_events.length ? <p className="kp-note">{tx("Yaklaşan olay yok ya da takvim okunamadı.")}</p> : (
          <K.DataTable rows={m.economic_events} rowKey="time_utc" columns={[
            { key: "time_utc", label: tx("Zaman"), render: (r) => relDay(r.time_utc) },
            { key: "event", label: tx("Olay"), render: (r) => <b>{r.event}</b> },
            { key: "high_impact", label: tx("Etki"), render: (r) => (r.high_impact == null ? <span className="text-t-3">{tx("bilinmiyor")}</span> : r.high_impact ? <b className={WAIT}>{tx("yüksek")}</b> : "normal") },
            { key: "consensus", label: tx("Beklenti / önceki"), num: true, mobile: false, render: (r) => `${r.consensus ?? "—"} / ${r.previous ?? "—"}` },
            { key: "source", label: tx("Kaynak"), mobile: false, render: (r) => <span className="text-t-3">{r.source}</span> },
          ]} />
        )}
        <p className="kp-note">{tx("Etki derecesi")}: {m.impact_basis}.</p>
      </K.Card>
      <div className="kp-grid kp-g-3">
        {[[tx("Faiz"), m.rates], [tx("Enflasyon"), m.inflation], [tx("İstihdam"), m.employment]].map(([title, block]) => (
          <K.Card key={title} title={title}>
            {flat(block).length ? flat(block).map(([k, v, date]) => <Row key={k} label={`${k} (${date})`}>{v == null ? "—" : `%${U.fmtNum(v, 2)}`}</Row>) : <p className="kp-note">{tx("Veri yok.")}</p>}
          </K.Card>
        ))}
      </div>
      <p className="kp-note">{tx("Kaynaklar")}: {m.sources.map((s) => s.source).filter((v, i, a) => a.indexOf(v) === i).join(" · ") || "—"}. {tx("Bayat alanlar")}: {m.stale_fields.join(", ") || tx("yok")}.</p>
    </>
  );
}

function Paper() {
  const [origin, setOrigin] = useState("LIVE");
  const q = useData(["advisor-v2-paper", origin], `/admin/advisor/paper-stats?origin=${origin}`);
  const d = q.data;
  if (!d) return <K.Skeleton rows={4} label={tx("Paper kayıtları okunuyor…")} />;
  const x = d.exit_styles;
  const rows = Object.entries(x.variants).map(([k, v]) => ({ id: k, ...v }));
  const r2 = (v) => (v == null ? "—" : U.fmtNum(v, 2));
  return (
    <>
      <K.Card title={tx("Çıkış biçimleri karşılaştırması")} actions={<K.Segmented ariaLabel={tx("Kaynak")} value={origin} onChange={setOrigin} options={["LIVE", "REPLAY", "TEST", "ALL"]} />}>
        <div className="kp-grid kp-g-4">
          <K.StatCard label={tx("Kayıt§adet")} value={String(x.records)} sub={tx("{n} ayrı kurulum", { n: x.setups })} />
          <K.StatCard label={tx("Girişi olan")} value={String(x.entered)} sub={tx("{n} simüle edildi", { n: x.simulated })} />
          <K.StatCard label={tx("En az örnek")} value={String(x.min_sample)} sub={tx("altı: INCONCLUSIVE")} />
          <K.StatCard label={tx("Whipsaw oranı")} value={x.whipsaw.all.whipsaw_rate == null ? "—" : pct(x.whipsaw.all.whipsaw_rate, 1)} sub={`${x.whipsaw.all.stops} stop · ${x.whipsaw.all.verdict}`} />
        </div>
        <K.DataTable rows={rows} columns={[
          { key: "id", label: tx("Biçim"), render: (r) => <span><b>{r.id}</b> {r.label}</span> },
          { key: "sample_size", label: tx("Örnek"), num: true },
          { key: "verdict", label: tx("Durum"), render: (r) => <span className={r.verdict === "MEASURED" ? UP : WAIT}>{r.verdict}</span> },
          { key: "expectancy_R", label: tx("Beklenti R"), num: true, render: (r) => r2(r.expectancy_R) },
          { key: "win_rate", label: tx("İsabet"), num: true, render: (r) => (r.win_rate == null ? "—" : pct(r.win_rate, 1)) },
          { key: "profit_factor", label: "PF", num: true, mobile: false, render: (r) => r2(r.profit_factor) },
          { key: "max_drawdown_R", label: tx("Maks DD (R)"), num: true, mobile: false, render: (r) => r2(r.max_drawdown_R) },
          { key: "stop_rate", label: "Stop / TP", num: true, mobile: false, render: (r) => (r.stop_rate == null ? "—" : `${pct(r.stop_rate, 0)} / ${pct(r.TP_rate, 0)}`) },
          { key: "whipsaw_rate", label: "Whipsaw", num: true, mobile: false, render: (r) => (r.whipsaw_rate == null ? "—" : pct(r.whipsaw_rate, 1)) },
          { key: "MFE", label: "MFE / MAE", num: true, mobile: false, render: (r) => `${r2(r.MFE)} / ${r2(r.MAE)}` },
          { key: "MFE_left_on_table", label: tx("Masada kalan"), num: true, mobile: false, render: (r) => r2(r.MFE_left_on_table) },
          { key: "avg_holding_time_hours", label: tx("Süre (s)"), num: true, mobile: false, render: (r) => r2(r.avg_holding_time_hours) },
        ]} />
        <p className="kp-note">{d.note} {tx("Aynı giriş ve aynı ilk stop; yalnız çıkış değişir. Stop ve hedef aynı mumdaysa stop sayılır.")}</p>
      </K.Card>
      <K.Card title={tx("Whipsaw: stop mesafesine göre")}>
        {Object.entries(x.whipsaw.by_stop_distance_atr15).map(([k, v]) => (
          <Row key={k} label={`${k} ATR(15m)`}>{v.stops} stop · {v.whipsaw_rate == null ? "—" : pct(v.whipsaw_rate, 1)} · {v.verdict}</Row>
        ))}
        <p className="kp-note">{x.whipsaw.note}</p>
      </K.Card>
    </>
  );
}

function History() {
  const q = useData("advisor-v2-history", "/admin/advisor/consensus-history?limit=50");
  const rows = q.data;
  if (!rows) return <K.Skeleton rows={4} label={tx("Kayıtlar okunuyor…")} />;
  return (
    <K.Card title={tx("Konsensüs kaydı ({n})", { n: rows.length })}>
      {!rows.length ? <p className="kp-note">{tx("Henüz kayıt yok.")}</p> : (
        <K.DataTable rows={rows.map((r, i) => ({ ...r, id: i }))} columns={[
          { key: "generated_at", label: tx("Zaman"), render: (r) => relDay(r.generated_at) },
          { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}</b> },
          { key: "final", label: "Final", render: (r) => <span className={tone(r.final)}>{r.final}</span> },
          { key: "final_consensus", label: tx("Konsensüs"), render: (r) => <span className={tone(r.final_consensus)}>{r.final_consensus}</span> },
          { key: "verdicts", label: tx("Teknik / risk / rejim"), mobile: false, render: (r) => `${r.technical_verdict || "—"} / ${r.risk_verdict || "—"} / ${r.regime_verdict || "—"}` },
          { key: "plan_released", label: "Plan", render: (r) => (r.plan_released ? <b className={UP}>{tx("verildi")}</b> : tx("yok")) },
          { key: "ruleset_hash", label: tx("Kural seti"), mobile: false, render: (r) => <span className="text-t-3">{r.ruleset_hash} · {(r.git_commit || "").slice(0, 7)}</span> },
        ]} />
      )}
      <p className="kp-note">{tx("Her çalıştırma anlık görüntü kimliği, model adları, süreler ve kural seti ile saklanır. E-posta saklanmaz (yalnız özet).")}</p>
    </K.Card>
  );
}

export default function AdminAdvisor() {
  useLang(); // dil değişince sayfa yeniden çizilir
  const [tab, setTab] = useState("Analiz");
  const [form, setForm] = useState({ symbol: "BTC", portfolio: "", entry: "", initialStop: "", ai: true, usePortfolio: true });
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);

  const execute = async (path) => {
    const symbol = form.symbol.trim().toUpperCase().replace("/", "").replace(/USDT$/, "");
    if (!symbol) return toast.error(tx("Parite yaz (ör. BTC/USDT)."));
    const num = (v, name) => {
      if (!String(v).trim()) return undefined;
      const x = U.parseTr(String(v));
      if (!(x > 0)) throw new Error(tx("{n} pozitif bir sayı olmalı.", { n: tx(name) }));
      return x;
    };
    let body;
    try {
      body = { symbol, with_ai: form.ai, use_portfolio: form.usePortfolio, portfolio_usdt: num(form.portfolio, "Portföy"),
        ...(path === "sell-plan" ? { entry_price: num(form.entry, tx("Giriş fiyatı")), initial_stop: num(form.initialStop, tx("İlk stop")) } : {}) };
    } catch (e) {
      return toast.error(e.message);
    }
    setBusy(true);
    const out = await call(() => api.post(`/admin/advisor/${path}`, body, { timeout: RUN_TIMEOUT_MS }));
    setBusy(false);
    if (out) setRun(out.run || out);
    return null;
  };

  return (
    <div className="kp-page">
      <K.PageHeader controls={false} title={tx("Kripto Danışman V2")}
        subtitle={tx("Yönetici paneli · karar desteği: analiz, AL planı, koruma planı. Emir gönderilmez.")} />
      <div className="overflow-x-auto"><K.Segmented ariaLabel={tx("Sekme")} value={tab} onChange={setTab} options={TABS.map((v) => ({ value: v, label: tx(v) }))} /></div>
      {tab === "Özet" && <Overview />}
      {tab === "Analiz" && (
        <>
          <Controls form={form} setForm={setForm} busy={busy} onRun={() => execute("analyze")} label={tx("ANALİZ ET")} />
          {busy && <p className="kp-note">{tx("Mumlar çekiliyor, üç analiz paralel çalışıyor (genelde 20–45 sn; sunucu en geç ~2,5 dakikada keser).")}</p>}
          {run ? <AnalyzeView run={run} /> : <K.EmptyState icon="chart" title={tx("Henüz analiz yok")}>{tx("Pariteyi yazıp “ANALİZ ET”e bas.")}</K.EmptyState>}
        </>
      )}
      {tab === "AL planı" && (
        <>
          <Controls form={form} setForm={setForm} busy={busy} onRun={() => execute("buy-plan")} label={tx("AL PLANI")} />
          {run ? <BuyView run={run} /> : <K.EmptyState icon="chart" title={tx("Henüz plan yok")}>{tx("“AL PLANI”na bas: tetik, limit, stop, geçersizlik ve tutar hesaplanır.")}</K.EmptyState>}
        </>
      )}
      {tab === "SAT / Koruma" && (
        <>
          <Controls form={form} setForm={setForm} busy={busy} onRun={() => execute("sell-plan")} label={tx("KORUMA PLANI")} position />
          {run ? <SellView run={run} /> : <K.EmptyState icon="portfolio" title={tx("Henüz plan yok")}>{tx("“KORUMA PLANI”: kâr al, zarar durdur, geçersizlik, şu anki R.")}</K.EmptyState>}
        </>
      )}
      {tab === "Tarayıcı" && <Scanner form={form} />}
      {tab === "Portföy" && <Portfolio />}
      {tab === "Makro" && <Macro />}
      {tab === "Paper" && <Paper />}
      {tab === "Konsensüs kaydı" && <History />}
      <p className="kp-note">
        {tx("Karar desteğidir, yatırım tavsiyesi değildir. Kırılım ve geri test kuralları geçmiş veride kazandıran bir üstünlük göstermedi; planlar ARAŞTIRMA durumundadır. Hiçbir borsaya ya da aracı kuruma emir gönderilmez.")}
      </p>
    </div>
  );
}
