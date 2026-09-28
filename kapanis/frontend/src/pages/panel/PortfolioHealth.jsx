import { K, U } from "@/ds";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { px } from "@/lib/portfolio";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`);
const tone = (v) => (v == null ? "" : v >= 0 ? "kp-num-up" : "kp-num-down");

// Portföy sağlığı: ağırlık, tepeden düşüş, test edilmiş trend kuralı, birlikte hareket edenler
export default function PortfolioHealth() {
  const q = useData("health", "/portfolio/health", { refetchInterval: 300_000 });
  const d = q.data;
  const rows = d?.pozisyonlar || [];
  return <div className="kp-page">
    <PageHeader title="Portföy sağlığı" subtitle="Tek ekranda: neye ne kadar bağlısın, tepeden ne kadar düştün, hangileri aslında aynı pozisyon." />
    {q.isLoading ? <p className="kp-note">Hesaplanıyor…</p> : !rows.length ? (
      <K.Card title="Açık pozisyon yok"><p className="kp-note m-0">Portföyüm'e pozisyon ekleyince burada sağlık özeti çıkar.</p></K.Card>
    ) : <>
      {d.uyarilar?.length ? <K.Callout tone="warn" title={`${d.uyarilar.length} dikkat noktası`}>
        <ul className="m-0 pl-5">{d.uyarilar.map((w) => <li key={w}>{w}</li>)}</ul>
      </K.Callout> : <K.Callout tone="info" title="Belirgin sorun yok">Yoğunlaşma, birlikte hareket eden çift ya da stopsuz pozisyon görünmüyor.</K.Callout>}
      <K.Card title={`Pozisyonlar${d.toplam_tl ? ` · toplam ≈ ₺${U.fmtNum(d.toplam_tl, 0)}` : ""}`}>
        <K.DataTable rows={rows} rowKey="id" columns={[
          { key: "kod", label: "Kod", render: (x) => <K.Ticker symbol={x.kod} logo={{ code: x.kod, market: x.piyasa }} /> },
          { key: "agirlik_yuzde", label: "Ağırlık", num: true, strong: true, render: (x) => (x.agirlik_yuzde == null ? "—" : `%${U.fmtNum(x.agirlik_yuzde, 1)}`) },
          { key: "getiri_yuzde", label: "Maliyete göre", num: true, render: (x) => <span className={tone(x.getiri_yuzde)}>{pct(x.getiri_yuzde)}</span> },
          { key: "tepeden_yuzde", label: "Tepeden", num: true, render: (x) => <span className={x.tepeden_yuzde <= -10 ? "kp-num-down" : ""}>{pct(x.tepeden_yuzde)}</span> },
          { key: "trend", label: "Trend kuralı", mobile: false, render: (x) => !x.trend ? <span className="text-t-3">yalnız kripto</span>
            : x.trend.trendde ? <span className="kp-num-up">trendde · çıkış {px(x.trend.alt10)}</span>
            : <span className="kp-num-down">dışarıda (10 gün dibi {px(x.trend.alt10)})</span> },
          { key: "stop", label: "Stop", num: true, mobile: false, render: (x) => (x.stop == null ? "yok" : px(x.stop)) },
        ]} />
        <p className="kp-note">Ağırlık TL karşılığıyla (USD/TRY {d.usdtry ? U.fmtNum(d.usdtry, 2) : "—"}). "Tepeden": aldığından beri görülen en yüksek günlük kapanışa
          göre. Trend kuralı geçmiş testte işe yarayan tek kural; yalnız kriptoda test edildi. Kapanış fiyatları, oluşmakta olan mum sayılmaz.</p>
      </K.Card>
      {!!d.korelasyon?.length && <K.Card title="Birlikte hareket edenler">
        <ul className="m-0 pl-5 text-t-2">{d.korelasyon.map((c) => <li key={c.a + c.b}>{c.a} – {c.b}: 90 günlük korelasyon {U.fmtNum(c.r, 2)}. Biri düşerken diğeri de düşer; risk hesabında tek pozisyon say.</li>)}</ul>
      </K.Card>}
    </>}
  </div>;
}
