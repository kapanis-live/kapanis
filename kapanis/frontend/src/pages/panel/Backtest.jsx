import { useState } from "react";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { sendAction } from "@/lib/actions";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, StatCard, Panel } from "@/components/DataView";
import { formatNumber, formatPct } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { useTheme } from "@/lib/theme";
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, CartesianGrid, Tooltip } from "recharts";

const TFS = ["15m", "1h", "4h", "1d"];

// Aynı motor: Telegram'daki /backtest. Sonuç birkaç saniye içinde aşağıdaki kartlara gelir.
function RunCard() {
  const [f, setF] = useState({ pair: "BTC", yon: "ABOVE", tetik: "", tf: "15m", iptal: "", hedef: "", gun: "180" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const run = async () => {
    const num = (v) => (String(v).trim() === "" ? null : U.parseTr(String(v)));
    const body = { ...f, pair: f.pair.trim().toUpperCase(), tetik: num(f.tetik), iptal: num(f.iptal), hedef: num(f.hedef), gun: parseInt(f.gun, 10) || 180 };
    if (!body.pair || !(body.tetik > 0)) return toast.error("Parite ve tetik fiyatı gerekli.");
    await sendAction("backtest.run", body, `${body.pair} backtest başlatıldı (kapanış bazlı).`);
  };
  return (
    <K.Card title="Yeni backtest (kripto, kapanış bazlı)">
      <div className="grid gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <K.Field label="Coin"><K.TextInput value={f.pair} onChange={set("pair")} placeholder="BTC" /></K.Field>
        <K.Field label="Yön"><K.Select value={f.yon} onChange={set("yon")} options={[{ value: "ABOVE", label: "Üstünde kapanış" }, { value: "BELOW", label: "Altında kapanış" }]} /></K.Field>
        <K.Field label="Tetik"><K.TextInput prefix="$" inputMode="decimal" value={f.tetik} onChange={set("tetik")} /></K.Field>
        <K.Field label="Mum"><K.Select value={f.tf} onChange={set("tf")} options={TFS} /></K.Field>
        <K.Field label="İptal" hint="boş = 1,5×ATR"><K.TextInput prefix="$" inputMode="decimal" value={f.iptal} onChange={set("iptal")} /></K.Field>
        <K.Field label="Hedef" hint="boş = 2×ATR"><K.TextInput prefix="$" inputMode="decimal" value={f.hedef} onChange={set("hedef")} /></K.Field>
        <K.Field label="Gün"><K.TextInput inputMode="numeric" value={f.gun} onChange={set("gun")} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={run}>Çalıştır</K.Button></div>
      </div>
      <p className="kp-note">Komisyon ve kayma düşülmüş net R ile hesaplanır. Geçmiş sonuç geleceği garanti etmez. Telegram: /backtest</p>
    </K.Card>
  );
}

export default function Backtest() {
  const q = useData("backtest", "/backtest");
  const { colors: c } = useTheme();
  return (
    <div>
      <PageHeader eyebrow="Performans / Backtest" title="Backtest" subtitle="Strateji simülasyonu ve performans metrikleri." testid="page-backtest" />
      <div className="mb-6"><RunCard /></div>
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
                      <CartesianGrid stroke={c.grid} vertical={false} />
                      <XAxis dataKey="i" tick={{ fill: c.axis, fontSize: 10 }} axisLine={{ stroke: c.grid }} tickLine={false} />
                      <YAxis tick={{ fill: c.axis, fontSize: 10 }} axisLine={false} tickLine={false} width={40} />
                      <Tooltip
                        contentStyle={{ background: c.tooltipBg, border: `1px solid ${c.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
                        labelStyle={{ color: c.text }}
                        formatter={(v) => [formatNumber(v, { decimals: 2 }) + "R", "Kümülatif"]}
                      />
                      <Line type="monotone" dataKey="v" stroke={c.brand} strokeWidth={2} dot={false} isAnimationActive={false} />
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
