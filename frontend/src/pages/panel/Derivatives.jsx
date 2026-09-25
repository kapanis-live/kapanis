import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, Panel } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { formatNumber, formatCompact, formatPct, relativeTime } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { cn } from "@/lib/utils";

function CotBar({ pct }) {
  const tone = pct >= 90 ? "bg-down" : pct >= 70 ? "bg-wait" : "bg-info";
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-t-2">COT yüzdeliği</span>
        <span className={cn("num font-semibold", pct >= 90 ? "text-down" : pct >= 70 ? "text-wait" : "text-info")}>%{pct}</span>
      </div>
      <div className="mt-1.5 h-2 rounded-full bg-black border border-hairline overflow-hidden">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
      </div>
      {pct >= 90 && <p className="mt-1.5 text-xs text-down">Aşırı uç bölge — pozisyonlanma kalabalık.</p>}
    </div>
  );
}

export default function Derivatives() {
  const q = useData("derivatives", "/derivatives");
  return (
    <div>
      <PageHeader title="Vadeli" subtitle="Funding, açık pozisyon, long/short oranı ve COT yüzdeliği." testid="page-derivatives" />
      <DataView query={q} loadingText={TEXTS.loading.derivatives}>
        {(list) =>
          !list || list.length === 0 ? (
            <EmptyState text={TEXTS.empty.generic} />
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {list.map((d) => (
                <Panel key={d.id} title={d.symbol} testid={`derivative-${d.id}`}
                  action={<span className="text-xs text-t-3">{relativeTime(d.updated_at)}</span>}>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                    <div>
                      <div className="text-xs text-t-3">Funding</div>
                      <div className={cn("num text-lg font-bold", d.funding_rate >= 0 ? "text-up" : "text-down")}>
                        {formatPct(d.funding_rate, { decimals: 4 })}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-t-3">Açık pozisyon (OI)</div>
                      <div className="num text-lg font-bold text-t-1">${formatCompact(d.open_interest)}</div>
                    </div>
                    <div>
                      <div className="text-xs text-t-3">Long/Short oranı</div>
                      <div className={cn("num text-lg font-bold", d.long_short_ratio >= 1 ? "text-up" : "text-down")}>
                        {formatNumber(d.long_short_ratio, { decimals: 2 })}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-t-3">Baz (basis)</div>
                      <div className="num text-lg font-bold text-t-1">{formatPct(d.basis, { decimals: 2, sign: false })}</div>
                    </div>
                  </div>
                  <div className="mt-4 border-t border-hairline pt-4">
                    <CotBar pct={d.cot_percentile} />
                  </div>
                </Panel>
              ))}
            </div>
          )
        }
      </DataView>
    </div>
  );
}
