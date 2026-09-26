import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, StatCard, Panel } from "@/components/DataView";
import { formatCurrency, formatCompact, formatNumber } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { cn } from "@/lib/utils";

export default function Cost() {
  const q = useData("usage", "/usage");
  return (
    <div>
      <PageHeader eyebrow="Sistem / Maliyet" title="Yapay zekâ maliyeti" subtitle="Yapay zekâ çağrılarının maliyeti ve 24 saatlik tarife şeridi." testid="page-cost" />
      <DataView query={q} loadingText={TEXTS.loading.usage}>
        {(d) => {
          const maxCost = Math.max(...d.hourly.map((h) => h.cost), 0.000001);
          return (
            <div className="space-y-6">
              <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
                <StatCard label="Bugünkü maliyet" value={formatCurrency(d.total_cost, 3)} sub={d.usd_try ? `≈ ${formatNumber(d.total_cost * d.usd_try, { decimals: 2 })} TL` : undefined} testid="cost-total" />
                <StatCard label="Çağrı" value={formatNumber(d.calls, { decimals: 0 })} testid="cost-calls" />
                <StatCard label="Girdi token" value={formatCompact(d.tokens_in)} testid="cost-tokens-in" />
                <StatCard label="Çıktı token" value={formatCompact(d.tokens_out)} testid="cost-tokens-out" />
              </div>

              {/* 24 saatlik tarife şeridi */}
              <Panel title="24 saatlik tarife şeridi" testid="tariff-strip"
                action={
                  <div className="flex items-center gap-3 text-xs text-t-2">
                    <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-wait/60" /> Yüksek</span>
                    <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-info/50" /> Düşük</span>
                  </div>
                }>
                <div className="flex gap-0.5" data-testid="tariff-cells">
                  {d.tariff.map((t) => (
                    <div key={t.hour} className="group relative flex-1" data-testid={`tariff-${t.hour}`}>
                      <div className={cn("h-8 rounded-sm", t.tier === "yüksek" ? "bg-wait/60" : "bg-info/50")} title={`${t.hour}:00 · ${t.tier} · output ${formatCurrency(t.rate, 2)}/1M token`} />
                      {t.hour % 3 === 0 && <div className="num mt-1 text-center text-[9px] text-t-3">{t.hour}</div>}
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-xs text-t-3">DeepSeek yoğun tarifesi (2× fiyat): hafta içi TR 04:00–07:00 ve 09:00–13:00. Diğer saatler ve hafta sonu indirimli.</p>
              </Panel>

              {/* Saatlik maliyet */}
              <Panel title="Saatlik maliyet" testid="hourly-cost">
                <div className="flex items-end gap-1" style={{ height: 160 }}>
                  {d.hourly.map((h) => (
                    <div key={h.hour} className="group relative flex flex-1 flex-col items-center justify-end">
                      <div
                        className={cn("w-full rounded-t-sm transition-colors duration-150",
                          h.cost > 0 ? "bg-brand/60 group-hover:bg-brand" : "bg-raised")}
                        style={{ height: `${Math.max(4, (h.cost / maxCost) * 140)}px` }}
                        title={`${h.hour}:00 · ${formatCurrency(h.cost, 3)} · ${h.calls} çağrı`}
                      />
                      {h.hour % 3 === 0 && <div className="num mt-1 text-[9px] text-t-3">{h.hour}</div>}
                    </div>
                  ))}
                </div>
              </Panel>
            </div>
          );
        }}
      </DataView>
    </div>
  );
}
