import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, Panel } from "@/components/DataView";
import { StaleBadge } from "@/components/bits";
import { formatNumber, formatTime, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/states";
import { TEXTS } from "@/lib/texts";

// -5…+5 rejim skalası
export function RegimeScale({ score, label }) {
  const clamped = Math.max(-5, Math.min(5, score));
  const pct = ((clamped + 5) / 10) * 100;
  const tone = clamped > 0 ? "text-up" : clamped < 0 ? "text-down" : "text-t-1";
  return (
    <div data-testid="regime-scale">
      <div className="flex items-end justify-between">
        <div className={cn("num text-3xl font-bold", tone)}>{score > 0 ? "+" : ""}{score}</div>
        <div className="text-right">
          <div className="text-sm font-medium text-t-1">{label}</div>
          <div className="text-xs text-t-3">-5 … +5 skalası</div>
        </div>
      </div>
      <div className="relative mt-3 h-2 rounded-full bg-ink border border-hairline overflow-hidden">
        <div className="absolute inset-y-0 left-1/2 w-px bg-t-3" />
        <div
          className={cn("absolute top-1/2 h-3.5 w-3.5 -translate-y-1/2 -translate-x-1/2 rounded-full border-2 border-black", clamped >= 0 ? "bg-up" : "bg-down")}
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-t-3">
        <span>Risk-kaçışı</span><span>Nötr</span><span>Risk-iştahı</span>
      </div>
    </div>
  );
}

const IMP = { high: "bg-down/15 text-down", medium: "bg-wait/15 text-wait", low: "bg-t-3/20 text-t-2" };
const IMP_LABEL = { high: "Yüksek", medium: "Orta", low: "Düşük" };

export default function Macro() {
  const q = useData("macro", "/macro");
  return (
    <div>
      <PageHeader eyebrow="Piyasa / Makro" title="Makro" subtitle="Rejim skalası, alt dolar endeksi ve ekonomik takvim." testid="page-macro" />
      <DataView query={q} loadingText={TEXTS.loading.macro}>
        {(d) => (
          <div className="space-y-6">
            <div className="grid gap-6 lg:grid-cols-3">
              <Panel title="Rejim skalası" testid="macro-regime" action={d.stale ? <StaleBadge /> : <span className="text-xs text-t-3">Güncel · {relativeTime(d.updated_at)}</span>}>
                <RegimeScale score={d.regime_score} label={d.regime_label} />
              </Panel>

              <Panel title="Dolar endeksi (alt)" testid="macro-dxy">
                <div className="flex items-center gap-2">
                  <span className="num text-2xl font-bold text-t-1">{formatNumber(d.dxy_alt.value)}</span>
                  <span className="inline-flex items-center rounded bg-info/12 px-1.5 py-0.5 text-xs font-medium text-info" data-testid="dxy-alt-tag">
                    {d.dxy_alt.label}
                  </span>
                </div>
                <p className="mt-3 text-xs leading-relaxed text-t-2">
                  Bu endeks standart DXY değildir; likidite ağırlıklı, farklı bir hesaplama kullanır. Skor katkısı:{" "}
                  <span className={cn("num font-semibold", d.dxy_alt.score >= 0 ? "text-up" : "text-down")}>
                    {d.dxy_alt.score > 0 ? "+" : ""}{d.dxy_alt.score}
                  </span>
                </p>
              </Panel>

              <Panel title="Rejim bileşenleri" testid="macro-components">
                <ul className="space-y-2.5">
                  {d.components.map((c) => (
                    <li key={c.name} className="flex items-center justify-between text-sm">
                      <span className="text-t-2">{c.name}</span>
                      <span className="flex items-center gap-2">
                        <span className="text-t-1">{c.value}</span>
                        <span className={cn("num w-7 text-right text-xs font-semibold", c.score > 0 ? "text-up" : c.score < 0 ? "text-down" : "text-t-3")}>
                          {c.score > 0 ? "+" : ""}{c.score}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>

            <Panel title="Ekonomik takvim" testid="macro-calendar">
              {(!d.calendar || d.calendar.length === 0) ? (
                <EmptyState text={TEXTS.empty.calendar} />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-hairline text-left text-xs text-t-3">
                        <th className="pb-2 font-medium">Zaman</th>
                        <th className="pb-2 font-medium">Olay</th>
                        <th className="pb-2 font-medium">Ülke</th>
                        <th className="pb-2 font-medium">Önem</th>
                        <th className="pb-2 text-right font-medium">Beklenti</th>
                        <th className="pb-2 text-right font-medium">Önceki</th>
                        <th className="pb-2 text-right font-medium">Açıklanan</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-hairline">
                      {d.calendar.map((e, i) => (
                        <tr key={i} className="text-t-1" data-testid={`calendar-row-${i}`}>
                          <td className="num py-2.5 text-t-2 whitespace-nowrap">{formatTime(e.time)}</td>
                          <td className="py-2.5">{e.title}</td>
                          <td className="py-2.5 text-t-2">{e.country}</td>
                          <td className="py-2.5">
                            <span className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium", IMP[e.importance])}>
                              {IMP_LABEL[e.importance]}
                            </span>
                          </td>
                          <td className="num py-2.5 text-right text-t-2">{e.forecast ?? "—"}</td>
                          <td className="num py-2.5 text-right text-t-2">{e.previous ?? "—"}</td>
                          <td className="num py-2.5 text-right font-medium">{e.actual ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>

            <p className="text-xs leading-relaxed text-t-3">{d.note}</p>
          </div>
        )}
      </DataView>
    </div>
  );
}
