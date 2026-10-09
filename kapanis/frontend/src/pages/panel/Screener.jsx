import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { K, U } from "@/ds";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { sendAction } from "@/lib/actions";
import { AssetLogo } from "@/components/AssetLogo";
import { Segmented, Chip, SearchField, ChangeBadge, Trend } from "@/components/kp";
import { relDay } from "@/lib/dsmap";
import { px } from "@/lib/portfolio";
import { cn } from "@/lib/utils";
import { useLang } from "@/lib/i18n";

// Hisse tablosu: bir evrenin (S&P 100, BIST) bütün hisseleri, kartla aynı sütunlar. Bakmak ve sıralamak için; öneri listesi değil.
const MARKETS = [{ value: "ABD", label: "ABD · S&P 100" }, { value: "BIST", label: "BIST" }];
const UNIT = { ABD: "$", BIST: "₺" };
const BENCH = { ABD: "S&P 500", BIST: "BIST 100" };
const SORTS = [
  ["puan", "Temel puan: yüksekten düşüğe"], ["guc", "Endekse göre en güçlü"], ["gun", "Günlük: en çok yükselen"],
  ["hafta", "Haftalık: en çok yükselen"], ["bilanco", "Bilançosu en yakın"], ["rsi_up", "RSI: düşükten yükseğe"], ["kod", "Kod (A–Z)"],
];
const KEY = {
  puan: [(r) => r.puan, -1], guc: [(r) => r.guc_6a, -1], gun: [(r) => r.gun_yuzde, -1], hafta: [(r) => r.hafta_yuzde, -1],
  bilanco: [(r) => r.bilanco_gun, 1], rsi_up: [(r) => r.rsi, 1],
};
const FILTERS = {
  trend: { label: "↗ Güçlü trend", test: (r) => String(r.trend || "").startsWith("↗") },
  guc: { label: "Endeksten güçlü", test: (r) => r.guc === "GÜÇLÜ" },
  puan: { label: "Temel puan 70+", test: (r) => r.puan != null && r.puan >= 70 },
  pahali_degil: { label: "Pahalı değil", test: (r) => r.degerleme && r.degerleme !== "PAHALI" && r.degerleme !== "BİLİNMİYOR" },
  bilanco_uzak: { label: "Bilanço 14 günden uzak", test: (r) => r.bilanco_gun == null || r.bilanco_gun > 14 },
  bilanco_yakin: { label: "Bilanço 14 gün içinde", test: (r) => r.bilanco_gun != null && r.bilanco_gun <= 14 },
};
const VAL_CLASS = { PAHALI: "text-down", UCUZ: "text-up" };
const GUC_CLASS = { "GÜÇLÜ": "text-up", ZAYIF: "text-down" };

function sorted(rows, sort) {
  if (sort === "kod") return [...rows].sort((a, b) => a.kod.localeCompare(b.kod));
  const [get, dir] = KEY[sort];
  return [...rows].sort((a, b) => {
    const x = get(a), y = get(b);
    if (x == null) return 1;
    if (y == null) return -1;
    return dir * (x - y);
  });
}

function Earnings({ r }) {
  const { t } = useLang();
  if (r.bilanco_gun == null) return <span className="text-t-3">—</span>;
  const cls = r.bilanco_risk === "YÜKSEK" ? "bg-down/15 text-down" : r.bilanco_risk === "ORTA" ? "is-warn" : "is-flat";
  return <span className={cn("kp-alarm__status whitespace-nowrap", cls)} title={`${t("Bilanço")} ${r.bilanco_tarih}`}>{r.bilanco_gun === 0 ? t("bugün") : `${r.bilanco_gun} ${t("gün")}`}</span>;
}

