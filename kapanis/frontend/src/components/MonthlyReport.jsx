import { useState } from "react";
import { K, U } from "@/ds";
import { useData } from "@/lib/useData";
import { useLang } from "@/lib/i18n";
import { useAuth } from "@/context/AuthContext";
import api, { formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";

// Aylık rapor: bot ayın ilk günü hazırlar (ya da /aylik). Geçmişin özeti; tahmin ya da öneri içermez.
// Sistem sahibi: botun kendi kaydı. Diğer hesaplar: sitedeki Portföyüm'den, istek üzerine (günde 3), yalnız o hesaba görünür.
const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`);
const tone = (v) => (v == null ? undefined : v >= 0 ? "up" : "down");
const cls = (v) => (v == null ? "" : v >= 0 ? "kp-num-up" : "kp-num-down");
const money = (v, cur) => `${v >= 0 ? "+" : "−"}${cur === "TL" ? "₺" : "$"}${U.fmtNum(Math.abs(v), 0)}`;
const day = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

function Movers({ title, rows }) {
  const { t } = useLang();
  return (
    <section>
      <h3 className="kp-card__title" style={{ margin: "0 0 0.5rem" }}>{title}</h3>
      {rows.length ? (
        <ul className="m-0 flex list-none flex-col p-0">
          {rows.map((a) => (
            <li key={a.ad} className="flex items-baseline justify-between gap-3 border-b border-hairline py-2 last:border-0">
              <b className="text-t-1">{a.ad} <span className="text-sm font-normal text-t-3">· {t(a.piyasa)}</span></b>
              <span className="num whitespace-nowrap"><b className={cls(a.yuzde)}>{pct(a.yuzde)}</b> <span className="text-sm text-t-3">{money(a.kazanc, a.para)}</span></span>
            </li>
          ))}
        </ul>
      ) : <p className="kp-note m-0">{t("Yok.")}</p>}
    </section>
  );
}

export default function MonthlyReport() {
  const { t, td, monthName } = useLang();
  const { owner } = useAuth();
  const q = useData(owner ? ["sonuclar", "aylik"] : ["my-monthly"], owner ? "/sonuclar/aylik" : "/portfolio/monthly", owner ? undefined : { refetchInterval: 8000 });
  const [picked, setPicked] = useState(null);
  const [asked, setAsked] = useState(null);
  const waiting = !owner && asked && (!q.data?.zaman || new Date(q.data.zaman).getTime() < asked - 2000);
  const run = async () => {
    try {
      await api.post("/portfolio/monthly");
      toast.success(t("Aylık rapor hazırlanıyor."));
      setAsked(Date.now());
    } catch (e) {
      toast.error(td(formatApiErrorDetail(e.response?.data?.detail)) || t("Rapor hazırlanamadı"));
    }
  };
  const prepare = owner ? null : (
    <K.Button variant="secondary" onClick={run} disabled={!!waiting} data-testid="monthly-run">{waiting ? t("Hazırlanıyor…") : q.data?.son ? t("Yenile") : t("Hazırla")}</K.Button>
  );
  const months = q.data?.gecmis?.length ? q.data.gecmis : q.data?.son ? [q.data.son] : [];
  // "2026-09" → Eylül 2026 / September 2026
  const name = (m) => (/^\d{4}-\d{2}$/.test(m.ay || "") ? `${monthName(Number(m.ay.slice(5)) - 1)} ${m.ay.slice(0, 4)}` : m.ad);
  if (!months.length) {
    return (
      <K.Card title={t("Aylık rapor")} actions={prepare}>
        {owner ? <p className="kp-note m-0">{t("Henüz rapor yok. Bot her ayın ilk günü geçen ayın raporunu hazırlar; beklemeden görmek için Telegram'da /aylik yaz.")}</p>
          : waiting ? <p className="kp-note m-0" aria-busy="true">{t("Bot ay içindeki fiyatları topluyor (10–40 sn)…")}</p>
          : q.data?.hata ? <K.Callout tone="warn" title={t("Rapor hazırlanamadı")}>{td(q.data.hata)}</K.Callout>
          : q.data?.bos ? <p className="kp-note m-0">{t("Geçen ay içinde elde tutulan pozisyon yok.")}</p>
          : <p className="kp-note m-0">{t("Geçen ayın raporu: getiri, endekslere göre fark, en çok kazandıran ve kaybettiren, işlemler. Portföyüm'deki pozisyonlardan hesaplanır; \"Hazırla\"ya bas.")}</p>}
      </K.Card>
    );
  }
  const d = months.find((m) => m.ay === picked) || months[0];
  const g = d.getiri, tx = d.islemler, y = d.yogunlasma;
  const diffs = Object.entries(d.kiyas || {}).filter(([, v]) => v != null).map(([index, v]) => {
    const mine = index === "BIST 100" ? g.tl_yuzde : g.usd_yuzde;
    return { name: index, bench: v, diff: mine == null ? null : Math.round((mine - v) * 10) / 10, cur: index === "BIST 100" ? "TL" : "USD" };
  });
  const select = months.length > 1 ? (
    <select value={d.ay} onChange={(e) => setPicked(e.target.value)} aria-label={t("Ay")}
      className="h-10 rounded-[10px] border border-hairline bg-ink px-3 text-base font-semibold text-t-1 outline-none">
      {months.map((m) => <option key={m.ay} value={m.ay}>{name(m)}</option>)}
    </select>
  ) : null;
  return (
    <K.Card title={`${t("Aylık rapor")} · ${name(d)}`} actions={<span className="flex flex-wrap items-center gap-2">{select}{prepare}</span>}>
      <div className="flex flex-col gap-5" data-testid="monthly-report">
        {!d.varlik ? <p className="kp-note m-0">{t("Bu ay içinde izlenen pozisyon yok.")}</p> : (
          <>
            <div className="kp-grid kp-g-4">
              <K.StatCard label={t("Getiri (TL)")} value={pct(g.tl_yuzde)} tone={tone(g.tl_yuzde)} sub={money(g.kazanc_tl, "TL")} />
              <K.StatCard label={t("Getiri (USD)")} value={pct(g.usd_yuzde)} tone={tone(g.usd_yuzde)} sub={money(g.kazanc_usd, "USD")} />
              <K.StatCard label={t("İşlemler")} value={t("{a} alım · {s} satım", { a: tx.alim, s: tx.satim })}
                sub={Object.keys(tx.gerceklesen).length ? `${t("gerçekleşen")} ${Object.entries(tx.gerceklesen).map(([c, v]) => money(v, c)).join(" · ")}` : t("satış yok")} />
              <K.StatCard label={t("En büyük pozisyon")} value={y.ay_sonu ? `%${U.fmtNum(y.ay_sonu.yuzde, 1)}` : "—"}
                sub={y.ay_sonu ? `${y.ay_sonu.ad}${y.ay_basi ? ` · ${t("ay başı")} ${y.ay_basi.ad} %${U.fmtNum(y.ay_basi.yuzde, 1)}` : ""}` : t("ay sonunda pozisyon yok")} />
            </div>

            {diffs.length > 0 && (
              <section>
                <h3 className="kp-card__title" style={{ margin: "0 0 0.5rem" }}>{t("Aynı ay endeksler")}</h3>
                <K.DataTable rows={diffs.map((x, i) => ({ ...x, _k: i }))} rowKey="_k" columns={[
                  { key: "name", label: t("Endeks"), render: (x) => <b>{t(x.name)}</b> },
                  { key: "bench", label: t("Aynı ay"), num: true, render: (x) => <span className={cls(x.bench)}>{pct(x.bench)}</span> },
                  { key: "diff", label: t("Senin farkın (puan)"), num: true, strong: true,
                    render: (x) => (x.diff == null ? "—" : <span className={cls(x.diff)}>{x.diff >= 0 ? "+" : "−"}{U.fmtNum(Math.abs(x.diff), 1)} <span className="text-sm font-normal text-t-3">{x.cur}</span></span>) },
                ]} />
                <p className="kp-note">{t("BIST 100 ile TL getirin, diğerleriyle USD getirin karşılaştırılır. USD/TRY aynı ay {x}.", { x: pct(d.usdtry_yuzde) })}</p>
              </section>
            )}

            <div className="kp-grid kp-g-2">
              <Movers title={t("En çok kazandıran")} rows={d.en_iyi || []} />
              <Movers title={t("En çok kaybettiren")} rows={d.en_kotu || []} />
            </div>

            {(tx.alinan.length > 0 || tx.satilan.length > 0) && (
              <p className="m-0 text-[0.9375rem] text-t-2">
                {tx.alinan.length > 0 && <>{t("Alınan")}: <b className="text-t-1">{tx.alinan.join(", ")}</b></>}
                {tx.alinan.length > 0 && tx.satilan.length > 0 && " · "}
                {tx.satilan.length > 0 && <>{t("Satılan")}: <b className="text-t-1">{tx.satilan.join(", ")}</b></>}
              </p>
            )}
          </>
        )}
        {d.hesaplanamayan?.length > 0 && <p className="kp-note m-0">{t("Fiyat geçmişi alınamadığı için dışarıda kalan")}: {d.hesaplanamayan.join(", ")}.</p>}
        <p className="kp-note m-0">{t("Ölçüm: her pozisyon yalnız elde tutulduğu günler için sayılır ({a} kapanışı → {b} kapanışı; ay içinde alınan alış fiyatından, satılan satış fiyatından). Yeni giren para getiri sayılmaz. Geçmişin özetidir; tahmin ya da öneri içermez.",
          { a: day(d.bas_gun), b: day(d.son_gun) })}{owner ? " Telegram: /aylik" : ""}</p>
      </div>
    </K.Card>
  );
}
