import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, StatCard, Panel } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { SideBadge } from "@/components/bits";
import { formatNumber, formatPct, formatPrice, formatTime } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { cn } from "@/lib/utils";

export default function Report() {
  const q = useData("report", "/report");
  return (
    <div>
      <PageHeader title="Rapor" subtitle="İşlem geçmişi ve performans özeti." testid="page-report" />
      <DataView query={q} loadingText={TEXTS.loading.report}>
        {(d) => {
          const p = d.performance;
          return (
            <div className="space-y-6">
              <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
                <StatCard label="İşlem sayısı" value={formatNumber(p.count, { decimals: 0 })} testid="rep-count" />
                <StatCard label="Kazanma oranı" value={formatPct(p.win_rate * 100, { sign: false })} tone="up" testid="rep-winrate" />
                <StatCard label="Ort. R/R" value={formatNumber(p.avg_rr, { decimals: 2 })} testid="rep-avgrr" />
                <StatCard label="Toplam R" value={formatNumber(p.total_r, { decimals: 1, sign: true })} tone={p.total_r >= 0 ? "up" : "down"} testid="rep-totalr" />
                <StatCard label="En iyi / kötü" value={`${formatNumber(p.best, { decimals: 1, sign: true })}R`} sub={`${formatNumber(p.worst, { decimals: 1, sign: true })}R`} testid="rep-bestworst" />
              </div>

              <Panel title="İşlem geçmişi" testid="report-trades">
                {(!d.trades || d.trades.length === 0) ? (
                  <EmptyState text={TEXTS.empty.trades} />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-hairline text-left text-xs text-t-3">
                          <th className="pb-2 font-medium">Sembol</th>
                          <th className="pb-2 font-medium">Yön</th>
                          <th className="pb-2 text-right font-medium">Giriş</th>
                          <th className="pb-2 text-right font-medium">Çıkış</th>
                          <th className="pb-2 text-right font-medium">Sonuç (R)</th>
                          <th className="pb-2 text-right font-medium">Kapanış</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-hairline">
                        {d.trades.map((t) => (
                          <tr key={t.id} data-testid={`trade-${t.id}`}>
                            <td className="py-2.5 font-medium text-t-1">{t.symbol}</td>
                            <td className="py-2.5"><SideBadge side={t.side} /></td>
                            <td className="num py-2.5 text-right text-t-2">{formatPrice(t.entry)}</td>
                            <td className="num py-2.5 text-right text-t-2">{formatPrice(t.exit)}</td>
                            <td className={cn("num py-2.5 text-right font-semibold", t.r >= 0 ? "text-up" : "text-down")}>
                              {formatNumber(t.r, { decimals: 1, sign: true })}R
                            </td>
                            <td className="num py-2.5 text-right text-t-3 whitespace-nowrap">{formatTime(t.closed_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </div>
          );
        }}
      </DataView>
    </div>
  );
}