export default function Screener() {
  const [market, setMarket] = useState("ABD");
  const q = useData(["sonuclar", `tarama_${market.toLowerCase()}`], `/sonuclar/tarama_${market.toLowerCase()}`, LIVE);
  const navigate = useNavigate();
  const { t } = useLang();
  const [sort, setSort] = useState("puan");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState([]);
  const [asked, setAsked] = useState(null);
  const d = q.data || {};
  const all = useMemo(() => d.satirlar || [], [d.satirlar]);
  const waiting = asked && asked.market === market && (!d.zaman || new Date(d.zaman).getTime() < asked.at - 2000);
  const rows = useMemo(() => sorted(all.filter((r) => r.kod.includes(search.trim().toUpperCase()) && filters.every((f) => FILTERS[f].test(r))), sort),
    [all, search, filters, sort]);
  const toggle = (k) => setFilters((f) => (f.includes(k) ? f.filter((x) => x !== k) : [...f, k]));
  const refresh = async () => {
    if (await sendAction("scan.request", { piyasa: market }, `${market} hisse tablosu yenileniyor.`)) setAsked({ market, at: Date.now() });
  };
  const open = (kod) => navigate(`/app/hisse?piyasa=${market}&kod=${encodeURIComponent(kod)}`);
  const soon = all.filter((r) => r.bilanco_risk === "YÜKSEK").length;
  return (
    <div className="kp-page">
      <PageHeader title={t("Hisse tablosu")} testid="page-screener"
        subtitle={t("Bir evrenin bütün hisseleri tek tabloda: trend, endekse göre güç, bilanço günü, temel puan, değerleme. Bakmak ve sıralamak için; öneri listesi değil.")}
        action={<K.Button variant="secondary" onClick={refresh} disabled={!!waiting} data-testid="screener-refresh">{waiting ? t("Hazırlanıyor…") : t("Şimdi yenile")}</K.Button>} />
      <div className="kp-col">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented ariaLabel="Piyasa" value={market} onChange={(m) => { setMarket(m); setFilters([]); setSearch(""); }} options={MARKETS} />
          <SearchField value={search} onChange={setSearch} />
          <label className="inline-flex h-11 items-center rounded-[10px] border border-hairline bg-ink px-3">
            <span className="sr-only">{t("Sıralama")}</span>
            <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t("Sıralama")} className="bg-transparent text-base font-semibold text-t-1 outline-none">
              {SORTS.map(([k, v]) => <option key={k} value={k}>{t(v)}</option>)}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(FILTERS).map(([k, f]) => <Chip key={k} active={filters.includes(k)} onClick={() => toggle(k)}>{t(f.label)}</Chip>)}
        </div>
        {waiting && <p className="kp-note m-0" aria-busy="true">{t("Bot {n} hisse için fiyat, temel puan ve takvim topluyor (5–10 dakika). Sayfa kendiliğinden yenilenir.", { n: market === "ABD" ? "100" : t("200'e yakın") })}</p>}
        {q.isLoading ? <div className="kp-skel h-40" aria-busy="true" /> : !all.length ? (
          <K.Card title={t("Tablo henüz hazırlanmadı")}>
            <p className="kp-note m-0">{t("Bot her işlem günü kapanıştan sonra bu tabloyu yeniler. Beklemeden görmek için \"Şimdi yenile\"ye bas ya da Telegram'da")}
              {market === "ABD" ? " /abd tara" : " /bist tara"} {t("yaz.")}</p>
          </K.Card>
        ) : (
          <>
            <p className="m-0 text-[0.9375rem] text-t-2">
              <b className="num text-t-1">{rows.length}</b>/<b className="num text-t-1">{all.length}</b> {t("hisse")} · {t("güncelleme")} {relDay(d.zaman)}
              {soon > 0 && <> · <b className="text-down">{soon}</b> {t("hissenin bilançosu 5 gün içinde")}</>}
              {d.temeli_eksik > 0 && <span className="text-t-3"> · {d.temeli_eksik} {t("hissenin temel verisi alınamadı")}</span>}
            </p>
            {!rows.length ? <K.Card title={t("Eşleşen hisse yok")}><p className="kp-note m-0">{t("Bu filtrelere uyan hisse yok.")}</p></K.Card> : (
              <>
                <div className="hidden overflow-x-auto rounded-xl border border-hairline bg-surface md:block" data-testid="screener-table">
                  <table className="w-full border-collapse text-[1.0625rem]">
                    <thead>
                      <tr>{[t("Kod"), t("Fiyat"), t("Günlük"), t("Haftalık"), t("Trend"), `${t("Güç")} (${BENCH[market]})`, t("Bilanço"), t("Temel puan"), t("Değerleme"), "RSI"].map((h, i) => (
                        <th key={h} className={cn("h-12 whitespace-nowrap border-b border-hairline px-3 text-left text-sm font-semibold text-t-3", [1, 2, 3, 9].includes(i) && "text-right")}>{h}</th>
                      ))}</tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.kod} tabIndex={0} onClick={() => open(r.kod)} onKeyDown={(e) => e.key === "Enter" && open(r.kod)} aria-label={t("{k} kartını aç", { k: r.kod })}
                          className="cursor-pointer border-b border-hairline transition-colors duration-150 last:border-0 hover:bg-raised">
                          <td className="h-14 whitespace-nowrap px-3">
                            <span className="inline-flex items-center gap-3"><AssetLogo code={r.kod} market={market} />
                              <span><b className="block text-base text-t-1">{r.kod}</b>{r.sektor && <span className="block text-xs text-t-3">{r.sektor}</span>}</span></span>
                          </td>
                          <td className="num whitespace-nowrap px-3 text-right font-bold text-t-1">{px(r.fiyat)} <span className="text-sm font-semibold text-t-3">{UNIT[market]}</span></td>
                          <td className="px-3 text-right"><ChangeBadge value={r.gun_yuzde} /></td>
                          <td className="px-3 text-right"><ChangeBadge value={r.hafta_yuzde} decimals={1} /></td>
                          <td className="whitespace-nowrap px-3"><Trend label={t(r.trend)} /></td>
                          <td className="whitespace-nowrap px-3">{r.guc ? <><b className={GUC_CLASS[r.guc] || "text-t-2"}>{t(r.guc)}</b> <span className="num text-sm text-t-3">{r.guc_6a >= 0 ? "+" : "−"}{U.fmtNum(Math.abs(r.guc_6a), 1)}</span></> : <span className="text-t-3">—</span>}</td>
                          <td className="px-3"><Earnings r={r} /></td>
                          <td className="num whitespace-nowrap px-3 font-bold text-t-1" title={r.puan_etiket || ""}>{r.puan == null ? <span className="font-normal text-t-3">—</span> : <>{r.puan}<span className="text-sm font-normal text-t-3">/100</span></>}</td>
                          <td className="whitespace-nowrap px-3"><b className={VAL_CLASS[r.degerleme] || "text-t-2"}>{r.degerleme ? t(r.degerleme) : "—"}</b></td>
                          <td className="num px-3 text-right text-t-2">{r.rsi ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="divide-y divide-hairline rounded-xl border border-hairline bg-surface md:hidden" data-testid="screener-cards">
                  {rows.map((r) => (
                    <button type="button" key={r.kod} onClick={() => open(r.kod)} className="block w-full p-4 text-left">
                      <span className="flex items-center justify-between gap-3">
                        <span className="flex items-center gap-3"><AssetLogo code={r.kod} market={market} /><b className="text-lg text-t-1">{r.kod}</b></span>
                        <span className="num text-lg font-bold text-t-1">{px(r.fiyat)} <span className="text-base text-t-3">{UNIT[market]}</span></span>
                      </span>
                      <span className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-[0.9375rem] text-t-2">
                        <ChangeBadge value={r.gun_yuzde} label={t("Gün")} />
                        <Trend label={t(r.trend)} />
                        {r.guc && <span>{t("güç")} <b className={GUC_CLASS[r.guc] || "text-t-2"}>{t(r.guc)}</b></span>}
                        {r.puan != null && <span>{t("puan")} <b className="num text-t-1">{r.puan}</b></span>}
                        {r.degerleme && <span><b className={VAL_CLASS[r.degerleme] || "text-t-2"}>{t(r.degerleme)}</b></span>}
                        {r.bilanco_gun != null && <span>{t("bilanço")} <Earnings r={r} /></span>}
                      </span>
                    </button>
                  ))}
                </div>
              </>
            )}
            <p className="kp-note m-0">{t("Satıra basınca hisse kartı açılır. Güç: 6 aylık getirinin {b} getirisinden farkı. Değerleme kaba yön göstergesidir, adil değer hesabı değildir. Temel puan getiri tahmini değildir: hisselerde test edilen zamanlama kurallarının hiçbiri elde tutmayı geçemedi.", { b: BENCH[market] })}
              {(d.kaynaklar || []).length > 0 && ` ${t("Kaynaklar")}: ${d.kaynaklar.join(" · ")}.`}</p>
          </>
        )}
      </div>
    </div>
  );
}
