import { useState } from "react";
import { toast } from "sonner";
import { K, U } from "@/ds";
import api, { formatApiErrorDetail } from "@/lib/api";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { px } from "@/lib/portfolio";
import UsBook from "@/components/UsBook";
import { useLang } from "@/lib/i18n";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`);
const tone = (v) => (v == null ? "" : v >= 0 ? "kp-num-up" : "kp-num-down");

const REGIME_TONE = { TREND_UP: "kp-num-up", TREND_DOWN: "kp-num-down", PANIK: "kp-num-down" };

function RegimeStrip() {
  const { t } = useLang();
  const q = useData("market-regime", "/market/regime", { refetchInterval: 900_000 });
  if (!q.data) return null;
  return <K.Card title={t("Piyasa durumu")}>
    <div className="flex flex-wrap gap-4">{q.data.rejimler.map((r) =>
      <div key={r.piyasa} className="flex flex-col"><span className="text-sm text-t-3">{t(r.piyasa)}</span>
        <b className={REGIME_TONE[r.rejim] || "text-t-1"}>{t(r.aciklama)}</b></div>)}</div>
    <p className="kp-note">{t(q.data.not)}</p>
  </K.Card>;
}

// "Kaç adet alayım?": risk matematiği (portföy × risk %, oynaklık, korelasyon, yoğunlaşma), tahmin değil
function SizeCalc() {
  const { t, td } = useLang();
  const [f, setF] = useState({ piyasa: "BIST", kod: "", stop: "", risk: "" });
  const [r, setR] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const run = async () => {
    if (!f.kod.trim()) return toast.error(t("Kod yaz."));
    setBusy(true);
    try {
      const body = { piyasa: f.piyasa, kod: f.kod.trim() };
      if (String(f.stop).trim()) body.stop = U.parseTr(String(f.stop));
      if (String(f.risk).trim()) body.risk_yuzde = U.parseTr(String(f.risk));
      setR((await api.post("/risk/size", body)).data);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); setR(null); }
    finally { setBusy(false); }
  };
  return <K.Card title={t("Kaç adet alayım? (risk hesabı)")}>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <K.Field label={t("Piyasa")}><K.Select value={f.piyasa} onChange={set("piyasa")} options={[{ value: "BIST", label: "BIST" }, { value: "KRIPTO", label: t("Kripto") }, { value: "ABD", label: t("ABD") }]} /></K.Field>
      <K.Field label={t("Kod")}><K.TextInput value={f.kod} onChange={set("kod")} placeholder="ASTOR" /></K.Field>
      <K.Field label="Stop" hint={t("boşsa 2 × ATR")}><K.TextInput inputMode="decimal" value={f.stop} onChange={set("stop")} placeholder="0,00" /></K.Field>
      <K.Field label="Risk %" hint={t("boşsa %1")}><K.TextInput inputMode="decimal" value={f.risk} onChange={set("risk")} placeholder="1" /></K.Field>
      <div className="flex items-end"><K.Button variant="primary" disabled={busy} onClick={run}>{busy ? t("Hesaplanıyor…") : t("Hesapla")}</K.Button></div>
    </div>
    {r && <div className="mt-3 flex flex-col gap-2">
      <p className="m-0 text-lg text-t-1">{t("En fazla")} <b>{U.fmtNum(r.adet, r.piyasa === "BIST" ? 0 : 6)} {t("adet")}</b> ({r.para === "TL" ? "₺" : "$"}{U.fmtNum(r.tutar, 2)}) ·
        stop {px(r.stop)} ({td(r.stop_kaynagi)}) · {t("stop kırılırsa kayıp")} ≈ ₺{U.fmtNum(r.risk_tl, 0)}</p>
      <ul className="m-0 pl-5 text-t-2">{r.satirlar.map((x) => <li key={x}>{td(x)}</li>)}</ul>
      <p className="kp-note">{td(r.not)}</p>
    </div>}
  </K.Card>;
}

// Stres testi: geçmiş 1 yıldaki duyarlılıkla (beta) "şu olursa portföyüm ne olur?" — tahmin değil
function StressCard() {
  const { t } = useLang();
  const q = useData("stress", "/portfolio/stress", { refetchInterval: 900_000 });
  const d = q.data;
  if (q.isLoading) return <div className="kp-skel h-40" aria-busy="true" />;
  if (!d?.senaryolar?.length || !d.toplam_tl) return null;
  return <K.Card title={t("Stres testi: şu olursa?")}>
    <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(13rem, 1fr))" }}>
      {d.senaryolar.map((sc) => (
        <div key={sc.senaryo} className="rounded-lg border border-hairline p-3">
          <p className="m-0 text-sm text-t-3">{t(sc.senaryo)}</p>
          <p className={`m-0 text-xl font-bold ${sc.portfoy_tl < 0 ? "kp-num-down" : sc.portfoy_tl > 0 ? "kp-num-up" : ""}`}>
            {sc.portfoy_tl >= 0 ? "+" : "−"}₺{U.fmtNum(Math.abs(sc.portfoy_tl), 0)} <span className="text-sm">({pct(sc.portfoy_yuzde)})</span></p>
          <p className="m-0 mt-1 text-xs text-t-3">{sc.kalemler.slice(0, 3).map((k) => `${k.kod} ${pct(k.tahmini_yuzde)}`).join(" · ")}</p>
        </div>
      ))}
    </div>
    <p className="kp-note">{t(d.not)}</p>
  </K.Card>;
}

// Portföy sağlığı: ağırlık, tepeden düşüş, test edilmiş trend kuralı, birlikte hareket edenler
export default function PortfolioHealth() {
  const { t, td } = useLang();
  const q = useData("health", "/portfolio/health", { refetchInterval: 300_000 });
  const d = q.data;
  const rows = d?.pozisyonlar || [];
  return <div className="kp-page">
    <PageHeader title={t("Portföy sağlığı")} subtitle={t("Tek ekranda: neye ne kadar bağlısın, tepeden ne kadar düştün, hangileri aslında aynı pozisyon.")} />
    <div className="mb-4"><RegimeStrip /></div>
    <div className="mb-4"><SizeCalc /></div>
    <div className="mb-4"><StressCard /></div>
    <div className="mb-4"><UsBook /></div>
    {q.isLoading ? <div className="kp-skel h-40" aria-busy="true" /> : !rows.length ? (
      <K.Card title={t("Açık pozisyon yok")}><p className="kp-note m-0">{t("Portföyüm'e pozisyon ekleyince burada sağlık özeti çıkar.")}</p></K.Card>
    ) : <>
      {d.uyarilar?.length ? <K.Callout tone="warn" title={t("{n} dikkat noktası", { n: d.uyarilar.length })}>
        <ul className="m-0 pl-5">{d.uyarilar.map((w) => <li key={w}>{td(w)}</li>)}</ul>
      </K.Callout> : <K.Callout tone="info" title={t("Belirgin sorun yok")}>{t("Yoğunlaşma, birlikte hareket eden çift ya da stopsuz pozisyon görünmüyor.")}</K.Callout>}
      <K.Card title={`${t("Pozisyonlar")}${d.toplam_tl ? ` · ${t("toplam")} ≈ ₺${U.fmtNum(d.toplam_tl, 0)}` : ""}`}>
        <K.DataTable rows={rows} rowKey="id" columns={[
          { key: "kod", label: t("Kod"), render: (x) => <K.Ticker symbol={x.kod} logo={{ code: x.kod, market: x.piyasa }} /> },
          { key: "agirlik_yuzde", label: t("Ağırlık"), num: true, strong: true, render: (x) => (x.agirlik_yuzde == null ? "—" : `%${U.fmtNum(x.agirlik_yuzde, 1)}`) },
          { key: "getiri_yuzde", label: t("Maliyete göre"), num: true, render: (x) => <span className={tone(x.getiri_yuzde)}>{pct(x.getiri_yuzde)}</span> },
          { key: "tepeden_yuzde", label: t("Tepeden"), num: true, render: (x) => <span className={x.tepeden_yuzde <= -10 ? "kp-num-down" : ""}>{pct(x.tepeden_yuzde)}</span> },
          { key: "trend", label: t("Trend kuralı"), mobile: false, render: (x) => !x.trend ? <span className="text-t-3">{t("yalnız kripto")}</span>
            : x.trend.trendde ? <span className="kp-num-up">{t("trendde · çıkış {p}", { p: px(x.trend.alt10) })}</span>
            : <span className="kp-num-down">{t("dışarıda (10 gün dibi {p})", { p: px(x.trend.alt10) })}</span> },
          { key: "stop", label: "Stop", num: true, mobile: false, render: (x) => (x.stop == null ? t("yok") : px(x.stop)) },
        ]} />
        <p className="kp-note">{t("Ağırlık TL karşılığıyla (USD/TRY {fx}). \"Tepeden\": aldığından beri görülen en yüksek günlük kapanışa göre. Trend kuralı geçmiş testte işe yarayan tek kural; yalnız kriptoda test edildi. Kapanış fiyatları, oluşmakta olan mum sayılmaz.",
          { fx: d.usdtry ? U.fmtNum(d.usdtry, 2) : "—" })}</p>
      </K.Card>
      {!!d.korelasyon?.length && <K.Card title={t("Birlikte hareket edenler")}>
        <ul className="m-0 pl-5 text-t-2">{d.korelasyon.map((c) => <li key={c.a + c.b}>{c.a} – {c.b}: {t("90 günlük korelasyon {r}. Biri düşerken diğeri de düşer; risk hesabında tek pozisyon say.", { r: U.fmtNum(c.r, 2) })}</li>)}</ul>
      </K.Card>}
    </>}
  </div>;
}
