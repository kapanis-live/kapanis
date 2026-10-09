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
import { Plus, Sparkles } from "lucide-react";
import { K, U } from "@/ds";
import { sendAction } from "@/lib/actions";
import { AiPanel } from "@/pages/panel/Chart";
import { useLang } from "@/lib/i18n";

const RULE_FIELDS = [
  ["destek_yakin", "Desteğe yaklaşınca (%)", "Fiyat desteğe bu yüzdeden yakınsa"],
  ["rsi_alti", "RSI altına inince", "Çok satılmış bölge"],
  ["rsi_ustu", "RSI üstüne çıkınca", "Isınmış bölge"],
  ["hacim_kat", "Hacim ortalamanın kaç katı", "Olağandışı hacim"],
];

// Takip listesi koşulları: bot 30 dakikada bir kontrol eder, her kod+kural için günde en fazla bir kez yazar
function RulesCard({ rules }) {
  const { t } = useLang();
  const r = rules || {};
  const [edit, setEdit] = useState(false);
  const [form, setForm] = useState(() => Object.fromEntries(RULE_FIELDS.map(([k]) => [k, String(r[k] ?? "")])));
  const save = async () => {
    const payload = Object.fromEntries(RULE_FIELDS.map(([k]) => [k, U.parseTr(form[k])]));
    if (Object.values(payload).some((v) => !Number.isFinite(v) || v < 0)) {
      toast.error(t("Değerler sayı olmalı (0 = o kural kapalı)."));
      return;
    }
    if (await sendAction("watch.rules", payload, t("Takip kuralları kaydediliyor."))) setEdit(false);
  };
  const toggle = () => sendAction("watch.rules", { aktif: !r.aktif }, r.aktif ? t("Takip uyarıları kapatılıyor.") : t("Takip uyarıları açılıyor."));
  return (
    <K.Card title={t("Takip uyarıları")} actions={
      <div className="flex gap-2">
        <K.Button variant="ghost" onClick={toggle}>{r.aktif ? t("Kapat§off") : t("Aç")}</K.Button>
        <K.Button variant="ghost" onClick={() => setEdit(!edit)}>{edit ? t("Vazgeç") : t("Değiştir")}</K.Button>
      </div>}>
      {edit ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {RULE_FIELDS.map(([k, label]) => (
            <K.Field key={k} label={t(label)}>
              <K.TextInput inputMode="decimal" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
            </K.Field>
          ))}
          <div className="flex items-end"><K.Button variant="primary" onClick={save}>{t("Kaydet")}</K.Button></div>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <span className={cn("kp-alarm__status", r.aktif ? "is-up" : "is-flat")}>{r.aktif ? t("Açık") : t("Kapalı")}</span>
          {RULE_FIELDS.map(([k, label]) => (
            <span key={k} className="rounded-lg border border-hairline px-3 py-1 text-[0.9375rem] text-t-2">
              {t(label)}: <b className="num text-t-1">{r[k] != null ? U.fmtNum(r[k], k === "rsi_alti" || k === "rsi_ustu" ? 0 : 1) : "—"}</b>
            </span>
          ))}
        </div>
      )}
      <p className="kp-note">{t("Bot 30 dakikada bir listeni kontrol eder; bir koşul olursa Telegram'a yazar (her kod ve kural için günde en fazla bir kez). Bu bir AL sinyali değildir.")} Telegram: /takip kural</p>
    </K.Card>
  );
}

