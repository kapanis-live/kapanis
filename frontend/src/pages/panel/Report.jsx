import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { DataView, StatCard, Panel } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { SideBadge } from "@/components/bits";
import { formatNumber, formatPct, formatPrice, formatTime } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { cn } from "@/lib/utils";

function RuleBar({ n, pct, tone }) {
  return (
    <div className="ml-auto flex w-40 items-center justify-end gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-raised">
        <div className={cn("h-1.5 rounded-full", tone === "up" ? "bg-up" : "bg-down")} style={{ width: `${pct ?? 0}%` }} />
      </div>
      <span className="num w-20 text-right text-xs text-t-2">{pct ?? "—"}% · {n}</span>
    </div>
  );
}

export default function Report() {
  const q = useData("report", "/report");
  const extras = useData("extras", "/extras", LIVE);
  const advice = extras.data?.karne || [];
  return (
    <div>
      <PageHeader eyebrow="Performans / Rapor" title="Rapor & Kural Karnesi" subtitle="İşlem geçmişi, performans ve hangi kuralın gerçekten işe yaradığı." testid="page-report" />
      <DataView query={q} loadingText={TEXTS.loading.report}>
        {(d) => {
          const p = d.performance;
          return (
            <div className="space-y-6">
              <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
                <StatCard label="İşlem sayısı" value={formatNumber(p.count, { decimals: 0 })} testid="rep-count" />
                <StatCard label="İsabet oranı" value={formatPct(p.win_rate * 100, { sign: false })} tone="up" testid="rep-winrate" />
                <StatCard label="Ort. R/R" value={formatNumber(p.avg_rr, { decimals: 2 })} testid="rep-avgrr" />
                <StatCard label="Toplam R" value={formatNumber(p.total_r, { decimals: 1, sign: true })} tone={p.total_r >= 0 ? "up" : "down"} testid="rep-totalr" />
                <StatCard label="En iyi / kötü" value={`${formatNumber(p.best, { decimals: 1, sign: true })}R`} sub={`${formatNumber(p.worst, { decimals: 1, sign: true })}R`} testid="rep-bestworst" />
              </div>

              <Panel title="Kural etkinliği" testid="report-rule-stats">
                {(!d.rule_stats || d.rule_stats.length === 0) ? (
                  <EmptyState text="Henüz hedef/stopla sonuçlanan karar yok. Birkaç hafta birikince hangi kuralın işe yaradığı burada görünür." />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-hairline text-left text-xs text-t-3">
                          <th className="pb-2 font-medium">Kural</th>
                          <th className="pb-2 text-right font-medium">Geçtiğinde (karar · hedef %)</th>
                          <th className="pb-2 text-right font-medium">Kaldığında (karar · hedef %)</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-hairline">
                        {d.rule_stats.map((r) => (
                          <tr key={r.kural}>
                            <td className="py-2.5 font-medium text-t-1">{r.kural}</td>
                            <td className="py-2.5 text-right"><RuleBar n={r.gectiginde.n} pct={r.gectiginde.isabet_yuzde} tone="up" /></td>
                            <td className="py-2.5 text-right"><RuleBar n={r.kaldiginda.n} pct={r.kaldiginda.isabet_yuzde} tone="down" /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="mt-3 text-xs text-t-3">Sadece kapanışla hedefe ya da stopa gitmiş karar fişleri sayılır. 10 karardan az satırlar tesadüf olabilir.</p>
                  </div>
                )}
              </Panel>

              <Panel title="Kural karnesi önerileri" testid="report-advice">
                {!advice.length ? <p className="text-sm text-t-2">Öneri için kural başına en az 20 sonuçlanmış karar gerekiyor.</p>
                  : <ul className="space-y-2">{advice.map((x) => <li key={x} className="rounded-lg border border-hairline bg-raised/50 px-3 py-2 text-base text-t-1">{x}</li>)}</ul>}
              </Panel>

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
                            <td className="num py-2.5 text-right text-t-2">{formatPrice(t.entry)} {t.currency === "TL" ? "TL" : "USD"}</td>
                            <td className="num py-2.5 text-right text-t-2">{formatPrice(t.exit)} {t.currency === "TL" ? "TL" : "USD"}</td>
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
