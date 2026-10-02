import { useState } from "react";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { useData } from "@/lib/useData";
import api, { formatApiErrorDetail } from "@/lib/api";
import { relDay } from "@/lib/dsmap";

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
    toast.error(e.code === "ECONNABORTED" ? "Zaman aşımı: sunucu süresinde cevap vermedi. Tekrar dene."
      : formatApiErrorDetail(e.response?.data?.detail) || "Danışman cevap vermedi.");
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
      Piyasa verisi: {s.market_timestamp} (son kapanan 15m mum) · üretildi: {relDay(run.generated_at)} · veri yaşı {Math.round(s.data_age_seconds / 60)} dk
      {s.stale ? " · VERİ ESKİ" : ""} · kural seti {run.ruleset_hash} · sürüm {run.advisor_version}
    </p>
  );
}

function Controls({ form, setForm, busy, onRun, label, position }) {
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <K.Card title="Coin" actions={<K.Button variant="primary" disabled={busy} onClick={onRun}>{busy ? "Hesaplanıyor…" : label}</K.Button>}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <K.Field label="Parite"><K.TextInput value={form.symbol} placeholder="BTC/USDT" onChange={set("symbol")} onKeyDown={(e) => e.key === "Enter" && onRun()} /></K.Field>
        <K.Field label="Portföy (USDT)" hint="boş: botun portföyü okunur"><K.TextInput prefix="$" inputMode="decimal" value={form.portfolio} placeholder="—" onChange={set("portfolio")} /></K.Field>
        {position && <K.Field label="Giriş fiyatı" hint="boş: bottaki kayıt"><K.TextInput inputMode="decimal" value={form.entry} placeholder="—" onChange={set("entry")} /></K.Field>}
        {position && <K.Field label="İlk stop" hint="R birimi buna göre"><K.TextInput inputMode="decimal" value={form.initialStop} placeholder="—" onChange={set("initialStop")} /></K.Field>}
      </div>
      <div className="mt-3 flex flex-wrap gap-5 text-[0.9375rem] text-t-2">
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.ai} onChange={set("ai")} /> 3 bağımsız AI analizi: Teknik / Risk / Rejim (kapalıysa AL planı verilmez)</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.usePortfolio} onChange={set("usePortfolio")} /> Botun portföyünü kullan</label>
      </div>
    </K.Card>
  );
}

function TimeframeCard({ tf, f }) {
  const i = f.indicators;
  if (!i) return <K.Card title={tf.toUpperCase()}><p className="kp-note">Veri yetersiz ({f.bars} mum).</p></K.Card>;
  return (
    <K.Card title={tf.toUpperCase()}>
      <Row label="Trend"><b className={trendTone(f.trend)}>{ARROW[f.trend]}</b></Row>
      <Row label="RSI14">{n(i.rsi14)}</Row>
      <Row label="ATR14">{n(i.atr14)} <span className="text-t-3">({pct(i.atr_pct)})</span></Row>
      <Row label="VWAP">{n(i.vwap)}</Row>
      <Row label="Hacim / ort.">{i.volume_ratio == null ? "—" : `${U.fmtNum(i.volume_ratio, 2)}×`}</Row>
      <Row label="SMA20 / 50 / 200">{n(i.sma20)} / {n(i.sma50)} / {n(i.sma200)}</Row>
    </K.Card>
  );
}

