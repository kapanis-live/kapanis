import { useState, useEffect } from "react";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, Panel } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { RRPill } from "@/components/bits";
import { QueuedBadge } from "@/components/QueuedBadge";
import { PriceChart, SmaLegend } from "@/components/PriceChart";
import { Button } from "@/components/ui/button";
import api, { formatApiErrorDetail } from "@/lib/api";
import { formatPrice, relativeTime } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { toast } from "sonner";
import { Check, X, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

const VERDICT_CLS = { AL: "bg-up/15 text-up", "ŞİMDİ AL": "bg-up/15 text-up", TUT: "bg-info/15 text-info", BEKLE: "bg-wait/15 text-wait", PAS: "bg-down/15 text-down" };

function ScoreChip({ score }) {
  const up = score > 0, down = score < 0;
  const Icon = up ? TrendingUp : down ? TrendingDown : Minus;
  return (
    <span className={cn("num inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold", up ? "bg-up/12 text-up" : down ? "bg-down/12 text-down" : "bg-t-3/20 text-t-2")}>
      <Icon className="h-3 w-3" />{score > 0 ? "+" : ""}{score}
    </span>
  );
}

function PendingDecisions({ decisions }) {
  const [queued, setQueued] = useState({});
  const pending = (decisions || []).filter((d) => d.status === "pending");
  if (pending.length === 0) return null;

  const act = async (id, verdict) => {
    setQueued((s) => ({ ...s, [id]: verdict }));
    try {
      await api.post(`/decisions/${id}/action`, { verdict });
      toast.success(`"${verdict}" kararı bota iletildi.`);
    } catch (err) {
      setQueued((s) => { const n = { ...s }; delete n[id]; return n; });
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Karar iletilemedi.");
    }
  };

  return (
    <Panel title="Bekleyen kararlar" testid="pending-decisions" className="mb-6">
      <div className="space-y-3">
        {pending.map((d) => (
          <div key={d.id} className="rounded-lg border border-wait/30 bg-wait/5 p-4" data-testid={`decision-${d.id}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center rounded bg-t-1 px-1.5 py-0.5 text-[11px] font-bold text-black">KARAR</span>
                <span className="font-semibold text-t-1">{d.symbol}</span>
                {d.market === "BIST" && <span className="rounded bg-info/15 px-1.5 py-0.5 text-[11px] text-info">BIST · TL</span>}
              </div>
              <RRPill rr={d.rr} />
            </div>
            <div className="num mt-2 grid grid-cols-3 gap-2 text-sm">
              <div><span className="text-t-3 text-xs block">Giriş</span>{formatPrice(d.entry)}</div>
              <div><span className="text-t-3 text-xs block">Stop</span><span className="text-down">{formatPrice(d.stop)}</span></div>
              <div><span className="text-t-3 text-xs block">Hedef</span><span className="text-up">{formatPrice(d.target)}</span></div>
            </div>
            <p className="mt-2 text-xs text-t-2">{d.chart_note}</p>
            {queued[d.id] ? (
              <div className="mt-3"><QueuedBadge label={`"${queued[d.id]}" iletildi`} /></div>
            ) : (
              <div className="mt-3 flex gap-2">
                <Button size="sm" onClick={() => act(d.id, "Aldım")} className="flex-1 bg-up text-black hover:bg-up/90" data-testid={`decision-aldim-${d.id}`}>
                  <Check className="h-4 w-4" /> Aldım
                </Button>
                <Button size="sm" variant="outline" onClick={() => act(d.id, "Pas")} className="flex-1 border-down/40 text-down hover:bg-down/10" data-testid={`decision-pas-${d.id}`}>
                  <X className="h-4 w-4" /> Pas
                </Button>
              </div>
            )}
          </div>
        ))}
      </div>
    </Panel>
  );
}

const RULE_STYLE = {
  gecti: { icon: "✓", cls: "text-up" },
  kaldi: { icon: "✕", cls: "text-down" },
  uyari: { icon: "!", cls: "text-wait" },
};
const OUTCOME_TEXT = {
  hedef: { label: "Hedefe gitti", cls: "text-up" },
  stop: { label: "Stopa gitti", cls: "text-down" },
  "açık": { label: "Henüz sonuçlanmadı", cls: "text-t-2" },
  "veri yok": { label: "Veri yok", cls: "text-t-3" },
};

// "Neden AL / BEKLE / PAS?" — the code gate's rules, the candle it used, and what happened after.
function WhyPanel({ analysis, currency }) {
  const gate = analysis?.gate;
  const outcome = analysis?.outcome;
  if (!gate && !outcome) return null;
  const o = outcome ? OUTCOME_TEXT[outcome.sonuc] || { label: outcome.sonuc, cls: "text-t-2" } : null;
  return (
    <div className="rounded-lg border border-hairline bg-ink p-4" data-testid="why-panel">
      <div className="flex items-center justify-between">
        <span className="text-xs text-t-3">Neden? — kod kapısı</span>
        {gate && (
          <span className={cn("rounded px-1.5 py-0.5 text-[11px] font-bold", gate.ok ? "bg-up/15 text-up" : "bg-down/15 text-down")}>
            {gate.ok ? "GEÇTİ" : "KALDI"}
          </span>
        )}
      </div>
      {gate?.mum && (
        <p className="num mt-2 text-xs text-t-2">
          Kullanılan mum: {gate.mum.zaman_dilimi} · {gate.mum.acilis_utc} UTC · kapanış {formatPrice(gate.mum.kapanis)}
        </p>
      )}
      {gate?.kurallar && (
        <ul className="mt-3 space-y-1.5">
          {gate.kurallar.map((r) => {
            const st = RULE_STYLE[r.durum] || RULE_STYLE.uyari;
            return (
              <li key={r.kural} className="flex items-start gap-2 text-xs">
                <span className={cn("num w-3 shrink-0 font-bold", st.cls)}>{st.icon}</span>
                <span className="text-t-1 font-medium shrink-0">{r.kural}</span>
                <span className="text-t-2">{r.detay}</span>
              </li>
            );
          })}
        </ul>
      )}
      {gate && (
        <p className="num mt-3 text-xs text-t-2">
          R/R {gate.rr ?? "—"} · ilk kademe {currency === "TL" ? `${gate.lot ?? 0} lot / ${gate.kademe_tl ?? 0} TL` : `${gate.kademe_usd ?? 0} USD`}{gate.risk_off ? " · risk azaltıldı" : ""}
        </p>
      )}
      {o && (
        <div className="mt-3 border-t border-hairline pt-3 text-xs">
          <span className="text-t-3">Sonradan ne oldu (kapanışla): </span>
          <span className={cn("font-semibold", o.cls)}>{o.label}</span>
          {outcome.R != null && <span className="num text-t-2"> · {outcome.R > 0 ? "+" : ""}{outcome.R}R · {outcome.mum} mum</span>}
        </div>
      )}
      {analysis?.user_action && <p className="mt-1.5 text-xs text-t-3">Senin kararın: {analysis.user_action}</p>}
    </div>
  );
}

function AnalysisDetail({ signal }) {
  const symbolId = signal.symbol.replace("/", "-");
  const cq = useData(["candles", symbolId], `/candles/${symbolId}`, { retry: false, enabled: signal.market !== "BIST" });
  const bot = signal.analysis?.bot_decision;

  return (
    <div className="space-y-4" data-testid="analysis-detail">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-t-1">{signal.symbol}</h3>
            <span className="text-xs text-t-3">{signal.timeframe} · {signal.type}</span>
          </div>
          <p className="mt-0.5 text-xs text-t-3">{relativeTime(signal.created_at)}</p>
        </div>
        <ScoreChip score={signal.score} />
      </div>

      {/* Grafik */}
      {signal.market === "BIST" ? (
        <div className="flex h-[120px] items-center justify-center rounded-lg border border-hairline bg-ink text-xs text-t-3">
          BIST grafiği panelde yok. Sinyal ve fiyat verisi gecikmeli; fiyatı aracı kurumdan doğrula.
        </div>
      ) : cq.isSuccess ? (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs text-t-2">Fiyat & hareketli ortalamalar</span>
            <SmaLegend />
          </div>
          <PriceChart data={cq.data.candles} sma20={cq.data.sma20} sma50={cq.data.sma50} sma200={cq.data.sma200} />
        </div>
      ) : cq.isLoading ? (
        <div className="h-[280px] rounded-lg bg-ink animate-pulse" />
      ) : (
        <div className="flex h-[120px] items-center justify-center rounded-lg border border-hairline bg-ink text-xs text-t-3">
          Bu sembol için grafik verisi yok.
        </div>
      )}

      {/* 4 panel */}
      <div className="grid grid-cols-2 gap-3" data-testid="analysis-panels">
        {signal.analysis?.panels?.map((p) => (
          <div key={p.key} className="rounded-lg border border-hairline bg-ink p-3">
            <div className="text-xs text-t-3">{p.title}</div>
            <div className="mt-0.5 text-sm font-semibold text-t-1">{p.value}</div>
            <p className="mt-1 text-xs text-t-2">{p.detail}</p>
          </div>
        ))}
      </div>

      {/* Bot kararı */}
      {bot && (
        <div className="rounded-lg border border-hairline bg-ink p-4" data-testid="bot-decision">
          <div className="flex items-center justify-between">
            <span className="text-xs text-t-3">Bot kararı</span>
            <span className={cn("rounded-md px-2 py-0.5 text-sm font-bold", VERDICT_CLS[bot.verdict] || "bg-t-3/15 text-t-1")}>{bot.verdict}</span>
          </div>
          {bot.confidence != null && (
            <div className="mt-2 h-1.5 rounded-full bg-surface overflow-hidden">
              <div className="h-full bg-t-1" style={{ width: `${Math.round(bot.confidence * 100)}%` }} />
            </div>
          )}
          <div className="mt-1.5 flex items-center justify-between text-xs text-t-2">
            <span>{bot.reason}</span>
            {bot.confidence != null && <span className="num">%{Math.round(bot.confidence * 100)}</span>}
          </div>
        </div>
      )}

      <WhyPanel analysis={signal.analysis} currency={signal.currency} />

      {/* Botun tam analiz metni */}
      {signal.analysis?.text && (
        <div className="rounded-lg border border-hairline bg-ink p-4" data-testid="analysis-text">
          <div className="mb-2 text-xs text-t-3">Analiz metni</div>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-t-1">{signal.analysis.text}</p>
        </div>
      )}
    </div>
  );
}

export default function Signals() {
  const sq = useData("signals", "/signals");
  const dq = useData("decisions", "/decisions");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    if (sq.data && sq.data.length && !selected) setSelected(sq.data[0]);
  }, [sq.data, selected]);

  return (
    <div>
      <PageHeader eyebrow="Sinyaller / Analiz" title="Sinyaller & Analiz" subtitle="Sinyal akışı, 4 panelli analiz ve bot kararı." testid="page-signals" />

      {dq.isSuccess && <PendingDecisions decisions={dq.data} />}

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-2">
          <Panel title="Sinyal akışı" testid="signal-feed">
            <DataView query={sq} loadingText={TEXTS.loading.signals}>
              {(signals) =>
                !signals || signals.length === 0 ? (
                  <EmptyState text={TEXTS.empty.signals} testid="signals-empty" />
                ) : (
                  <div className="space-y-2">
                    {signals.map((s) => (
                      <button
                        key={s.id}
                        onClick={() => setSelected(s)}
                        data-testid={`signal-item-${s.id}`}
                        className={cn(
                          "w-full rounded-lg border p-3 text-left transition-colors duration-150",
                          selected?.id === s.id ? "border-t-2/50 bg-ink" : "border-hairline bg-ink hover:border-t-3"
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-t-1">{s.symbol}</span>
                          <ScoreChip score={s.score} />
                        </div>
                        <div className="mt-0.5 text-xs text-t-3">{s.timeframe} · {s.type} · {relativeTime(s.created_at)}</div>
                        <p className="mt-1.5 text-xs text-t-2">{s.summary}</p>
                      </button>
                    ))}
                  </div>
                )
              }
            </DataView>
          </Panel>
        </div>

        <div className="lg:col-span-3">
          <Panel title="Analiz detayı" testid="analysis-panel">
            {selected ? <AnalysisDetail signal={selected} /> : (
              <EmptyState text="Detayı görmek için soldan bir sinyal seç." />
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
