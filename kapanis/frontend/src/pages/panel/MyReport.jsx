import { K, U } from "@/ds";
import { relDay } from "@/lib/dsmap";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { px } from "@/lib/portfolio";
import MonthlyReport from "@/components/MonthlyReport";
import { useLang } from "@/lib/i18n";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`);
const tone = (v) => (v == null ? "" : v >= 0 ? "kp-num-up" : "kp-num-down");
const money = (v, cur) => `${v >= 0 ? "+" : "−"}${cur === "TL" ? "₺" : "$"}${U.fmtNum(Math.abs(v), 2)}`;

// Kendi karnen: tahmin değil, kapattığın işlemlerin aynası
export default function MyReport() {
  const { t } = useLang();
  const q = useData("karne", "/karne");
  const r = q.data;
  const held = (n) => (n != null ? t("ort. {n} gün tuttun", { n: U.fmtNum(n, 1) }) : "");
  return <div className="kp-page">
    <PageHeader title={t("Karnem")} subtitle={t("Kapattığın işlemlerden: ne kadar isabetli, ne kadar tuttun, stopa uydun mu, erken mi sattın.")} />
    <div className="mb-4"><MonthlyReport /></div>
    {q.isLoading ? <div className="kp-skel h-40" aria-busy="true" /> : !r?.islem ? (
      <K.Card title={t("Henüz kapalı işlem yok")}>
        <p className="kp-note m-0">{t("Portföyüm'de bir pozisyonu \"Sattım\" ile kapattığında karnen burada oluşur.")}</p>
      </K.Card>
    ) : <>
      {r.not && <K.Callout tone="info" title={t("Az veri")}>{r.not}</K.Callout>}
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(11rem, 1fr))" }}>
        <K.StatCard label={t("Kapalı işlem")} value={String(r.islem)} sub={t("{w} kazanç · {l} kayıp", { w: r.kazanan, l: r.kaybeden })} />
        <K.StatCard label={t("İsabet")} value={r.isabet_yuzde == null ? "—" : `%${r.isabet_yuzde}`} sub={t("kârla kapanan işlem oranı")} />
        <K.StatCard label={t("Ortalama kazanç")} value={pct(r.ort_kazanc_yuzde)} sub={held(r.ort_gun_kazanan)} />
        <K.StatCard label={t("Ortalama kayıp")} value={pct(r.ort_kayip_yuzde)} sub={held(r.ort_gun_kaybeden)} />
        {Object.entries(r.gerceklesen || {}).map(([cur, v]) =>
          <K.StatCard key={cur} label={t("Gerçekleşen ({c})", { c: cur })} value={money(v, cur)} sub={t("kapattıkların toplamı")} />)}
      </div>
      <K.Card title={t("Davranışın")}>
        <ul className="m-0 flex list-none flex-col gap-2 p-0 text-t-2">
          <li>{r.ort_gun_kaybeden != null && r.ort_gun_kazanan != null && r.ort_gun_kaybeden > r.ort_gun_kazanan
            ? t("⚠️ Kaybedenleri kazananlardan uzun tutuyorsun ({a} gün vs {b} gün): en yaygın hata \"kârı erken al, zararı bekle\".", { a: U.fmtNum(r.ort_gun_kaybeden, 1), b: U.fmtNum(r.ort_gun_kazanan, 1) })
            : t("✅ Kaybedenleri kazananlardan uzun tutmuyorsun.")}</li>
          <li>{r.stop_alti_satis
            ? t("⚠️ {n} işlemi stopunun altından sattın (ortalama {p}): stop kapanışla kırıldığında beklemek kaybı büyüttü.", { n: r.stop_alti_satis, p: pct(r.stop_alti_ort_yuzde) })
            : t("✅ Stopunun altına inmeden sattın.")}</li>
          <li>{r.erken_satis
            ? t("ℹ️ {n} kârlı satıştan sonra fiyat %10'dan fazla daha yükseldi. Bu kesin bir hata değil; çıkışı kurala (ör. trend kuralı) bağlarsan duyguya bağlı kalmaz.", { n: r.erken_satis })
            : t("ℹ️ Sattıktan sonra %10'dan fazla yükselen olmadı.")}</li>
        </ul>
      </K.Card>
      <K.Card title={t("Son satışların")}>
        <K.DataTable rows={r.islemler.map((x, i) => ({ ...x, _k: i }))} rowKey="_k" columns={[
          { key: "kod", label: t("Kod"), render: (x) => <K.Ticker symbol={x.kod} logo={{ code: x.kod, market: x.piyasa }} /> },
          { key: "zaman", label: t("Satış"), render: (x) => relDay(x.zaman) },
          { key: "fiyat", label: t("Maliyet → satış"), num: true, mobile: false, render: (x) => `${px(x.maliyet)} → ${px(x.fiyat)}` },
          { key: "getiri_yuzde", label: t("Sonuç"), num: true, strong: true, render: (x) => <span className={tone(x.getiri_yuzde)}>{pct(x.getiri_yuzde)}{x.stop_alti ? ` · ${t("stop altı")}` : ""}</span> },
          { key: "gun", label: t("Gün"), num: true, mobile: false, render: (x) => (x.gun == null ? "—" : U.fmtNum(x.gun, 1)) },
          { key: "sonra_yuzde", label: t("Satıştan sonra"), num: true, render: (x) => <span className={tone(x.sonra_yuzde)}>{pct(x.sonra_yuzde)}</span> },
        ]} />
        <p className="kp-note">{t("\"Satıştan sonra\": sattığın fiyattan son günlük kapanışa değişim.")}</p>
      </K.Card>
    </>}
  </div>;
}