function Zones({ title, zones }) {
  return (
    <K.Card title={title}>
      {!zones?.length ? <p className="kp-note">Kayıtlı bölge yok.</p> : zones.map((z, i) => (
        <Row key={i} label={`${z.touch_count} temas · ${z.timeframe.join("+")}`}>{zone(z)} <span className="text-t-3">({pct(z.distance_pct)})</span></Row>
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
  if (!v) return <K.Card title={AGENT_TITLE[role]}><p className="kp-note">Çağrılmadı.</p></K.Card>;
  const failed = v.status !== "OK";
  return (
    <K.Card title={AGENT_TITLE[role]} actions={<span className="text-sm text-t-3">{v.model || "ayarlı değil"}</span>}>
      <div className="flex items-baseline justify-between gap-3">
        <b className={`text-[1.375rem] ${failed ? FLAT : tone(v.verdict)}`}>{failed ? "CEVAP YOK" : v.verdict}</b>
        {!failed && <span className="num text-t-2">güven {U.fmtNum(v.confidence * 100, 0)}%</span>}
      </div>
      {failed ? <p className="kp-note">Sebep: {v.error}. Eksik analist varken AL planı verilmez.</p> : (
        <>
          {v.setup && <p className="kp-note">Kurulum: {v.setup}</p>}
          <p className="mt-3 text-[0.9375rem] leading-relaxed text-t-2">{v.reason}</p>
          {AGENT_LISTS[role].map(([key, label]) => v[key]?.length > 0 && (
            <div key={key} className="mt-3">
              <div className="text-sm font-semibold text-t-3">{label}</div>
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
    <K.Card title="Final konsensüs" actions={<b className={tone(c.consensus)}>{c.consensus_tr}</b>}>
      <div className="kp-grid kp-g-4">
        <K.StatCard label="Final" value={<span className={tone(run.final)}>{run.final}</span>} sub={run.mode === "POSITION" ? "pozisyon var" : "yeni pozisyon"} />
        <K.StatCard label="Teknik" value={<span className={tone(c.technical_verdict)}>{c.technical_verdict || "—"}</span>} />
        <K.StatCard label="Risk (veto)" value={<span className={tone(c.risk_verdict)}>{c.risk_verdict || "—"}</span>} />
        <K.StatCard label="Rejim (veto)" value={<span className={tone(c.regime_verdict)}>{c.regime_verdict || "—"}</span>} />
      </div>
      <p className="kp-note">
        Karar kodda: Teknik BUY + Risk APPROVE + Rejim BLOCK değil + kural motorunda uygulanabilir plan. Risk ve rejim vetosu çoğunlukla aşılamaz;
        eksik analist = AL yok. {models === 1 ? "3 bağımsız analiz, tek model: bu üç modelli bir konsensüs değildir. " : models > 1 ? `3 bağımsız analiz, ${models} farklı model. ` : ""}
        {c.reasons.join(" · ")}
      </p>
    </K.Card>
  );
}

function WhyNot({ run }) {
  if (run.buy_plan || !run.why_not_trade?.length) return null;
  return (
    <K.Callout tone="warn" title="Neden işlem yok">
      <ul className="m-0 list-disc pl-5">{run.why_not_trade.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </K.Callout>
  );
}

function AnalyzeView({ run }) {
  const s = run.snapshot, st = s.structure, e = run.engine, m = s.macro || {};
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={`${s.symbol}/${s.quote_asset} fiyat`} value={n(s.current_price)} sub={s.live ? "açık mum (yalnız gösterim)" : "son kapanış"} />
        <K.StatCard label="Kural motoru" value={<span className={tone(e.status)}>{e.status}</span>} sub={`${e.status_tr} · kurulum ${e.setup}`} />
        <K.StatCard label="BTC rejimi" value={<span className={tone(s.btc.regime)}>{s.btc.regime}</span>} sub={`1h ${s.btc.trend_1h} · 4h ${s.btc.trend_4h}`} />
        <K.StatCard label="Makro" value={<span className={tone(m.macro_status)}>{m.macro_status}</span>} sub={m.caution ? `temkin: ${m.next_high_impact_event}` : m.risk_context || "risk filtresi"} />
      </div>
      <Stamp run={run} />
      <div className="kp-grid kp-g-4">{["15m", "1h", "4h", "1d"].map((tf) => <TimeframeCard key={tf} tf={tf} f={s.timeframes[tf]} />)}</div>
      <div className="kp-grid kp-g-3">
        <Zones title="Direnç" zones={st.resistances} />
        <Zones title="Destek" zones={st.supports} />
        <K.Card title="Kırılım durumu">
          <Row label="Durum"><b>{st.breakout_status}</b></Row>
          <Row label="Kontrol seviyesi">{n(st.control_level)}</Row>
          <Row label="Seviyeye uzaklık">{st.distance_from_control_level_atr == null ? "—" : `${U.fmtNum(st.distance_from_control_level_atr, 2)} ATR(15m)`}</Row>
          <Row label="Kırılan direnç">{n(st.broken_resistance)}</Row>
          <Row label="Geri test bölgesi">{zone(st.retest_zone)}</Row>
          <Row label="Geri alış">{st.reclaim ? (st.reclaim.confirmed ? `tutundu (${st.reclaim.held_bars} mum)` : `bekleniyor (${st.reclaim.held_bars} mum)`) : "—"}</Row>
          <p className="kp-note">Teyit yalnız kapanmış 15m mumla. {st.open_candle_above ? "Açık mum direncin üstünde: kapanmadan sayılmaz." : ""}</p>
        </K.Card>
      </div>
      {(e.blocks.length > 0 || e.waits.length > 0 || e.warnings.length > 0) && (
        <K.Card title="Kural motoru notları">
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
    <K.Card title={released ? "STOP-LIMIT AL" : "Kural motorunun seviyeleri (onaylanmadı)"}
      actions={<span className={`kp-alarm__status ${released ? "" : "is-flat"}`}>{released ? "Konsensüs onayı var" : "Plan değil, bilgi"}</span>}>
      <div className="kp-grid kp-g-2">
        <div>
          <Row label="Kurulum">{plan.setup} · {plan.kind}</Row>
          {plan.resistance && <Row label="Direnç">{zone(plan.resistance)}</Row>}
          {plan.retest_zone && <Row label="Geri test bölgesi">{zone(plan.retest_zone)}</Row>}
          {plan.trigger != null && <Row label="Tetik (stop)" strong>{n(plan.trigger)}</Row>}
          {plan.limit != null && <Row label="Limit" strong>{n(plan.limit)}</Row>}
          {plan.confirmation_price != null && <Row label="Teyit fiyatı">{n(plan.confirmation_price)}</Row>}
        </div>
        <div>
          <Row label="İlk teknik stop" strong>{n(plan.technical_stop)}</Row>
          <Row label="Geçersizlik">{n(plan.technical_invalidation)}</Row>
          <Row label="Stop mesafesi">{pct(plan.stop_distance_pct)} · {U.fmtNum(plan.stop_distance_atr15, 2)} ATR(15m)</Row>
          {plan.take_profit_reference != null && <Row label="Kâr al referansı">{n(plan.take_profit_reference)} <span className="text-t-3">({plan.take_profit_source})</span></Row>}
          {plan.trigger != null && <Row label="Önerilen pozisyon">{pos ? `${n(pos.suggested_notional)} ${quote}` : `— (${plan.position_note})`}</Row>}
          {pos && <Row label="Stop olursa kayıp">{n(pos.loss_at_stop)} {quote} · portföyün {pct(pos.risk_of_portfolio_pct, 3)}'i</Row>}
        </div>
      </div>
      <p className="kp-note">
        {plan.stop_source}. {plan.confirmation_rule || ""} Kanıt durumu: ARAŞTIRMA (15m kırılım kuralı geçmiş testte işlem başına yaklaşık −0,21R verdi; bu plan
        kazanç kanıtı değildir). {plan.take_profit_is_research_fallback ? "Üstte direnç yok: hedef 2,5R araştırma varsayımıdır. " : ""}
        {pos ? `Sınırlayan: ${pos.limited_by}${pos.limit_basis ? ` (${pos.limit_basis})` : ""}. ` : ""}Emir gönderilmedi.
      </p>
    </K.Card>
  );
}

function BuyView({ run }) {
  const e = run.engine, plan = run.buy_plan || run.unreleased_plan || e.withheld_plan, s = run.snapshot;
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={`${s.symbol}/${s.quote_asset}`} value={n(s.current_price)} sub="şimdi" />
        <K.StatCard label="Final" value={<span className={tone(run.final)}>{run.final}</span>} sub={e.status_tr} />
        <K.StatCard label="Kurulum" value={e.setup} sub={`sonuç: ${e.result}`} />
        <K.StatCard label="Konsensüs" value={<span className={tone(run.consensus.consensus)}>{run.consensus.consensus}</span>} sub={run.consensus.consensus_tr} />
      </div>
      {plan ? <PlanCard plan={plan} quote={s.quote_asset} released={!!run.buy_plan} /> : (
        <K.EmptyState icon="alert" title="AL planı yok">Kural motorunda fiyatlanabilir bir kurulum yok.</K.EmptyState>
      )}
      {e.retest && (
        <K.Card title="Geri test durumu">
          <Row label="Kırılan direnç">{n(e.retest.broken_resistance)}</Row>
          <Row label="Geri test bölgesi">{n(e.retest.zone_low)} – {n(e.retest.zone_high)}</Row>
          <Row label="Bölgeye uzaklık">{U.fmtNum(e.retest.current_distance_atr15, 2)} ATR(15m)</Row>
          <Row label="Bölgeye girdi mi">{e.retest.entered_zone ? "evet" : "hayır"}</Row>
          <Row label="Teyit mumu">{e.retest.confirmation ? `${e.retest.confirmation.time} · kapanış ${n(e.retest.confirmation.close)}` : "yok"}</Row>
          <p className="kp-note">Teyit: bir 15m mum bölgeye girip {n(e.retest.broken_resistance)} üstünde KAPANMALI. Açık mum teyit sayılmaz.</p>
        </K.Card>
      )}
      <WhyNot run={run} />
      {e.next_review && <p className="kp-note">Sonraki kontrol: {e.next_review}</p>}
      <Stamp run={run} />
    </>
  );
}

function SellView({ run }) {
  const p = run.sell_plan, s = run.snapshot;
  if (!p || p.error) {
    return <K.EmptyState icon="portfolio" title="Pozisyon yok">Bu coinde kayıtlı pozisyon yok. Giriş fiyatını (ve varsa ilk stopunu) yazıp “Koruma planı”na bas.</K.EmptyState>;
  }
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={`${s.symbol}/${s.quote_asset}`} value={n(p.current_price)} sub={`giriş ${n(p.entry_price)}`} />
        <K.StatCard label="Öneri" value={<span className={tone(p.action)}>{p.action}</span>} sub={p.action_tr} />
        <K.StatCard label={p.current_R_estimated ? "Şu an (tahmini R)" : "Şu an"}
          value={`${p.current_R_estimated ? "~" : ""}${p.current_R > 0 ? "+" : ""}${U.fmtNum(p.current_R, 2)}R`}
          tone={p.current_R > 0 ? "up" : p.current_R < 0 ? "down" : undefined}
          sub={p.current_R_estimated ? `ESTIMATED_R · ilk stop kayıtlı değil · durum ${p.state}` : `durum ${p.state}`} />
        <K.StatCard label="Nefes payı" value={p.breathing_room_atr15 == null ? "—" : `${U.fmtNum(p.breathing_room_atr15, 2)} ATR`} sub="fiyat − stop, 15m ATR" />
      </div>
      <K.Card title="Pozisyon koruma" actions={<span className="kp-alarm__status is-flat">Piyasa satışı değil</span>}>
        <div className="kp-grid kp-g-2">
          <div>
            <Row label="Kâr al" strong>{n(p.take_profit)}</Row>
            <Row label="Kâr al kaynağı">{p.take_profit_source}</Row>
            <Row label="Zarar durdur" strong>{n(p.stop_loss)}</Row>
            <Row label="Stop kaynağı">{p.stop_source}</Row>
            <Row label="Teknik geçersizlik">{n(p.technical_invalidation)}</Row>
          </div>
          <div>
            <Row label="İlk stop">{n(p.initial_stop)}{p.initial_stop_assumed ? " (varsayım)" : p.initial_stop_source === "V2_PLAN" ? " (V2 planından)" : ""}</Row>
            <Row label="Başa baş + masraf">{n(p.break_even_level)}</Row>
            <Row label="3 ATR iz süren referans">{n(p.trailing_reference_3atr)}</Row>
            <Row label="Önceki stop">{n(p.previous_stop)}</Row>
            <Row label="Açık K/Z">{pct(p.unrealized_pnl_pct)}</Row>
          </div>
        </div>
        <p className="kp-note">Stop yalnız yukarı taşınır. +1R öncesi ilk yapısal stop korunur. {p.trailing_note}. Sonraki kontrol: {p.next_review}. Emir gönderilmedi.</p>
      </K.Card>
      {p.exit_reasons.length > 0 && <K.Callout tone="down" title="Çıkış nedenleri"><Codes items={p.exit_reasons} cls={DOWN} /></K.Callout>}
      {(p.reasons.length > 0 || p.warnings.length > 0) && (
        <K.Card title="Gerekçe ve uyarılar">
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
  if (!h) return <K.Skeleton rows={4} label="Durum okunuyor…" />;
  const rules = Object.entries(h.thresholds);
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label="Sürüm" value={h.advisor_version} sub={`kural seti ${h.ruleset_hash}`} />
        <K.StatCard label="Kod" value={(h.git_commit || "—").slice(0, 10)} sub={h.working_tree_dirty ? "yerel değişiklik var" : "temiz"} />
        <K.StatCard label="OpenBB" value={h.openbb.mode} sub="makro / çapraz varlık" />
        <K.StatCard label="Otomatik işlem" value="YOK" sub="hiçbir uç nokta emir göndermez" />
      </div>
      <K.Card title="Analistler">
        {Object.entries(h.analysts).map(([role, a]) => (
          <Row key={role} label={AGENT_TITLE[role]}>{a ? `${a.provider} · ${a.model}` : <span className={WAIT}>anahtar yok (AL planı verilmez)</span>}</Row>
        ))}
        <p className="kp-note">
          Üç analist ROLÜ aynı anlık görüntüyü birbirinden bağımsız okur: 3 bağımsız AI analizi.{" "}
          {h.model_diversity.distinct_models <= 1 ? "Üç rol de aynı modeli kullanıyor; bu üç farklı modelin konsensüsü değildir." : `${h.model_diversity.distinct_models} farklı model kullanılıyor.`}{" "}
          Sert süre sınırı: analist başına {h.timeouts.AI_TIMEOUT_SECONDS} sn, üçü birlikte {h.timeouts.AI_TOTAL_TIMEOUT_SECONDS} sn; aşan analist FAILED sayılır ve AL planı verilmez.
          Anahtarlar yalnız sunucuda durur; bu sayfaya hiçbir anahtar gelmez.
        </p>
      </K.Card>
      <K.Card title="Akış">
        <p className="m-0 text-[0.9375rem] leading-relaxed text-t-2">
          Binance mumları (15m / 1h / 4h / 1d, yalnız kapanmış) → MarketSnapshot → kural motoru (destek/direnç, kırılım, geri test, stop, hedef, tutar) →
          3 bağımsız AI analizi (Teknik / Risk / Rejim) → deterministik konsensüs → plan. Fiyatların tamamını kod hesaplar; model yalnız “kurulum mantıklı mı?” sorusunu cevaplar.
          OpenBB yalnız makro risk filtresidir, alım sinyali değildir. Telegram'daki /danis ile aynı metin raporu:{" "}
          <a className="underline" href="/app/danisman">klasik danışman sayfası</a>.
        </p>
      </K.Card>
      <K.Card title="Pay sınırları" actions={<span className="kp-alarm__status is-flat">{h.policy.basis}</span>}>
        {Object.entries(h.policy.limits).map(([k, v]) => <Row key={k} label={k}>%{String(v)}</Row>)}
        <p className="kp-note">{h.policy.note} Sunucuda ADVISOR_&lt;AD&gt; ile değiştirilir.</p>
      </K.Card>
      <K.Card title={`Eşikler (${rules.length})`}>
        <div className="grid gap-x-8 sm:grid-cols-2">{rules.map(([k, v]) => <Row key={k} label={k}>{Array.isArray(v) ? (v.length ? v.join(", ") : "boş") : String(v)}</Row>)}</div>
        <p className="kp-note">Sunucuda ADVISOR_&lt;AD&gt; ortam değişkeniyle değiştirilir; değişen eşik kural seti kimliğini değiştirir. Yeterli paper örneği olmadan ayar yapılmaz.</p>
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
      <K.Card title="Fırsat taraması" actions={<K.Button variant="primary" disabled={busy} onClick={run}>{busy ? "Taranıyor…" : "60 pariteyi tara"}</K.Button>}>
        <p className="kp-note">En çok işlem gören USDT pariteleri kural motorundan geçer (yapay zekâ çağrılmaz). Satırdaki seviyeler adaydır; onay için coini Analiz sekmesinden geçir.</p>
        {busy && <p className="kp-note">Bir dakikaya yakın sürebilir.</p>}
      </K.Card>
      {scan && (
        <>
          <div className="kp-grid kp-g-4">
            {["READY_TO_WATCH", "WAIT_FOR_RETEST", "WAIT_FOR_BREAKOUT", "BLOCKED_SETUP"].map((g) => (
              <K.StatCard key={g} label={g} value={String(scan.groups[g]?.length || 0)} sub={(scan.groups[g] || []).slice(0, 6).join(", ") || "—"} />
            ))}
          </div>
          <K.Card title={`Sonuçlar (${scan.results.length} / ${scan.scanned})`}>
            <K.DataTable rows={scan.results} rowKey="symbol" columns={[
              { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}{r.held ? " · portföyde" : ""}</b> },
              { key: "group", label: "Grup", render: (r) => <span className={tone(r.status)}>{r.group}</span> },
              { key: "setup", label: "Kurulum", mobile: false },
              { key: "current_price", label: "Fiyat", num: true, render: (r) => n(r.current_price) },
              { key: "trigger", label: "Tetik / limit", num: true, render: (r) => (r.trigger ? `${n(r.trigger)} / ${n(r.limit)}` : r.retest_zone ? `bölge ${zone(r.retest_zone)}` : "—") },
              { key: "technical_stop", label: "Stop", num: true, render: (r) => (r.technical_stop ? `${n(r.technical_stop)} (${pct(r.stop_distance_pct)})` : "—") },
              { key: "trend", label: "1h / 4h", mobile: false, render: (r) => `${r.trend_1h} / ${r.trend_4h}` },
              { key: "why", label: "Not", mobile: false, render: (r) => <span className="text-t-2">{r.why_not[0] || r.rank_reasons.join("; ")}</span> },
            ]} />
            <p className="kp-note">Sıra: {scan.ranking.join(" → ")}. Tek bir birleşik puan yok. {scan.note}</p>
          </K.Card>
        </>
      )}
    </>
  );
}

function Portfolio() {
  const q = useData("advisor-v2-portfolio", "/admin/advisor/portfolio");
  const d = q.data;
  if (!d) return <K.Skeleton rows={4} label="Portföy okunuyor…" />;
  const p = d.portfolio;
  if (!p) return <K.EmptyState icon="portfolio" title="Portföy verisi yok">Bot henüz portföyü göndermedi; analizde tutarı elle yazabilirsin.</K.EmptyState>;
  const L = d.limits;
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label="Portföy değeri (USD)" value={n(p.portfolio_value)} sub={p.total_known ? "bütün piyasalar + nakit" : "yalnız bilinen kısım"} />
        <K.StatCard label="Kripto payı" value={pct(p.portfolio_crypto_exposure)} sub={`politika sınırı %${L.MAX_TOTAL_CRYPTO_EXPOSURE_PCT}`} />
        <K.StatCard label="Altcoin payı" value={pct(p.portfolio_alt_exposure)} sub={`politika sınırı %${L.MAX_ALT_EXPOSURE_PCT}`} />
        <K.StatCard label="Memecoin payı" value={pct(p.portfolio_meme_exposure)} sub={`politika sınırı %${L.MAX_MEME_EXPOSURE_PCT}`} />
      </div>
      {d.warnings.length > 0 && <K.Callout tone="warn" title="Yoğunlaşma uyarıları"><Codes items={d.warnings} /></K.Callout>}
      <K.Card title={`Kripto varlıklar (${p.holdings.length})`}>
        <K.DataTable rows={p.holdings} rowKey="symbol" columns={[
          { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}</b> },
          { key: "asset_class", label: "Sınıf" },
          { key: "value", label: "Değer", num: true, render: (r) => n(r.value) },
          { key: "share", label: "Pay", num: true, render: (r) => (p.portfolio_value ? pct((r.value / p.portfolio_value) * 100) : "—") },
        ]} />
        <p className="kp-note">
          Sınırlar paya göredir (kaç coin olduğuna göre değil) ve {d.policy.basis}: {d.policy.note} Yeni pozisyon: risk %{L.RISK_PER_TRADE_PCT},
          en fazla portföyün %{L.MAX_NEW_POSITION_PCT}'i.
        </p>
      </K.Card>
      <K.Card title={`Kayıtlı işlem durumları (${d.position_states.length})`}>
        {!d.position_states.length ? <p className="kp-note">Henüz koruma planı çalıştırılmadı.</p> : (
          <K.DataTable rows={d.position_states} rowKey="symbol" columns={[
            { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}</b> },
            { key: "state", label: "Durum" },
            { key: "entry_price", label: "Giriş", num: true, render: (r) => n(r.entry_price) },
            { key: "initial_stop", label: "İlk stop", num: true, render: (r) => `${n(r.initial_stop)}${r.initial_stop_assumed ? " *" : ""}` },
            { key: "last_stop", label: "Son stop", num: true, render: (r) => n(r.last_stop) },
            { key: "max_R", label: "En yüksek R", num: true, render: (r) => U.fmtNum(r.max_R, 2) },
          ]} />
        )}
      </K.Card>
    </>
  );
}

function Macro() {
  const q = useData("advisor-v2-macro", "/admin/advisor/macro");
  const m = q.data;
  if (!m) return <K.Skeleton rows={4} label="OpenBB okunuyor (ilk okuma yarım dakika sürebilir)…" />;
  const flat = (o) => Object.entries(o || {}).flatMap(([k, v]) => Object.entries(v || {}).filter(([f]) => !["date", "unit"].includes(f)).map(([f, x]) => [`${k} · ${f}`, x, v.date]));
  return (
    <>
      <div className="kp-grid kp-g-4">
        <K.StatCard label="Makro durumu" value={<span className={tone(m.macro_status)}>{m.macro_status}</span>} sub={`OpenBB: ${m.openbb_mode || "—"}`} />
        <K.StatCard label="Yüksek etkili veri (2s)" value={m.high_impact_event_within_2h == null ? "bilinmiyor" : m.high_impact_event_within_2h ? "VAR" : "yok"} sub={m.next_high_impact_event || "—"} />
        <K.StatCard label="Yeni giriş" value={<span className={m.block_new_entry ? DOWN : m.caution ? WAIT : UP}>{m.block_new_entry ? "ENGEL" : m.caution ? "TEMKİN" : "serbest"}</span>} sub="makro yalnız risk filtresi" />
        <K.StatCard label="Bağlam" value={m.equity_market?.vix ? `VIX ${n(m.equity_market.vix.last)}` : "—"} sub={m.risk_context || "veri yok"} />
      </div>
      {m.macro_status !== "OK" && (
        <K.Callout tone="warn" title="Makro eksik çalışıyor">
          OpenBB okunamayan alanlar boş bırakıldı; teknik danışman etkilenmez. {m.unavailable_fields.map((u) => `${u.field}: ${u.reason}`).join(" · ")}
        </K.Callout>
      )}
      <K.Card title={`Ekonomik takvim (${m.economic_events.length})`}>
        {!m.economic_events.length ? <p className="kp-note">Yaklaşan olay yok ya da takvim okunamadı.</p> : (
          <K.DataTable rows={m.economic_events} rowKey="time_utc" columns={[
            { key: "time_utc", label: "Zaman", render: (r) => relDay(r.time_utc) },
            { key: "event", label: "Olay", render: (r) => <b>{r.event}</b> },
            { key: "high_impact", label: "Etki", render: (r) => (r.high_impact == null ? <span className="text-t-3">bilinmiyor</span> : r.high_impact ? <b className={WAIT}>yüksek</b> : "normal") },
            { key: "consensus", label: "Beklenti / önceki", num: true, mobile: false, render: (r) => `${r.consensus ?? "—"} / ${r.previous ?? "—"}` },
            { key: "source", label: "Kaynak", mobile: false, render: (r) => <span className="text-t-3">{r.source}</span> },
          ]} />
        )}
        <p className="kp-note">Etki derecesi: {m.impact_basis}.</p>
      </K.Card>
      <div className="kp-grid kp-g-3">
        {[["Faiz", m.rates], ["Enflasyon", m.inflation], ["İstihdam", m.employment]].map(([title, block]) => (
          <K.Card key={title} title={title}>
            {flat(block).length ? flat(block).map(([k, v, date]) => <Row key={k} label={`${k} (${date})`}>{v == null ? "—" : `%${U.fmtNum(v, 2)}`}</Row>) : <p className="kp-note">Veri yok.</p>}
          </K.Card>
        ))}
      </div>
      <p className="kp-note">Kaynaklar: {m.sources.map((s) => s.source).filter((v, i, a) => a.indexOf(v) === i).join(" · ") || "—"}. Bayat alanlar: {m.stale_fields.join(", ") || "yok"}.</p>
    </>
  );
}

function Paper() {
  const [origin, setOrigin] = useState("LIVE");
  const q = useData(["advisor-v2-paper", origin], `/admin/advisor/paper-stats?origin=${origin}`);
  const d = q.data;
  if (!d) return <K.Skeleton rows={4} label="Paper kayıtları okunuyor…" />;
  const x = d.exit_styles;
  const rows = Object.entries(x.variants).map(([k, v]) => ({ id: k, ...v }));
  const r2 = (v) => (v == null ? "—" : U.fmtNum(v, 2));
  return (
    <>
      <K.Card title="Çıkış biçimleri karşılaştırması" actions={<K.Segmented ariaLabel="Kaynak" value={origin} onChange={setOrigin} options={["LIVE", "REPLAY", "TEST", "ALL"]} />}>
        <div className="kp-grid kp-g-4">
          <K.StatCard label="Kayıt" value={String(x.records)} sub={`${x.setups} ayrı kurulum`} />
          <K.StatCard label="Girişi olan" value={String(x.entered)} sub={`${x.simulated} simüle edildi`} />
          <K.StatCard label="En az örnek" value={String(x.min_sample)} sub="altı: INCONCLUSIVE" />
          <K.StatCard label="Whipsaw oranı" value={x.whipsaw.all.whipsaw_rate == null ? "—" : pct(x.whipsaw.all.whipsaw_rate, 1)} sub={`${x.whipsaw.all.stops} stop · ${x.whipsaw.all.verdict}`} />
        </div>
        <K.DataTable rows={rows} columns={[
          { key: "id", label: "Biçim", render: (r) => <span><b>{r.id}</b> {r.label}</span> },
          { key: "sample_size", label: "Örnek", num: true },
          { key: "verdict", label: "Durum", render: (r) => <span className={r.verdict === "MEASURED" ? UP : WAIT}>{r.verdict}</span> },
          { key: "expectancy_R", label: "Beklenti R", num: true, render: (r) => r2(r.expectancy_R) },
          { key: "win_rate", label: "İsabet", num: true, render: (r) => (r.win_rate == null ? "—" : pct(r.win_rate, 1)) },
          { key: "profit_factor", label: "PF", num: true, mobile: false, render: (r) => r2(r.profit_factor) },
          { key: "max_drawdown_R", label: "Maks DD (R)", num: true, mobile: false, render: (r) => r2(r.max_drawdown_R) },
          { key: "stop_rate", label: "Stop / TP", num: true, mobile: false, render: (r) => (r.stop_rate == null ? "—" : `${pct(r.stop_rate, 0)} / ${pct(r.TP_rate, 0)}`) },
          { key: "whipsaw_rate", label: "Whipsaw", num: true, mobile: false, render: (r) => (r.whipsaw_rate == null ? "—" : pct(r.whipsaw_rate, 1)) },
          { key: "MFE", label: "MFE / MAE", num: true, mobile: false, render: (r) => `${r2(r.MFE)} / ${r2(r.MAE)}` },
          { key: "MFE_left_on_table", label: "Masada kalan", num: true, mobile: false, render: (r) => r2(r.MFE_left_on_table) },
          { key: "avg_holding_time_hours", label: "Süre (s)", num: true, mobile: false, render: (r) => r2(r.avg_holding_time_hours) },
        ]} />
        <p className="kp-note">{d.note} Aynı giriş ve aynı ilk stop; yalnız çıkış değişir. Stop ve hedef aynı mumdaysa stop sayılır.</p>
      </K.Card>
      <K.Card title="Whipsaw: stop mesafesine göre">
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
  if (!rows) return <K.Skeleton rows={4} label="Kayıtlar okunuyor…" />;
  return (
    <K.Card title={`Konsensüs kaydı (${rows.length})`}>
      {!rows.length ? <p className="kp-note">Henüz kayıt yok.</p> : (
        <K.DataTable rows={rows.map((r, i) => ({ ...r, id: i }))} columns={[
          { key: "generated_at", label: "Zaman", render: (r) => relDay(r.generated_at) },
          { key: "symbol", label: "Coin", render: (r) => <b>{r.symbol}</b> },
          { key: "final", label: "Final", render: (r) => <span className={tone(r.final)}>{r.final}</span> },
          { key: "final_consensus", label: "Konsensüs", render: (r) => <span className={tone(r.final_consensus)}>{r.final_consensus}</span> },
          { key: "verdicts", label: "Teknik / risk / rejim", mobile: false, render: (r) => `${r.technical_verdict || "—"} / ${r.risk_verdict || "—"} / ${r.regime_verdict || "—"}` },
          { key: "plan_released", label: "Plan", render: (r) => (r.plan_released ? <b className={UP}>verildi</b> : "yok") },
          { key: "ruleset_hash", label: "Kural seti", mobile: false, render: (r) => <span className="text-t-3">{r.ruleset_hash} · {(r.git_commit || "").slice(0, 7)}</span> },
        ]} />
      )}
      <p className="kp-note">Her çalıştırma anlık görüntü kimliği, model adları, süreler ve kural seti ile saklanır. E-posta saklanmaz (yalnız özet).</p>
    </K.Card>
  );
}

export default function AdminAdvisor() {
  const [tab, setTab] = useState("Analiz");
  const [form, setForm] = useState({ symbol: "BTC", portfolio: "", entry: "", initialStop: "", ai: true, usePortfolio: true });
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);

  const execute = async (path) => {
    const symbol = form.symbol.trim().toUpperCase().replace("/", "").replace(/USDT$/, "");
    if (!symbol) return toast.error("Parite yaz (ör. BTC/USDT).");
    const num = (v, name) => {
      if (!String(v).trim()) return undefined;
      const x = U.parseTr(String(v));
      if (!(x > 0)) throw new Error(`${name} pozitif bir sayı olmalı.`);
      return x;
    };
    let body;
    try {
      body = { symbol, with_ai: form.ai, use_portfolio: form.usePortfolio, portfolio_usdt: num(form.portfolio, "Portföy"),
        ...(path === "sell-plan" ? { entry_price: num(form.entry, "Giriş fiyatı"), initial_stop: num(form.initialStop, "İlk stop") } : {}) };
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
      <K.PageHeader controls={false} title="Kripto Danışman V2"
        subtitle="Yönetici paneli · karar desteği: analiz, AL planı, koruma planı. Emir gönderilmez." />
      <div className="overflow-x-auto"><K.Segmented ariaLabel="Sekme" value={tab} onChange={setTab} options={TABS} /></div>
      {tab === "Özet" && <Overview />}
      {tab === "Analiz" && (
        <>
          <Controls form={form} setForm={setForm} busy={busy} onRun={() => execute("analyze")} label="ANALİZ ET" />
          {busy && <p className="kp-note">Mumlar çekiliyor, üç analiz paralel çalışıyor (genelde 20–45 sn; sunucu en geç ~2,5 dakikada keser).</p>}
          {run ? <AnalyzeView run={run} /> : <K.EmptyState icon="chart" title="Henüz analiz yok">Pariteyi yazıp “ANALİZ ET”e bas.</K.EmptyState>}
        </>
      )}
      {tab === "AL planı" && (
        <>
          <Controls form={form} setForm={setForm} busy={busy} onRun={() => execute("buy-plan")} label="AL PLANI" />
          {run ? <BuyView run={run} /> : <K.EmptyState icon="chart" title="Henüz plan yok">“AL PLANI”na bas: tetik, limit, stop, geçersizlik ve tutar hesaplanır.</K.EmptyState>}
        </>
      )}
      {tab === "SAT / Koruma" && (
        <>
          <Controls form={form} setForm={setForm} busy={busy} onRun={() => execute("sell-plan")} label="KORUMA PLANI" position />
          {run ? <SellView run={run} /> : <K.EmptyState icon="portfolio" title="Henüz plan yok">“KORUMA PLANI”: kâr al, zarar durdur, geçersizlik, şu anki R.</K.EmptyState>}
        </>
      )}
      {tab === "Tarayıcı" && <Scanner form={form} />}
      {tab === "Portföy" && <Portfolio />}
      {tab === "Makro" && <Macro />}
      {tab === "Paper" && <Paper />}
      {tab === "Konsensüs kaydı" && <History />}
      <p className="kp-note">
        Karar desteğidir, yatırım tavsiyesi değildir. Kırılım ve geri test kuralları geçmiş veride kazandıran bir üstünlük göstermedi; planlar ARAŞTIRMA durumundadır.
        Hiçbir borsaya ya da aracı kuruma emir gönderilmez.
      </p>
    </div>
  );
}
