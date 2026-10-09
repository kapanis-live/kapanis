import { useState } from "react";
import { K, U } from "@/ds";
import { useData } from "@/lib/useData";

// Aylık rapor: bot ayın ilk günü hazırlar (ya da /aylik). Geçmişin özeti; tahmin ya da öneri içermez.
const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`);
const tone = (v) => (v == null ? undefined : v >= 0 ? "up" : "down");
const cls = (v) => (v == null ? "" : v >= 0 ? "kp-num-up" : "kp-num-down");
const money = (v, cur) => `${v >= 0 ? "+" : "−"}${cur === "TL" ? "₺" : "$"}${U.fmtNum(Math.abs(v), 0)}`;
const day = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;

function Movers({ title, rows }) {
  return (
    <section>
      <h3 className="kp-card__title" style={{ margin: "0 0 0.5rem" }}>{title}</h3>
      {rows.length ? (
        <ul className="m-0 flex list-none flex-col p-0">
          {rows.map((a) => (
            <li key={a.ad} className="flex items-baseline justify-between gap-3 border-b border-hairline py-2 last:border-0">
              <b className="text-t-1">{a.ad} <span className="text-sm font-normal text-t-3">· {a.piyasa}</span></b>
              <span className="num whitespace-nowrap"><b className={cls(a.yuzde)}>{pct(a.yuzde)}</b> <span className="text-sm text-t-3">{money(a.kazanc, a.para)}</span></span>
            </li>
          ))}
        </ul>
      ) : <p className="kp-note m-0">Yok.</p>}
    </section>
  );
}

export default function MonthlyReport() {
  const q = useData(["sonuclar", "aylik"], "/sonuclar/aylik");
  const [picked, setPicked] = useState(null);
  const months = q.data?.gecmis?.length ? q.data.gecmis : q.data?.son ? [q.data.son] : [];
  if (!months.length) {
    return (
      <K.Card title="Aylık rapor">
        <p className="kp-note m-0">Henüz rapor yok. Bot her ayın ilk günü geçen ayın raporunu hazırlar; beklemeden görmek için Telegram'da /aylik yaz.</p>
      </K.Card>
    );
  }
  const d = months.find((m) => m.ay === picked) || months[0];
  const g = d.getiri, t = d.islemler, y = d.yogunlasma;
  const diffs = Object.entries(d.kiyas || {}).filter(([, v]) => v != null).map(([name, v]) => {
    const mine = name === "BIST 100" ? g.tl_yuzde : g.usd_yuzde;
    return { name, bench: v, diff: mine == null ? null : Math.round((mine - v) * 10) / 10, cur: name === "BIST 100" ? "TL" : "USD" };
  });
  const select = months.length > 1 ? (
    <select value={d.ay} onChange={(e) => setPicked(e.target.value)} aria-label="Ay"
      className="h-10 rounded-[10px] border border-hairline bg-ink px-3 text-base font-semibold text-t-1 outline-none">
      {months.map((m) => <option key={m.ay} value={m.ay}>{m.ad}</option>)}
    </select>
  ) : null;
  return (
    <K.Card title={`Aylık rapor · ${d.ad}`} actions={select}>
      <div className="flex flex-col gap-5" data-testid="monthly-report">
        {!d.varlik ? <p className="kp-note m-0">Bu ay içinde izlenen pozisyon yok.</p> : (
          <>
            <div className="kp-grid kp-g-4">
              <K.StatCard label="Getiri (TL)" value={pct(g.tl_yuzde)} tone={tone(g.tl_yuzde)} sub={money(g.kazanc_tl, "TL")} />
              <K.StatCard label="Getiri (USD)" value={pct(g.usd_yuzde)} tone={tone(g.usd_yuzde)} sub={money(g.kazanc_usd, "USD")} />
              <K.StatCard label="İşlemler" value={`${t.alim} alım · ${t.satim} satım`}
                sub={Object.keys(t.gerceklesen).length ? `gerçekleşen ${Object.entries(t.gerceklesen).map(([c, v]) => money(v, c)).join(" · ")}` : "satış yok"} />
              <K.StatCard label="En büyük pozisyon" value={y.ay_sonu ? `%${U.fmtNum(y.ay_sonu.yuzde, 1)}` : "—"}
                sub={y.ay_sonu ? `${y.ay_sonu.ad}${y.ay_basi ? ` · ay başı ${y.ay_basi.ad} %${U.fmtNum(y.ay_basi.yuzde, 1)}` : ""}` : "ay sonunda pozisyon yok"} />
            </div>

            {diffs.length > 0 && (
              <section>
                <h3 className="kp-card__title" style={{ margin: "0 0 0.5rem" }}>Aynı ay endeksler</h3>
                <K.DataTable rows={diffs.map((x, i) => ({ ...x, _k: i }))} rowKey="_k" columns={[
                  { key: "name", label: "Endeks", render: (x) => <b>{x.name}</b> },
                  { key: "bench", label: "Aynı ay", num: true, render: (x) => <span className={cls(x.bench)}>{pct(x.bench)}</span> },
                  { key: "diff", label: "Senin farkın (puan)", num: true, strong: true,
                    render: (x) => (x.diff == null ? "—" : <span className={cls(x.diff)}>{x.diff >= 0 ? "+" : "−"}{U.fmtNum(Math.abs(x.diff), 1)} <span className="text-sm font-normal text-t-3">{x.cur}</span></span>) },
                ]} />
                <p className="kp-note">BIST 100 ile TL getirin, diğerleriyle USD getirin karşılaştırılır. USD/TRY aynı ay {pct(d.usdtry_yuzde)}.</p>
              </section>
            )}

            <div className="kp-grid kp-g-2">
              <Movers title="En çok kazandıran" rows={d.en_iyi || []} />
              <Movers title="En çok kaybettiren" rows={d.en_kotu || []} />
            </div>

            {(t.alinan.length > 0 || t.satilan.length > 0) && (
              <p className="m-0 text-[0.9375rem] text-t-2">
                {t.alinan.length > 0 && <>Alınan: <b className="text-t-1">{t.alinan.join(", ")}</b></>}
                {t.alinan.length > 0 && t.satilan.length > 0 && " · "}
                {t.satilan.length > 0 && <>Satılan: <b className="text-t-1">{t.satilan.join(", ")}</b></>}
              </p>
            )}
          </>
        )}
        {d.hesaplanamayan?.length > 0 && <p className="kp-note m-0">Fiyat geçmişi alınamadığı için dışarıda kalan: {d.hesaplanamayan.join(", ")}.</p>}
        <p className="kp-note m-0">Ölçüm: her pozisyon yalnız elde tutulduğu günler için sayılır ({day(d.bas_gun)} kapanışı → {day(d.son_gun)} kapanışı;
          ay içinde alınan alış fiyatından, satılan satış fiyatından). Yeni giren para getiri sayılmaz. Geçmişin özetidir; tahmin ya da öneri içermez.
          Telegram: /aylik</p>
      </div>
    </K.Card>
  );
}