const MARKETS = ["KRIPTO", "BIST", "ABD"];
const UNIT = { KRIPTO: "$", BIST: "₺", ABD: "$" };
const SORTS = [
  ["liste", "Liste sırası"], ["gun_up", "Günlük: en çok yükselen"], ["gun_down", "Günlük: en çok düşen"],
  ["hafta_up", "Haftalık: en çok yükselen"], ["hafta_down", "Haftalık: en çok düşen"],
  ["rsi_down", "RSI: yüksekten düşüğe"], ["rsi_up", "RSI: düşükten yükseğe"], ["destek", "Desteğe en yakın"],
  ["guc_down", "Endekse göre en güçlü"], ["bilanco_up", "Bilançosu en yakın"], ["puan_down", "Temel puan: yüksekten düşüğe"],
];
// [değer, yön]: -1 büyükten küçüğe, 1 küçükten büyüğe. Değeri olmayanlar sona.
const SORT_KEYS = {
  gun_up: [(r) => r.gun_yuzde, -1], gun_down: [(r) => r.gun_yuzde, 1],
  hafta_up: [(r) => r.hafta_yuzde, -1], hafta_down: [(r) => r.hafta_yuzde, 1],
  rsi_down: [(r) => r.rsi, -1], rsi_up: [(r) => r.rsi, 1],
  destek: [(r) => r.destek_yuzde, -1], // destek_yuzde negatif: sıfıra en yakın = desteğe en yakın
  guc_down: [(r) => r.guc_6a, -1], bilanco_up: [(r) => (r.bilanco_gun != null && r.bilanco_gun >= 0 ? r.bilanco_gun : null), 1],
  puan_down: [(r) => r.puan, -1],
};
const FILTERS = {
  guclu: { label: "↗ Güçlü trend", test: (r) => r.trend?.startsWith("↗") },
  zayif: { label: "↘ Zayıf", test: (r) => r.trend?.startsWith("↘") },
  isinmis: { label: "Isınmış (RSI > 70)", test: (r) => r.rsi != null && r.rsi > 70 },
  satilmis: { label: "Çok satılmış (RSI < 30)", test: (r) => r.rsi != null && r.rsi < 30 },
  yakin: { label: "Desteğe %2'den yakın", test: (r) => r.destek_yuzde != null && r.destek_yuzde >= -2 },
  goreli: { label: "Endeksten güçlü", test: (r) => r.guc === "GÜÇLÜ" },
  bilanco: { label: "Bilanço 14 gün içinde", test: (r) => r.bilanco_gun != null && r.bilanco_gun >= 0 && r.bilanco_gun <= 14 },
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

// Endekse göre güç (6 ay, puan farkı), bilançoya kalan gün ve temel puan: açıklama, öneri değil
const BENCH = { KRIPTO: "BTC", BIST: "BIST 100", ABD: "S&P 500" };
const GUC_CLASS = { "GÜÇLÜ": "text-up", ZAYIF: "text-down" };
function Strength({ r }) {
  const { t } = useLang();
  if (r.guc == null) return <span className="text-t-3">—</span>;
  return <span className="whitespace-nowrap"><b className={GUC_CLASS[r.guc] || "text-t-2"}>{t(r.guc)}</b>{" "}
    <span className="num text-sm text-t-3">{r.guc_6a >= 0 ? "+" : "−"}{U.fmtNum(Math.abs(r.guc_6a), 1)}</span></span>;
}
function Earnings({ r }) {
  const { t } = useLang();
  if (r.bilanco_gun == null || r.bilanco_gun < 0) return <span className="text-t-3">—</span>;
  const cls = r.bilanco_risk === "YÜKSEK" ? "bg-down/15 text-down" : r.bilanco_risk === "ORTA" ? "is-warn" : "is-flat";
  return <span className={cn("kp-alarm__status whitespace-nowrap", cls)} title={`${t("Bilanço")} ${r.bilanco_tarih} · ${t("boşluk riski")} ${t(r.bilanco_risk)}`}>
    {r.bilanco_gun === 0 ? t("bugün") : t("{n} gün", { n: r.bilanco_gun })}</span>;
}
function Score({ r }) {
  if (r.puan == null) return <span className="text-t-3">—</span>;
  return <span className="num whitespace-nowrap font-bold text-t-1" title={r.puan_etiket || ""}>{r.puan}<span className="text-sm font-normal text-t-3">/100</span></span>;
}

function HeldTag() {
  const { t } = useLang();
  return <span className="rounded-md bg-brand/15 px-1.5 py-0.5 text-xs font-semibold text-brand">{t("Portföyde")}</span>;
}

export default function Watchlist() {
  const { t } = useLang();
  const q = useData("extras", "/extras", LIVE);
  const navigate = useNavigate();
  const [tab, setTab] = useState("KRIPTO");
  const [sort, setSort] = useState("liste");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState([]);
  const [picked, setPicked] = useState([]);
  const [asked, setAsked] = useState(null);
  const [draft, setDraft] = useState("");
  // Sekmedeki piyasaya eklenir; birden çok kod boşluk ya da virgülle
  const addCodes = async () => {
    const kodlar = draft.toUpperCase().split(/[\s,;]+/).filter(Boolean);
    if (!kodlar.length) {
      toast.error(t("Eklenecek kodu yaz."));
      return;
    }
    if (await sendAction("watch.add", { kodlar, piyasa: tab }, t("{k} takip listesine ekleniyor.", { k: kodlar.join(", ") }))) setDraft("");
  };
  const removePicked = async () => {
    if (await sendAction("watch.remove", { kodlar: picked }, t("{k} listeden çıkarılıyor.", { k: picked.join(", ") }))) setPicked([]);
  };
  const toggleFilter = (k) => setFilters((f) => (f.includes(k) ? f.filter((x) => x !== k) : [...f, k]));
  const togglePick = (k) => setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k]));
  const held = useMemo(() => new Set((q.data?.portfoy || []).map((g) => baseCode(g.ad))), [q.data]);
  const open = (kod) => navigate(chartHref(kod, tab));

  return (
    <div>
      <PageHeader title={t("Takip listesi")} testid="page-watchlist"
        subtitle={t("İzlediğin kodların kodla hesaplanmış hızlı durumu. Satıra tıkla, grafiği açılsın.")}
        action={(
          <span className="flex items-center gap-2">
            <input value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addCodes()}
              placeholder={`${t(MARKET_LABEL[tab])}: ${t("kod ekle")}`} aria-label={t("Takip listesine eklenecek kod")}
              className="h-11 w-44 rounded-[10px] border border-hairline bg-ink px-3 text-base text-t-1 outline-none focus:border-info" />
            <KButton icon={<Plus className="h-4 w-4" />} onClick={addCodes}>{t("Ekle")}</KButton>
          </span>
        )} />
      <DataView query={q} loadingText={t("Takip listesi yükleniyor...")}>
        {(d) => {
          const tl = d.takip_listesi;
          if (!tl?.piyasalar) return <EmptyState text={t("Bot takip listesi verisini henüz göndermedi (30 dakikada bir yeniler). Yukarıdan kod ekleyebilirsin.")} />;
          const all = tl.piyasalar[tab] || [];
          const ok = all.filter((r) => !r.hata);
          const ups = ok.filter((r) => (r.gun_yuzde || 0) > 0).length;
          let rows = all.filter((r) => r.kod.includes(search.trim().toUpperCase()));
          rows = rows.filter((r) => (r.hata ? filters.length === 0 : filters.every((f) => FILTERS[f].test(r, held))));
          rows = sortRows(rows, sort);
          return (
            <div className="space-y-4">
              <RulesCard key={JSON.stringify(d.takip_kurallari || {})} rules={d.takip_kurallari} />
              <div className="flex flex-wrap items-center gap-3">
                <Segmented ariaLabel={t("Piyasa")} value={tab} onChange={(m) => { setTab(m); setPicked([]); setAsked(null); }}
                  options={MARKETS.map((m) => ({ value: m, label: `${t(MARKET_LABEL[m])} ${(tl.piyasalar[m] || []).length}` }))} />
                <SearchField value={search} onChange={setSearch} />
                <label className="inline-flex h-11 items-center rounded-[10px] border border-hairline bg-ink px-3">
                  <span className="sr-only">{t("Sıralama")}</span>
                  <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t("Sıralama")}
                    className="bg-transparent text-base font-semibold text-t-1 outline-none">
                    {SORTS.map(([k, v]) => <option key={k} value={k}>{t(v)}</option>)}
                  </select>
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(FILTERS).map(([k, f]) => (
                  <Chip key={k} active={filters.includes(k)} onClick={() => toggleFilter(k)}>{t(f.label)}</Chip>
                ))}
              </div>
              <p className="m-0 text-[0.9375rem] text-t-2">
                <b className="num text-up">{ups}</b>/<b className="num text-t-1">{ok.length}</b> {t("yükselişte")} ·{" "}
                {tab === "KRIPTO" ? t("günlük = 24 saatlik değişim") : t("günlük = son seans")}{tab === "BIST" ? ` · ${t("veri ~15 dk gecikmeli")}` : ""} ·{" "}
                <span className="text-t-3">{t("güncelleme")} {formatTime(new Date(tl.zaman * 1000).toISOString())}, {t("30 dakikada bir")}</span>
              </p>
              <p className="m-0 text-sm text-t-3">{t("Güç: 6 aylık getirinin {b} getirisinden farkı (puan); 10 puan üstü GÜÇLÜ, altı ZAYIF.", { b: BENCH[tab] })}{" "}
                {tab !== "KRIPTO" && `${t("Bilanço: sıradaki bilançoya kalan gün (5 gün ve altı kırmızı). Temel puan: bilanço verisinden 100 üzerinden, günde bir kez.")} `}
                {t("Açıklamadır, öneri değildir.")}</p>

              {!rows.length ? <EmptyState text={t("Bu filtrelere uyan kod yok.")} /> : (
                <>
                  <div className="hidden overflow-x-auto rounded-xl border border-hairline bg-surface md:block" data-testid="wl-table">
                    <table className="w-full border-collapse text-[1.0625rem]">
                      <thead>
                        <tr>
                          {["", t("Kod"), t("Fiyat"), t("Günlük"), t("Haftalık"), "Trend", `${t("Güç")} (${BENCH[tab]})`, ...(tab === "KRIPTO" ? [] : [t("Bilanço"), t("Temel puan")]), "RSI", t("Destek → Direnç")].map((h, i) => (
                            <th key={h + i} className={cn("h-12 whitespace-nowrap border-b border-hairline px-3 text-left text-sm font-semibold text-t-3", [2, 3, 4].includes(i) && "text-right", i === 0 && "w-12")}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r) => r.hata ? (
                          <tr key={r.kod} className="border-b border-hairline last:border-0">
                            <td className="h-16 pl-4 pr-2" />
                            <td className="px-4 font-bold">{r.kod}</td>
                            <td colSpan={tab === "KRIPTO" ? 7 : 9} className="px-4 text-t-3">{t("veri alınamadı")}</td>
                          </tr>
                        ) : (
                          <tr key={r.kod} tabIndex={0} onClick={() => open(r.kod)} onKeyDown={(e) => e.key === "Enter" && open(r.kod)}
                            className={cn("cursor-pointer border-b border-hairline transition-colors duration-150 last:border-0 hover:bg-raised",
                              picked.includes(r.kod) && "bg-brand/[0.07]")}>
                            <td className="h-16 pl-4 pr-2">
                              <input type="checkbox" checked={picked.includes(r.kod)} onChange={() => togglePick(r.kod)} onClick={(e) => e.stopPropagation()}
                                aria-label={t("{k} seç", { k: r.kod })} className="h-[1.125rem] w-[1.125rem] cursor-pointer" style={{ accentColor: "rgb(var(--c-brand))" }} />
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
                            <td className="whitespace-nowrap px-3"><Trend label={t(r.trend)} /></td>
                            <td className="px-3"><Strength r={r} /></td>
                            {tab !== "KRIPTO" && <td className="px-3"><Earnings r={r} /></td>}
                            {tab !== "KRIPTO" && <td className="px-3"><Score r={r} /></td>}
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
                              aria-label={t("{k} seç", { k: r.kod })} className="h-[1.125rem] w-[1.125rem]" style={{ accentColor: "rgb(var(--c-brand))" }} />}
                            <button onClick={() => !r.hata && open(r.kod)} className="flex items-center gap-3 text-left">
                              <AssetLogo code={r.kod} market={tab} />
                              <span className="text-lg font-bold text-t-1">{r.kod}</span>
                            </button>
                            {held.has(r.kod) && <HeldTag />}
                          </span>
                          {r.hata ? <span className="text-sm text-t-3">{t("veri alınamadı")}</span> : (
                            <span className="num text-lg font-bold text-t-1">{px(r.fiyat)} <span className="text-base text-t-3">{UNIT[tab]}</span></span>
                          )}
                        </div>
                        {!r.hata && (
                          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
                            <ChangeBadge value={r.gun_yuzde} label={t("Gün")} />
                            <ChangeBadge value={r.hafta_yuzde} decimals={1} label={t("Hafta")} />
                            <Trend label={t(r.trend)} />
                            {r.guc && <span className="text-[0.9375rem] text-t-2">{t("güç")} <Strength r={r} /></span>}
                            {tab !== "KRIPTO" && r.bilanco_gun != null && r.bilanco_gun >= 0 && <span className="text-[0.9375rem] text-t-2">{t("bilanço")} <Earnings r={r} /></span>}
                            {tab !== "KRIPTO" && r.puan != null && <span className="text-[0.9375rem] text-t-2">{t("puan")} <Score r={r} /></span>}
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

              {asked && <AiPanel key={asked.join(",")} code={asked[0]} codes={asked} market={tab} auto />}

              {picked.length > 0 && (
                <div className="sticky bottom-20 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-strong bg-surface p-4 lg:bottom-4">
                  <span className="text-base text-t-1"><b>{picked.length}</b> {t("kod seçili")}: <span className="text-t-2">{picked.join(", ")}</span></span>
                  <div className="flex gap-2">
                    <KButton variant="ghost" onClick={() => setPicked([])}>{t("Temizle")}</KButton>
                    <KButton variant="ghost" onClick={removePicked}>{t("Listeden çıkar")}</KButton>
                    <KButton variant="primary" icon={<Sparkles className="h-4 w-4" />} disabled={picked.length > 10}
                      onClick={() => { setAsked(picked); setPicked([]); }}>
                      {picked.length > 10 ? t("En fazla 10 kod") : t("Yapay zekâ analizi")}
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
