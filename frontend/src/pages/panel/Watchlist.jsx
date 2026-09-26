import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { AssetLogo, chartHref } from "@/components/AssetLogo";
import { Segmented, Chip, SearchField, KButton, ChangeBadge, Trend, RsiMeter, RangeBar } from "@/components/kp";
import { formatPct, formatTime } from "@/lib/format";
import { MARKET_LABEL, px, baseCode } from "@/lib/portfolio";
import { cn } from "@/lib/utils";
import { Copy, Plus } from "lucide-react";

const MARKETS = ["KRIPTO", "BIST", "ABD"];
const UNIT = { KRIPTO: "$", BIST: "₺", ABD: "$" };
const SORTS = [
  ["liste", "Liste sırası"], ["gun_up", "Günlük: en çok yükselen"], ["gun_down", "Günlük: en çok düşen"],
  ["hafta_up", "Haftalık: en çok yükselen"], ["hafta_down", "Haftalık: en çok düşen"],
  ["rsi_down", "RSI: yüksekten düşüğe"], ["rsi_up", "RSI: düşükten yükseğe"], ["destek", "Desteğe en yakın"],
];
// [değer, yön]: -1 büyükten küçüğe, 1 küçükten büyüğe. Değeri olmayanlar sona.
const SORT_KEYS = {
  gun_up: [(r) => r.gun_yuzde, -1], gun_down: [(r) => r.gun_yuzde, 1],
  hafta_up: [(r) => r.hafta_yuzde, -1], hafta_down: [(r) => r.hafta_yuzde, 1],
  rsi_down: [(r) => r.rsi, -1], rsi_up: [(r) => r.rsi, 1],
  destek: [(r) => r.destek_yuzde, -1], // destek_yuzde negatif: sıfıra en yakın = desteğe en yakın
};
const FILTERS = {
  guclu: { label: "↗ Güçlü trend", test: (r) => r.trend?.startsWith("↗") },
  zayif: { label: "↘ Zayıf", test: (r) => r.trend?.startsWith("↘") },
  isinmis: { label: "Isınmış (RSI > 70)", test: (r) => r.rsi != null && r.rsi > 70 },
  satilmis: { label: "Çok satılmış (RSI < 30)", test: (r) => r.rsi != null && r.rsi < 30 },
  yakin: { label: "Desteğe %2'den yakın", test: (r) => r.destek_yuzde != null && r.destek_yuzde >= -2 },
  elimde: { label: "Portföyümde", test: (r, held) => held.has(r.kod) },
};

function sortRows(rows, sort) {
  if (!SORT_KEYS[sort]) return rows;
  const [val, dir] = SORT_KEYS[sort];
  return [...rows].sort((a, b) => {
    const x = val(a), y = val(b);
    if (x == null) return 1;
    if (y == null) return -1;
    return dir * (x - y);
  });
}

async function copy(text, what) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} kopyalandı`, { description: `${text} — Telegram'da bota yapıştır.` });
  } catch {
    toast.error("Kopyalanamadı", { description: text });
  }
}

function HeldTag() {
  return <span className="rounded-md bg-brand/15 px-1.5 py-0.5 text-xs font-semibold text-brand">Portföyde</span>;
}

