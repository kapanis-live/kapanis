import { ComposedChart, Line, Area, ReferenceLine, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { formatPrice, formatTime } from "@/lib/format";
import { useTheme } from "@/lib/theme";

function ChartTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-md border border-hairline bg-surface px-3 py-2 text-xs shadow-lg">
      <div className="text-t-3 mb-1">{formatTime(p.t)}</div>
      <div className="num text-t-1">Kapanış: {formatPrice(p.c)}</div>
      <div className="num text-t-2">Y: {formatPrice(p.h)} · D: {formatPrice(p.l)}</div>
    </div>
  );
}

export function PriceChart({ data, sma20, sma50, sma200, height = 280 }) {
  const candles = data || [];
  const { colors: c } = useTheme();
  return (
    <div style={{ width: "100%", height }} data-testid="price-chart">
      <ResponsiveContainer>
        <ComposedChart data={candles} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
          <defs>
            <linearGradient id="closeFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={c.brand} stopOpacity={0.25} />
              <stop offset="100%" stopColor={c.brand} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={c.grid} vertical={false} />
          <XAxis dataKey="t" tickFormatter={(t) => formatTime(t).slice(0, 5)} tick={{ fill: c.axis, fontSize: 10 }} axisLine={{ stroke: c.grid }} tickLine={false} minTickGap={40} />
          <YAxis domain={["auto", "auto"]} tick={{ fill: c.axis, fontSize: 10 }} axisLine={false} tickLine={false} width={56} tickFormatter={(v) => formatPrice(v)} />
          <Tooltip content={<ChartTooltip />} />
          <Area type="monotone" dataKey="c" stroke={c.brand} strokeWidth={2} fill="url(#closeFill)" dot={false} isAnimationActive={false} />
          {sma20 != null && <ReferenceLine y={sma20} stroke={c.wait} strokeDasharray="4 3" strokeWidth={1} />}
          {sma50 != null && <ReferenceLine y={sma50} stroke={c.info} strokeDasharray="4 3" strokeWidth={1} />}
          {sma200 != null && <ReferenceLine y={sma200} stroke={c.violet} strokeDasharray="4 3" strokeWidth={1} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SmaLegend() {
  const { colors } = useTheme();
  const items = [
    { c: colors.wait, l: "SMA20" },
    { c: colors.info, l: "SMA50" },
    { c: colors.violet, l: "SMA200" },
  ];
  return (
    <div className="flex items-center gap-4 text-xs text-t-2">
      {items.map((i) => (
        <span key={i.l} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4" style={{ background: i.c }} />
          {i.l}
        </span>
      ))}
    </div>
  );
}
