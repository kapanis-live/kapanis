import { useState } from "react";
import { toast } from "sonner";
import { K, U } from "@/ds";
import api, { formatApiErrorDetail } from "@/lib/api";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { px } from "@/lib/portfolio";

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`);
const tone = (v) => (v == null ? "" : v >= 0 ? "kp-num-up" : "kp-num-down");

const REGIME_TONE = { TREND_UP: "kp-num-up", TREND_DOWN: "kp-num-down", PANIK: "kp-num-down" };

function RegimeStrip() {
  const q = useData("market-regime", "/market/regime", { refetchInterval: 900_000 });
  if (!q.data) return null;
  return <K.Card title="Piyasa durumu">
    <div className="flex flex-wrap gap-4">{q.data.rejimler.map((r) =>
      <div key={r.piyasa} className="flex flex-col"><span className="text-sm text-t-3">{r.piyasa}</span>
        <b className={REGIME_TONE[r.rejim] || "text-t-1"}>{r.aciklama}</b></div>)}</div>
    <p className="kp-note">{q.data.not}</p>
  </K.Card>;
}

// "Kaç adet alayım?": risk matematiği (portföy × risk %, oynaklık, korelasyon, yoğunlaşma), tahmin değil
function SizeCalc() {
  const [f, setF] = useState({ piyasa: "BIST", kod: "", stop: "", risk: "" });
  const [r, setR] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const run = async () => {
    if (!f.kod.trim()) return toast.error("Kod yaz.");
    setBusy(true);
    try {
      const body = { piyasa: f.piyasa, kod: f.kod.trim() };
      if (String(f.stop).trim()) body.stop = U.parseTr(String(f.stop));
      if (String(f.risk).trim()) body.risk_yuzde = U.parseTr(String(f.risk));
      setR((await api.post("/risk/size", body)).data);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); setR(null); }
    finally { setBusy(false); }
  };
  return <K.Card title="Kaç adet alayım? (risk hesabı)">
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <K.Field label="Piyasa"><K.Select value={f.piyasa} onChange={set("piyasa")} options={[{ value: "BIST", label: "BIST" }, { value: "KRIPTO", label: "Kripto" }, { value: "ABD", label: "ABD" }]} /></K.Field>
      <K.Field label="Kod"><K.TextInput value={f.kod} onChange={set("kod")} placeholder="ASTOR" /></K.Field>
      <K.Field label="Stop" hint="boşsa 2 × ATR"><K.TextInput inputMode="decimal" value={f.stop} onChange={set("stop")} placeholder="0,00" /></K.Field>
      <K.Field label="Risk %" hint="boşsa %1"><K.TextInput inputMode="decimal" value={f.risk} onChange={set("risk")} placeholder="1" /></K.Field>
      <div className="flex items-end"><K.Button variant="primary" disabled={busy} onClick={run}>{busy ? "Hesaplanıyor…" : "Hesapla"}</K.Button></div>
    </div>
    {r && <div className="mt-3 flex flex-col gap-2">
      <p className="m-0 text-lg text-t-1">En fazla <b>{U.fmtNum(r.adet, r.piyasa === "BIST" ? 0 : 6)} adet</b> ({r.para === "TL" ? "₺" : "$"}{U.fmtNum(r.tutar, 2)}) ·
        stop {px(r.stop)} ({r.stop_kaynagi}) · stop kırılırsa kayıp ≈ ₺{U.fmtNum(r.risk_tl, 0)}</p>
      <ul className="m-0 pl-5 text-t-2">{r.satirlar.map((x) => <li key={x}>{x}</li>)}</ul>
      <p className="kp-note">{r.not}</p>
    </div>}
  </K.Card>;
}

// Portföy sağlığı: ağırlık, tepeden düşüş, test edilmiş trend kuralı, birlikte hareket edenler
export default function PortfolioHealth() {
  const q = useData("health", "/portfolio/health", { refetchInterval: 300_000 });
  const d = q.data;
  const rows = d?.pozisyonlar || [];
  return <div className="kp-page">
    <PageHeader title="Portföy sağlığı" subtitle="Tek ekranda: neye ne kadar bağlısın, tepeden ne kadar düştün, hangileri aslında aynı pozisyon." />
    <div className="mb-4"><RegimeStrip /></div>
    <div className="mb-4"><SizeCalc /></div>
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
