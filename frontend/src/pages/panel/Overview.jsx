import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { DataView, StatCard, Panel } from "@/components/DataView";
import { RegimeScale } from "@/pages/panel/Macro";
import { PriceChart } from "@/components/PriceChart";
import { PctBadge, MarketTag } from "@/components/bits";
import { formatCurrency, formatPct, formatNumber, relativeTime } from "@/lib/format";
import { MARKET_LABEL, MARKET_ORDER, px, money, dayLabel, marketTotals } from "@/lib/portfolio";
import { ArrowUpRight, Bell, Wallet, GitCommitVertical, Zap, Target, AlertTriangle } from "lucide-react";

const TONE_DOT = { up: "bg-up", down: "bg-down", info: "bg-info", wait: "bg-wait" };
const TONE_LINE = { up: "border-up", down: "border-down", info: "border-info", wait: "border-wait" };
const FRESH = {
  "güncel": { dot: "bg-up", label: "Güncel" },
  "eski": { dot: "bg-wait", label: "Eski" },
  "bayat": { dot: "bg-down", label: "Bayat" },
  yok: { dot: "bg-t-3", label: "Yok" },
};

function FreshnessPanel({ rows }) {
  if (!rows || rows.length === 0) return null;
  // Only sources the decision gate uses can block an AL; the rest are informational.
  const bad = rows.filter((r) => r.kapiyi_etkiler && (r.durum === "bayat" || r.durum === "yok"));
  return (
    <Panel title="Veri güncelliği" testid="overview-freshness"
      action={<span className={bad.length ? "text-xs text-down" : "text-xs text-up"}>{bad.length ? `Karar kapısı: ${bad.length} sorunlu kaynak` : "Karar verileri güncel"}</span>}>
      <ul className="divide-y divide-hairline">
        {rows.map((r) => {
          const f = FRESH[r.durum] || FRESH.yok;
          return (
            <li key={r.kaynak} className="flex items-center justify-between gap-3 py-2 text-sm">
              <span className="flex items-center gap-2 text-t-1">
                <span className={`h-2 w-2 shrink-0 rounded-full ${f.dot}`} aria-hidden />
                {r.kaynak}
              </span>
              <span className="text-right text-xs text-t-2">
                <span className="num">{r.yas}</span> · {f.label}
                {r.not ? <span className="block text-t-3">{r.not}</span> : null}
              </span>
            </li>
          );
        })}
      </ul>
      {bad.length > 0 && <p className="mt-3 text-xs text-t-3">Bayat ya da eksik veriyle karar kapısı AL vermez.</p>}
    </Panel>
  );
}