export default function Watchlist() {
  const q = useData("extras", "/extras", LIVE);
  const navigate = useNavigate();
  const [tab, setTab] = useState("KRIPTO");
  const [sort, setSort] = useState("liste");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState([]);
  const [picked, setPicked] = useState([]);
  const toggleFilter = (k) => setFilters((f) => (f.includes(k) ? f.filter((x) => x !== k) : [...f, k]));
  const togglePick = (k) => setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k]));
  const held = useMemo(() => new Set((q.data?.portfoy || []).map((g) => baseCode(g.ad))), [q.data]);
  const open = (kod) => navigate(chartHref(kod, tab));

  return (
    <div>
      <PageHeader title="Takip listesi" testid="page-watchlist"
        subtitle="İzlediğin kodların kodla hesaplanmış hızlı durumu. Satıra tıkla, grafiği açılsın."
        action={<KButton icon={<Plus className="h-4 w-4" />} onClick={() => copy("/takip ekle ", "Ekleme komutu")}>Kod ekle</KButton>} />
      <DataView query={q} loadingText="Takip listesi yükleniyor...">
        {(d) => {
          const tl = d.takip_listesi;
          if (!tl?.piyasalar) return <EmptyState text="Bot takip listesi verisini henüz göndermedi (30 dakikada bir yeniler). Telegram: /takip" />;
          const all = tl.piyasalar[tab] || [];
          const ok = all.filter((r) => !r.hata);
          const ups = ok.filter((r) => (r.gun_yuzde || 0) > 0).length;
          let rows = all.filter((r) => r.kod.includes(search.trim().toUpperCase()));
          rows = rows.filter((r) => (r.hata ? filters.length === 0 : filters.every((f) => FILTERS[f].test(r, held))));
          rows = sortRows(rows, sort);
          return (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <Segmented ariaLabel="Piyasa" value={tab} onChange={(m) => { setTab(m); setPicked([]); }}
                  options={MARKETS.map((m) => ({ value: m, label: `${MARKET_LABEL[m]} ${(tl.piyasalar[m] || []).length}` }))} />
                <SearchField value={search} onChange={setSearch} />
                <label className="inline-flex h-11 items-center rounded-[10px] border border-hairline bg-ink px-3">
                  <span className="sr-only">Sıralama</span>
                  <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sıralama"
                    className="bg-transparent text-base font-semibold text-t-1 outline-none">
                    {SORTS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(FILTERS).map(([k, f]) => (
                  <Chip key={k} active={filters.includes(k)} onClick={() => toggleFilter(k)}>{f.label}</Chip>
                ))}
              </div>
              <p className="m-0 text-[0.9375rem] text-t-2">
                <b className="num text-up">{ups}</b>/<b className="num text-t-1">{ok.length}</b> yükselişte ·{" "}
                {tab === "KRIPTO" ? "günlük = 24 saatlik değişim" : "günlük = son seans"}{tab === "BIST" ? " · veri ~15 dk gecikmeli" : ""} ·{" "}
                <span className="text-t-3">güncelleme {formatTime(new Date(tl.zaman * 1000).toISOString())}, 30 dakikada bir</span>
              </p>

              {!rows.length ? <EmptyState text="Bu filtrelere uyan kod yok." /> : (
                <>
                  <div className="hidden overflow-x-auto rounded-xl border border-hairline bg-surface md:block" data-testid="wl-table">
                    <table className="w-full border-collapse text-[1.0625rem]">
                      <thead>
                        <tr>
                          {["", "Kod", "Fiyat", "Günlük", "Haftalık", "Trend", "RSI", "Destek → Direnç"].map((h, i) => (
                            <th key={h + i} className={cn("h-12 whitespace-nowrap border-b border-hairline px-3 text-left text-sm font-semibold text-t-3", [2, 3, 4].includes(i) && "text-right", i === 0 && "w-12")}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => r.hata ? (
                          <tr key={r.kod} className="border-b border-hairline last:border-0">
                            <td className="h-16 pl-4 pr-2" />
                            <td className="px-4 font-bold">{r.kod}</td>
                            <td colSpan={6} className="px-4 text-t-3">veri alınamadı</td>
                          </tr>
                        ) : (
                          <tr key={r.kod} tabIndex={0} onClick={() => open(r.kod)} onKeyDown={(e) => e.key === "Enter" && open(r.kod)}
                            className={cn("cursor-pointer border-b border-hairline transition-colors duration-150 last:border-0 hover:bg-raised",
                              picked.includes(r.kod) && "bg-brand/[0.07]")}>
                            <td className="h-16 pl-4 pr-2">
                              <input type="checkbox" checked={picked.includes(r.kod)} onChange={() => togglePick(r.kod)} onClick={(e) => e.stopPropagation()}
                                aria-label={`${r.kod} seç`} className="h-[1.125rem] w-[1.125rem] cursor-pointer" style={{ accentColor: "rgb(var(--c-brand))" }} />
                            </td>
                            <td className="whitespace-nowrap px-3">
                              <span className="inline-flex items-center gap-3">
                                <AssetLogo code={r.kod} market={tab} />
                                <span className="text-lg font-bold tracking-[0.01em] text-t-1">{r.kod}</span>
                                {held.has(r.kod) && <HeldTag />}
                              </span>
                            </td>
                            <td className="num whitespace-nowrap px-3 text-right text-lg font-bold text-t-1">{px(r.fiyat)} <span className="text-base font-semibold text-t-3">{UNIT[tab]}</span></td>
                            <td className="px-3 text-right"><ChangeBadge value={r.gun_yuzde} /></td>
                            <td className="px-3 text-right"><ChangeBadge value={r.hafta_yuzde} decimals={1} /></td>
                            <td className="whitespace-nowrap px-3"><Trend label={r.trend} /></td>
                            <td className="px-3"><RsiMeter value={r.rsi} /></td>
                            <td className="px-3"><RangeBar support={r.destek} supportPct={r.destek_yuzde} resistance={r.direnc} resistancePct={r.direnc_yuzde} price={r.fiyat} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="divide-y divide-hairline rounded-xl border border-hairline bg-surface md:hidden" data-testid="wl-cards">
                    {rows.map((r) => (
                      <div key={r.kod} className={cn("p-4", picked.includes(r.kod) && "bg-brand/[0.07]")}>
                        <div className="flex items-center justify-between gap-3">
                          <span className="flex items-center gap-3">
                            {!r.hata && <input type="checkbox" checked={picked.includes(r.kod)} onChange={() => togglePick(r.kod)}
                              aria-label={`${r.kod} seç`} className="h-[1.125rem] w-[1.125rem]" style={{ accentColor: "rgb(var(--c-brand))" }} />}
                            <button onClick={() => !r.hata && open(r.kod)} className="flex items-center gap-3 text-left">
                              <AssetLogo code={r.kod} market={tab} />
                              <span className="text-lg font-bold text-t-1">{r.kod}</span>
                            </button>
                            {held.has(r.kod) && <HeldTag />}
                          </span>
                          {r.hata ? <span className="text-sm text-t-3">veri alınamadı</span> : (
                            <span className="num text-lg font-bold text-t-1">{px(r.fiyat)} <span className="text-base text-t-3">{UNIT[tab]}</span></span>
                          )}
                        </div>
                        {!r.hata && (
                          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
                            <ChangeBadge value={r.gun_yuzde} label="Gün" />
                            <ChangeBadge value={r.hafta_yuzde} decimals={1} label="Hafta" />
                            <Trend label={r.trend} />
                            <RsiMeter value={r.rsi} />
                            <span className="num text-[0.9375rem] text-t-2">
                              {r.destek != null ? `${px(r.destek)} (${formatPct(r.destek_yuzde, { decimals: 1 })})` : "—"} <span className="text-t-3">→</span>{" "}
                              {r.direnc != null ? `${px(r.direnc)} (${formatPct(r.direnc_yuzde, { decimals: 1 })})` : "—"}
                            </span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}

              {picked.length > 0 && (
                <div className="sticky bottom-20 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-strong bg-surface p-4 lg:bottom-4">
                  <span className="text-base text-t-1"><b>{picked.length}</b> kod seçili: <span className="text-t-2">{picked.join(", ")}</span></span>
                  <div className="flex gap-2">
                    <KButton variant="ghost" onClick={() => setPicked([])}>Temizle</KButton>
                    <KButton variant="primary" icon={<Copy className="h-4 w-4" />} onClick={() => copy(`/takip ${picked.join(" ")}`, "Komut")}>
                      Telegram'da analiz et
                    </KButton>
                  </div>
                </div>
              )}
            </div>
          );
        }}
      </DataView>
    </div>
  );
}
