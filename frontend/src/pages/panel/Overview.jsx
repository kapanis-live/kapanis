import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, StatCard, Panel } from "@/components/DataView";
import { RegimeScale } from "@/pages/panel/Macro";
import { formatCurrency, formatPct, formatNumber, relativeTime } from "@/lib/format";
import { ArrowUpRight, Bell, Wallet, GitCommitVertical } from "lucide-react";

const TONE_DOT = { up: "bg-up", down: "bg-down", info: "bg-info", wait: "bg-wait" };

export default function Overview() {
  const q = useData("overview", "/overview");
  return (
    <div>
      <PageHeader title="Genel Bakış" subtitle="Günün özeti, açık risk ve öne çıkanlar." testid="page-overview" />
      <DataView query={q} loadingText="Panel özeti hazırlanıyor…">
        {(d) => (
          <div className="space-y-6">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Günlük P/L" value={formatCurrency(d.day_pnl)} sub={formatPct(d.day_pnl_pct)} tone={d.day_pnl >= 0 ? "up" : "down"} testid="stat-day-pnl" />
              <StatCard label="Açık risk (R)" value={formatNumber(d.open_r, { decimals: 2 })} sub={`${d.open_positions} açık pozisyon`} testid="stat-open-r" />
              <StatCard label="Kurulu alarm" value={formatNumber(d.armed_alerts, { decimals: 0 })} sub="tetiklenme bekliyor" tone="info" testid="stat-alerts" />
              <StatCard label="Bekleyen karar" value={formatNumber(d.pending_decisions, { decimals: 0 })} sub="Aldım / Pas" tone="wait" testid="stat-decisions" />
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <Panel title="Öne çıkanlar" testid="overview-highlights">
                  <ul className="space-y-3">
                    {d.highlights?.map((h, i) => (
                      <li key={i} className="flex items-start gap-3 text-sm text-t-1">
                        <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT[h.tone] || "bg-t-3"}`} />
                        {h.text}
                      </li>
                    ))}
                  </ul>
                  <div className="mt-5 flex flex-wrap gap-2">
                    <Link to="/app/alarmlar" className="inline-flex items-center gap-1.5 rounded-md border border-hairline px-3 py-1.5 text-xs text-t-1 transition-colors duration-150 hover:bg-secondary"><Bell className="h-3.5 w-3.5" /> Alarmlar</Link>
                    <Link to="/app/pozisyonlar" className="inline-flex items-center gap-1.5 rounded-md border border-hairline px-3 py-1.5 text-xs text-t-1 transition-colors duration-150 hover:bg-secondary"><Wallet className="h-3.5 w-3.5" /> Pozisyonlar</Link>
                    <Link to="/app/sinyaller" className="inline-flex items-center gap-1.5 rounded-md border border-hairline px-3 py-1.5 text-xs text-t-1 transition-colors duration-150 hover:bg-secondary"><GitCommitVertical className="h-3.5 w-3.5" /> Sinyaller</Link>
                  </div>
                </Panel>
              </div>

              <Panel title="Makro rejim" testid="overview-regime" action={<Link to="/app/makro" className="text-xs text-t-2 hover:text-t-1 inline-flex items-center gap-1">Detay <ArrowUpRight className="h-3 w-3" /></Link>}>
                <RegimeScale score={d.regime_score} label={d.regime_label} />
                <p className="mt-4 text-xs text-t-3">Güncellendi {relativeTime(d.updated_at)}</p>
              </Panel>
            </div>
          </div>
        )}
      </DataView>
    </div>
  );
}
