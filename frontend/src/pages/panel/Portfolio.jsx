import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AssetLogo, chartHref } from "@/components/AssetLogo";
import { PieChart as RPieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { DataView, StatCard, Panel } from "@/components/DataView";
import { PctBadge, DeltaText, MarketTag } from "@/components/bits";
import { Segmented } from "@/components/kp";
import { EmptyState } from "@/components/states";
import { formatNumber, formatPct, formatTime } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import { MARKET_LABEL, MARKET_ORDER, MARKET_TONE, px, qty, money, dayLabel, marketTotals } from "@/lib/portfolio";
import { cn } from "@/lib/utils";
import { AlertTriangle, Scale } from "lucide-react";

function MarketCards({ totals }) {
  const entries = MARKET_ORDER.filter((m) => totals[m]).map((m) => [m, totals[m]]);
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {entries.map(([m, t]) => (
        <div key={m} className={cn("card-shine rounded-xl border border-hairline bg-surface p-4 bg-gradient-to-b to-transparent",
          t.kz >= 0 ? "from-up/[0.07]" : "from-down/[0.07]")} data-testid={`pf-market-${m}`}>
          <div className="flex items-center justify-between text-xs font-semibold text-t-2">
            <MarketTag m={m} />
            <span className="text-t-3">{t.adet} varlık</span>
          </div>
          <div className="num mt-3 text-[28px] font-semibold tracking-tight text-t-1">{money(t.deger, t.para)}</div>
          <div className="mt-3 space-y-1.5 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-t-2">{dayLabel(m)}</span>
              <span className="flex items-center gap-2">
                <DeltaText value={t.gun} suffix="" arrow={false} className="text-xs" />
                <PctBadge value={t.gun_yuzde} />
              </span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-t-2">Toplam</span>
              <span className="flex items-center gap-2">
                <DeltaText value={t.kz} suffix="" arrow={false} className="text-xs" />
                <PctBadge value={t.kz_yuzde} />
              </span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Donut({ rows, currency }) {
  const { colors } = useTheme();
  const palette = [colors.brand, colors.wait, colors.info, colors.violet, colors.up, colors.down, colors.axis];
  const data = [...rows].sort((a, b) => b.deger - a.deger);
  const total = data.reduce((s, r) => s + r.deger, 0);
  const top = data.slice(0, 6);
  const rest = data.slice(6).reduce((s, r) => s + r.deger, 0);
  const slices = [...top.map((r) => ({ name: r.ad, value: r.deger })), ...(rest ? [{ name: "Diğer", value: rest }] : [])];
  return (
    <div>
      <div className="relative h-44">
        <ResponsiveContainer>
          <RPieChart>
            <Pie data={slices} dataKey="value" innerRadius="62%" outerRadius="92%" paddingAngle={2} stroke="none" isAnimationActive={false}>
              {slices.map((s, i) => <Cell key={s.name} fill={palette[i % palette.length]} />)}
            </Pie>
            <Tooltip
              formatter={(v, n) => [`${money(v, currency)} · ${formatPct((v / total) * 100, { sign: false, decimals: 1 })}`, n]}
              contentStyle={{ background: colors.tooltipBg, border: `1px solid ${colors.tooltipBorder}`, borderRadius: 8, fontSize: 12 }}
              itemStyle={{ color: colors.line }}
            />
          </RPieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
          <div>
            <div className="num text-base font-semibold text-t-1">{formatNumber(total, { decimals: 0 })}</div>
            <div className="text-[11px] text-t-3">{currency}</div>
          </div>
        </div>
      </div>
      <ul className="mt-3 space-y-1.5 text-sm">
        {slices.map((s, i) => (
          <li key={s.name} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-t-1">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: palette[i % palette.length] }} />{s.name}
            </span>
            <span className="num text-t-2">{formatPct((s.value / total) * 100, { sign: false, decimals: 1 })}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function HoldingsTable({ rows }) {
  const navigate = useNavigate();
  const has = (k) => rows.some((g) => g[k] !== null && g[k] !== undefined && g[k] !== 0);
  const showFx = rows.some((g) => (g.para === "USD" ? g.tl_yuzde : g.usd_yuzde) != null);
  const showReal = has("reel_yuzde");
  const showDiv = has("temettu");
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full whitespace-nowrap text-[1.0625rem]">
          <thead className="text-left text-sm font-semibold text-t-3">
            <tr className="border-b border-hairline">
              <th className="py-2.5 pl-5 pr-3 font-semibold">Varlık</th>
              <th className="pr-3 text-right font-semibold">Adet</th>
              <th className="pr-3 text-right font-semibold">Ort. maliyet</th>
              <th className="pr-3 text-right font-semibold">Fiyat</th>
              <th className="pr-3 text-right font-semibold">Değer</th>
              <th className="pr-3 text-right font-semibold">Günlük</th>
              <th className="pr-3 text-right font-semibold">Toplam</th>
              <th className="pr-3 text-right font-semibold">K/Z</th>
              {showFx && <th className="pr-3 text-right font-semibold" title="TL varlıkta dolar bazında, dolar varlıkta TL bazında getiri">$ / TL</th>}
              {showReal && <th className="pr-3 text-right font-semibold" title="Enflasyondan arındırılmış">Reel</th>}
              {showDiv && <th className="pr-5 text-right font-semibold">Temettü</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <tr key={g.piyasa + g.ad} onClick={() => navigate(chartHref(g.ad, g.piyasa))} title="Grafiği aç"
                className="h-16 cursor-pointer border-b border-hairline transition-colors duration-150 last:border-0 hover:bg-raised">
                <td className="pl-5 pr-3">
                  <span className="flex items-center gap-3">
                    <AssetLogo code={g.ad.split("/")[0]} market={g.piyasa} size={34} />
                    <span>
                      <span className="block text-lg font-bold leading-tight text-t-1">{g.ad}</span>
                      <MarketTag m={g.piyasa} className="text-xs text-t-3" />
                    </span>
                  </span>
                </td>
                <td className="num pr-3 text-right text-t-1">{qty(g.adet)}</td>
                <td className="num pr-3 text-right text-t-2">{px(g.adet ? g.maliyet / g.adet : null)}</td>
                <td className="num pr-3 text-right text-t-1">{px(g.fiyat)}</td>
                <td className="num pr-3 text-right font-bold text-t-1">{money(g.deger, g.para)}</td>
                <td className="pr-3 text-right"><PctBadge value={g.gun_yuzde} /></td>
                <td className="pr-3 text-right"><PctBadge value={g.toplam_yuzde} /></td>
                <td className="pr-3 text-right"><DeltaText value={g.deger - g.maliyet} suffix="" arrow={false} /></td>
                {showFx && <td className="pr-3 text-right"><DeltaText value={g.para === "USD" ? g.tl_yuzde : g.usd_yuzde} arrow={false} /></td>}
                {showReal && <td className="pr-3 text-right"><DeltaText value={g.reel_yuzde} arrow={false} /></td>}
                {showDiv && <td className="num pr-5 text-right text-t-2">{g.temettu ? money(g.temettu, "TL") : "—"}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="divide-y divide-hairline md:hidden">
        {rows.map((g) => (
          <div key={g.piyasa + g.ad} className="cursor-pointer p-4" onClick={() => navigate(chartHref(g.ad, g.piyasa))}>
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <AssetLogo code={g.ad.split("/")[0]} market={g.piyasa} size={32} />
                <div>
                <div className="text-lg font-bold text-t-1">{g.ad}</div>
                <div className="text-xs text-t-3">{MARKET_LABEL[g.piyasa]} · {qty(g.adet)} adet · ort. {px(g.adet ? g.maliyet / g.adet : null)}</div>
                </div>
              </div>
              <div className="num text-right font-semibold text-t-1">{money(g.deger, g.para)}</div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-t-2">
              {dayLabel(g.piyasa)} <PctBadge value={g.gun_yuzde} />
              <span className="ml-1">Toplam</span> <PctBadge value={g.toplam_yuzde} />
              <DeltaText value={g.deger - g.maliyet} suffix="" arrow={false} className="text-xs" />
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export default function Portfolio() {
  const q = useData("extras", "/extras", LIVE);
  const [tab, setTab] = useState("TUMU");
  return (
    <div>
      <PageHeader title="Portföy"
        subtitle="Adet, maliyet, günlük ve toplam getiri. Rakamları bot kodla hesaplar, 15 dakikada bir günceller." testid="page-portfolio" />
      <DataView query={q} loadingText="Portföy verisi yükleniyor...">
        {(d) => {
          if (!d.guncelleme) return <EmptyState text="Bot henüz portföy verisini göndermedi (15 dakikada bir gönderir)." />;
          const all = d.portfoy || [];
          if (!all.length) return <EmptyState text="Portföy boş. Telegram'da ekle: /portfoy veya düz yazıyla “astordan 4 tane 260 TL'den aldım”." />;
          const totals = marketTotals(all);
          const markets = MARKET_ORDER.filter((m) => totals[m]);
          const rows = tab === "TUMU" ? all : all.filter((g) => g.piyasa === tab);
          const byCurrency = rows.reduce((acc, g) => ((acc[g.para] ||= []).push(g), acc), {});
          return (
            <div className="space-y-6">
              <MarketCards totals={totals} />

              <div className="flex flex-wrap items-center justify-between gap-3">
                <Segmented ariaLabel="Piyasa" value={tab} onChange={setTab}
                  options={[{ value: "TUMU", label: "Tümü" }, ...markets.map((m) => ({ value: m, label: MARKET_LABEL[m] }))]} />
                <span className="text-sm text-t-3">Güncelleme {formatTime(d.guncelleme)} · rakamları bot kodla hesaplar</span>
              </div>

              <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
                <Panel title="Varlıklar" testid="pf-table" bodyClass="p-0" className="min-w-0"
                  action={<span className="text-xs text-t-3">{rows.length} varlık</span>}>
                  <HoldingsTable rows={rows} />
                </Panel>
                <div className="space-y-6">
                  <Panel title="Dağılım" testid="pf-donut">
                    <div className="space-y-6">
                      {Object.entries(byCurrency).map(([cur, rs]) => <Donut key={cur} rows={rs} currency={cur} />)}
                    </div>
                  </Panel>
                  {(d.yogunlasma?.uyarilar || []).length > 0 && (
                    <div className="rounded-xl border border-wait/40 bg-wait/[0.08] p-4" data-testid="pf-concentration">
                      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-wait"><AlertTriangle className="h-4 w-4" /> Yoğunlaşma</div>
                      {d.yogunlasma.uyarilar.map((w) => <p key={w} className="text-base text-t-1">{w}</p>)}
                      <p className="mt-2 text-xs text-t-2">Bu bir uyarıdır; bot otomatik işlem önermez. Ayrıntı: /risk</p>
                    </div>
                  )}
                </div>
              </div>

              <Panel title="Kıyas (TL, aynı tarihlerde)" testid="pf-benchmark" action={<Scale className="h-4 w-4 text-t-3" />}>
                {!d.kiyas?.kiyas ? <p className="text-sm text-t-2">Kıyas için alış tarihi girilmiş açık pozisyon gerekli (/duzelt ID tarih=2025-03-01).</p> : (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <StatCard label="Senin portföyün" value={formatPct(d.kiyas.portfoy_yuzde)} tone={d.kiyas.portfoy_yuzde >= 0 ? "up" : "down"} />
                    {d.kiyas.kiyas.map((b) => (
                      <StatCard key={b.ad} label={b.ad} value={formatPct(b.yuzde)}
                        sub={b.not || (b.fark === null || b.fark === undefined ? "" : b.fark > 0 ? `yendin (+${formatNumber(b.fark, { decimals: 1 })} puan)` : `geride (${formatNumber(b.fark, { decimals: 1 })} puan)`)}
                        tone={b.fark > 0 ? "up" : b.fark < 0 ? "down" : undefined} />
                    ))}
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
