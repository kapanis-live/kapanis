import { K, U } from "@/ds";
import { relDay } from "@/lib/dsmap";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { px } from "@/lib/portfolio";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`);
const tone = (v) => (v == null ? "" : v >= 0 ? "kp-num-up" : "kp-num-down");
const money = (v, cur) => `${v >= 0 ? "+" : "−"}${cur === "TL" ? "₺" : "$"}${U.fmtNum(Math.abs(v), 2)}`;

// Kendi karnen: tahmin değil, kapattığın işlemlerin aynası
export default function MyReport() {
  const q = useData("karne", "/karne");
  const r = q.data;
  return <div className="kp-page">
    <PageHeader title="Karnem" subtitle="Kapattığın işlemlerden: ne kadar isabetli, ne kadar tuttun, stopa uydun mu, erken mi sattın." />
    {q.isLoading ? <p className="kp-note">Hesaplanıyor…</p> : !r?.islem ? (
      <K.Card title="Henüz kapalı işlem yok">
        <p className="kp-note m-0">Portföyüm'de bir pozisyonu "Sattım" ile kapattığında karnen burada oluşur.</p>
      </K.Card>
    ) : <>
      {r.not && <K.Callout tone="info" title="Az veri">{r.not}</K.Callout>}
      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(11rem, 1fr))" }}>
        <K.StatCard label="Kapalı işlem" value={String(r.islem)} sub={`${r.kazanan} kazanç · ${r.kaybeden} kayıp`} />
        <K.StatCard label="İsabet" value={r.isabet_yuzde == null ? "—" : `%${r.isabet_yuzde}`} sub="kârla kapanan işlem oranı" />
        <K.StatCard label="Ortalama kazanç" value={pct(r.ort_kazanc_yuzde)} sub={r.ort_gun_kazanan != null ? `ort. ${U.fmtNum(r.ort_gun_kazanan, 1)} gün tuttun` : ""} />
        <K.StatCard label="Ortalama kayıp" value={pct(r.ort_kayip_yuzde)} sub={r.ort_gun_kaybeden != null ? `ort. ${U.fmtNum(r.ort_gun_kaybeden, 1)} gün tuttun` : ""} />
        {Object.entries(r.gerceklesen || {}).map(([cur, v]) =>
          <K.StatCard key={cur} label={`Gerçekleşen (${cur})`} value={money(v, cur)} sub="kapattıkların toplamı" />)}
      </div>
      <K.Card title="Davranışın">
        <ul className="m-0 flex list-none flex-col gap-2 p-0 text-t-2">
          <li>{r.ort_gun_kaybeden != null && r.ort_gun_kazanan != null && r.ort_gun_kaybeden > r.ort_gun_kazanan
            ? `⚠️ Kaybedenleri kazananlardan uzun tutuyorsun (${U.fmtNum(r.ort_gun_kaybeden, 1)} gün vs ${U.fmtNum(r.ort_gun_kazanan, 1)} gün): en yaygın hata "kârı erken al, zararı bekle".`
            : "✅ Kaybedenleri kazananlardan uzun tutmuyorsun."}</li>
          <li>{r.stop_alti_satis
            ? `⚠️ ${r.stop_alti_satis} işlemi stopunun altından sattın (ortalama ${pct(r.stop_alti_ort_yuzde)}): stop kapanışla kırıldığında beklemek kaybı büyüttü.`
            : "✅ Stopunun altına inmeden sattın."}</li>
          <li>{r.erken_satis
            ? `ℹ️ ${r.erken_satis} kârlı satıştan sonra fiyat %10'dan fazla daha yükseldi. Bu kesin bir hata değil; çıkışı kurala (ör. trend kuralı) bağlarsan duyguya bağlı kalmaz.`
            : "ℹ️ Sattıktan sonra %10'dan fazla yükselen olmadı."}</li>
        </ul>
      </K.Card>
      <K.Card title="Son satışların">
        <K.DataTable rows={r.islemler.map((x, i) => ({ ...x, _k: i }))} rowKey="_k" columns={[
          { key: "kod", label: "Kod", render: (x) => <K.Ticker symbol={x.kod} logo={{ code: x.kod, market: x.piyasa }} /> },
          { key: "zaman", label: "Satış", render: (x) => relDay(x.zaman) },
          { key: "fiyat", label: "Maliyet → satış", num: true, mobile: false, render: (x) => `${px(x.maliyet)} → ${px(x.fiyat)}` },
          { key: "getiri_yuzde", label: "Sonuç", num: true, strong: true, render: (x) => <span className={tone(x.getiri_yuzde)}>{pct(x.getiri_yuzde)}{x.stop_alti ? " · stop altı" : ""}</span> },
          { key: "gun", label: "Gün", num: true, mobile: false, render: (x) => (x.gun == null ? "—" : U.fmtNum(x.gun, 1)) },
          { key: "sonra_yuzde", label: "Satıştan sonra", num: true, render: (x) => <span className={tone(x.sonra_yuzde)}>{pct(x.sonra_yuzde)}</span> },
        ]} />
        <p className="kp-note">"Satıştan sonra": sattığın fiyattan son günlük kapanışa değişim.</p>
      </K.Card>
    </>}
  </div>;
}
