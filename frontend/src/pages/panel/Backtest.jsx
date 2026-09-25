import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, StatCard, Panel } from "@/components/DataView";
import { formatNumber, formatPct } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, CartesianGrid, Tooltip } from "recharts";

export default function Backtest() {
  const q = useData("backtest", "/backtest");
  return (
    <div>
      <PageHeader title="Backtest" subtitle="Strateji simülasyonu ve performans metrikleri." testid="page-backtest" />
      <DataView query={q} loadingText={TEXTS.loading.backtest}>
        {(d) => {
          const m = d.metrics;
          const curve = d.equity_curve.map((v, i) => ({ i, v }));
          return (
            <div className="space-y-6">
              <Panel testid="backtest-meta">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <div className="text-sm font-semibold text-t-1">{d.strategy}</div>
                    <div className="text-xs text-t-3">{d.period}</div>
                  </div>
                </div>
              </Panel>

              <div className="grid gap-3 grid-cols-2 lg:grid-cols-3">
                <StatCard label="İşlem" value={formatNumber(m.trades, { decimals: 0 })} testid="bt-trades" />
                <StatCard label="Kazanma oranı" value={formatPct(m.win_rate * 100, { sign: false })} tone="up" testid="bt-winrate" />
                <StatCard label="Profit factor" value={formatNumber(m.profit_factor, { decimals: 2 })} testid="bt-pf" />
                <StatCard label="Beklenti (R)" value={formatNumber(m.expectancy_r, { decimals: 2, sign: true })} tone={m.expectancy_r >= 0 ? "up" : "down"} testid="bt-exp" />
                <StatCard label="Maks. düşüş (R)" value={formatNumber(m.max_drawdown_r, { decimals: 1 })} tone="down" testid="bt-dd" />
                <StatCard label="Sharpe" value={formatNumber(m.sharpe, { decimals: 2 })} testid="bt-sharpe" />
              </div>

              <Panel title="Kümülatif R (equity curve)" testid="backtest-curve">
                <div style={{ width: "100%", height: 260 }}>
                  <ResponsiveContainer>
                    <LineChart data={curve} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
                      <CartesianGrid stroke="#1F1F1F" vertical={false} />
                      <XAxis dataKey="i" tick={{ fill: "#555555", fontSize: 10 }} axisLine={{ stroke: "#1F1F1F" }} tickLine={false} />
                      <YAxis tick={{ fill: "#555555", fontSize: 10 }} axisLine={false} tickLine={false} width={40} />
                      <Tooltip
                        contentStyle={{ background: "#0A0A0A", border: "1px solid #1F1F1F", borderRadius: 8, fontSize: 12 }}
                        labelStyle={{ color: "#8A8A8A" }}
                        formatter={(v) => [formatNumber(v, { decimals: 2 }) + "R", "Kümülatif"]}
                      />
                      <Line type="monotone" dataKey="v" stroke="#26A69A" strokeWidth={2} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </Panel>

              <p className="text-xs leading-relaxed text-t-3">{d.note}</p>
            </div>
          );
        }}
      </DataView>
    </div>
  );
}