function PortfolioPulse({ extras }) {
  const rows = extras?.portfoy || [];
  if (!rows.length) return null;
  const totals = marketTotals(rows);
  return (
    <Panel title="Portföy nabzı" testid="overview-portfolio"
      action={<Link to="/app/portfoy" className="inline-flex items-center gap-1 text-xs text-t-2 hover:text-t-1">Portföy <ArrowUpRight className="h-3 w-3" /></Link>}>
      <div className="divide-y divide-hairline">
        {MARKET_ORDER.filter((m) => totals[m]).map((m) => {
          const t = totals[m];
          return (
            <div key={m} className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0">
              <div>
                <div className="text-xs text-t-2"><MarketTag m={m} label={`${MARKET_LABEL[m]} · ${t.adet} varlık`} /></div>
                <div className="num text-xl font-semibold text-t-1">{money(t.deger, t.para)}</div>
              </div>
              <div className="space-y-1 text-right text-xs text-t-2">
                <div>{dayLabel(m)} <PctBadge value={t.gun_yuzde} /></div>
                <div>Toplam <PctBadge value={t.kz_yuzde} /></div>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function Movers({ extras }) {
  const tl = extras?.takip_listesi?.piyasalar;
  if (!tl) return null;
  const all = Object.entries(tl).flatMap(([m, rs]) => rs.filter((r) => !r.hata && r.gun_yuzde != null).map((r) => ({ ...r, m })));
  if (!all.length) return null;
  const sorted = [...all].sort((a, b) => b.gun_yuzde - a.gun_yuzde);
  const Row = ({ r }) => (
    <li className="flex items-center justify-between gap-2 py-1.5 text-sm">
      <span className="text-t-1">
        <MarketTag m={r.m} label={<b>{r.kod}</b>} /> <span className="num text-xs text-t-3">{px(r.fiyat)}</span>
      </span>
      <PctBadge value={r.gun_yuzde} />
    </li>
  );
  return (
    <Panel title="Takip: hareket edenler" testid="overview-movers"
      action={<Link to="/app/takip" className="inline-flex items-center gap-1 text-xs text-t-2 hover:text-t-1">Tümü <ArrowUpRight className="h-3 w-3" /></Link>}>
      <p className="eyebrow mb-1 text-[10px] text-up">En çok yükselen</p>
      <ul>{sorted.slice(0, 3).map((r) => <Row key={r.m + r.kod} r={r} />)}</ul>
      <p className="eyebrow mb-1 mt-3 text-[10px] text-down">En çok düşen</p>
      <ul>{sorted.slice(-3).reverse().map((r) => <Row key={r.m + r.kod} r={r} />)}</ul>
    </Panel>
  );
}

function BtcChart() {
  const q = useData(["candles", "BTC-USDT"], "/candles/BTC-USDT", { retry: false, refetchInterval: 60_000 });
  const c = q.data?.candles;
  if (!c?.length) return null;
  const last = c[c.length - 1].c;
  const first = c[0].c;
  return (
    <Panel title="BTC / USDT · 1 saatlik" testid="overview-btc"
      action={<span className="flex items-center gap-2"><span className="num text-sm font-semibold text-t-1">{px(last)}</span><PctBadge value={((last - first) / first) * 100} /></span>}>
      <PriceChart data={c} sma20={q.data.sma20} sma50={q.data.sma50} sma200={q.data.sma200} height={220} />
      <p className="mt-2 text-[11px] text-t-3">Son {c.length} mum; değişim bu aralığın başından.</p>
    </Panel>
  );
}

const linkCls = "inline-flex items-center gap-1.5 rounded-lg border border-hairline px-3 py-1.5 text-xs text-t-1 transition-colors duration-150 hover:bg-raised";

export default function Overview() {
  const q = useData("overview", "/overview");
  const extras = useData("extras", "/extras", LIVE);
  const today = new Date().toLocaleDateString("tr-TR", { day: "numeric", month: "long", year: "numeric", weekday: "long" });
  return (
    <div>
      <PageHeader title="Genel bakış" subtitle={`${today} · kapanıştan önce bakman gerekenler, tek sakin ekranda.`} testid="page-overview" />
      <DataView query={q} loadingText="Panel özeti hazırlanıyor…">
        {(d) => {
          const gateBad = (d.veri_durumu || []).filter((r) => r.kapiyi_etkiler && (r.durum === "bayat" || r.durum === "yok"));
          return (
            <div className="space-y-6">
              {gateBad.length > 0 && (
                <div className="flex items-start gap-3 rounded-xl border border-down/50 bg-down/10 p-4 text-sm text-t-1" data-testid="overview-gate-banner">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-down" />
                  <span><b className="text-down">Karar kapısını etkileyen veri eski</b> ({gateBad.map((r) => r.kaynak).join(", ")}). Veri tazelenene kadar yeni AL verilmez.</span>
                </div>
              )}

              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
                <StatCard label={<MarketTag m="KRIPTO" label={`Kripto · ${dayLabel("KRIPTO")}`} />} value={formatCurrency(d.day_pnl)} sub={formatPct(d.day_pnl_pct)}
                  tone={d.day_pnl >= 0 ? "up" : "down"} glow testid="stat-day-pnl" />
                <StatCard label={<MarketTag m="BIST" label={`BIST · ${dayLabel("BIST").toLowerCase()}`} />} value={`${formatNumber(d.bist_day_pnl ?? 0, { decimals: 2, sign: true })} TL`}
                  sub={formatPct(d.bist_day_pnl_pct ?? 0)} tone={(d.bist_day_pnl ?? 0) >= 0 ? "up" : "down"} glow testid="stat-bist-pnl" />
                <StatCard label="Açık risk" value={`${formatNumber(d.open_r, { decimals: 2 })}R`} sub={`${d.open_positions} açık pozisyon`} icon={Target} testid="stat-open-r" />
                <StatCard label="Kurulu alarm" value={formatNumber(d.armed_alerts, { decimals: 0 })} sub="kapanış bekliyor" tone="info" icon={Bell} testid="stat-alerts" />
                <StatCard label="Bekleyen karar" value={formatNumber(d.pending_decisions, { decimals: 0 })} icon={Zap}
                  sub={d.pending_decisions ? <Link to="/app/sinyaller" className="text-wait hover:underline">Aldım / Pas →</Link> : "yok"}
                  tone={d.pending_decisions ? "wait" : undefined} glow={!!d.pending_decisions} testid="stat-decisions" />
              </div>

              <div className="grid gap-6 lg:grid-cols-3">
                <div className="lg:col-span-2"><PortfolioPulse extras={extras.data} /></div>
                <Movers extras={extras.data} />
              </div>

              <div className="grid gap-6 lg:grid-cols-3">
                <div className="lg:col-span-2">
                  <Panel title="Öne çıkanlar" testid="overview-highlights">
                    <ul className="space-y-2.5">
                      {d.highlights?.map((h, i) => (
                        <li key={i} className={`flex items-start gap-3 rounded-r-lg border-l-[3px] bg-raised/40 py-2 pl-3 pr-2 text-sm text-t-1 ${TONE_LINE[h.tone] || "border-t-3"}`}>
                          <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT[h.tone] || "bg-t-3"}`} />
                          {h.text}
                        </li>
                      ))}
                    </ul>
                    <div className="mt-5 flex flex-wrap gap-2">
                      <Link to="/app/alarmlar" className={linkCls}><Bell className="h-3.5 w-3.5" /> Alarmlar</Link>
                      <Link to="/app/pozisyonlar" className={linkCls}><Wallet className="h-3.5 w-3.5" /> Pozisyonlar</Link>
                      <Link to="/app/sinyaller" className={linkCls}><GitCommitVertical className="h-3.5 w-3.5" /> Sinyaller</Link>
                    </div>
                  </Panel>
                </div>
                <Panel title="Makro rejim" testid="overview-regime"
                  action={<Link to="/app/makro" className="inline-flex items-center gap-1 text-xs text-t-2 hover:text-t-1">Detay <ArrowUpRight className="h-3 w-3" /></Link>}>
                  <RegimeScale score={d.regime_score} label={d.regime_label} />
                  <p className="mt-4 text-xs text-t-3">Güncellendi {relativeTime(d.updated_at)}</p>
                </Panel>
              </div>

              <div className="grid gap-6 lg:grid-cols-3">
                <div className="lg:col-span-2"><BtcChart /></div>
                <FreshnessPanel rows={d.veri_durumu} />
              </div>
            </div>
          );
        }}
      </DataView>
    </div>
  );
}
