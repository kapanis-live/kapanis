import { Link, useNavigate } from "react-router-dom";
import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { chartHref } from "@/components/AssetLogo";
import { marketRows, istTime, MARKET_UI, logo } from "@/lib/dsmap";
import { dayLabel } from "@/lib/portfolio";
import { useLang } from "@/lib/i18n";

const TONE = { up: "up", down: "down", wait: "warn", info: "info" };
function feedKind(text) {
  if (/karar/i.test(text)) return "Sinyal";
  if (/kapı/i.test(text)) return "Kapı";
  if (/BIST aday/i.test(text)) return "Aday";
  if (/veri|TR$/i.test(text)) return "Takvim";
  return "Not";
}

function BtcCard() {
  const { t } = useLang();
  const navigate = useNavigate();
  const q = useData(["candles", "BTC-USDT"], "/candles/BTC-USDT", { retry: false, refetchInterval: 60_000 });
  const c = (q.data?.candles || []).slice(-48).map((k) => ({ t: new Date(k.t).getTime(), o: k.o, h: k.h, l: k.l, c: k.c, v: k.v }));
  if (c.length < 2) return null;
  const last = c[c.length - 1].c;
  const ref = c.length > 24 ? c[c.length - 25].c : c[0].c;
  return (
    <K.Card title={t("BTC · 1 saat")} actions={<K.Button variant="ghost" onClick={() => navigate(chartHref("BTC", "KRIPTO"))}>{t("Grafiği aç")}</K.Button>}>
      <div className="kp-sighead" style={{ marginBottom: "0.75rem" }}>
        <span style={{ fontSize: "1.875rem", fontWeight: 700 }}>{U.fmtPrice(last, "USD", 2)}</span>
        <K.ChangeBadge value={(last / ref - 1) * 100} label={t("24 sa")} />
      </div>
      <K.MiniChart candles={c} height={150} symbol="BTC" />
      <p className="kp-note">{t("Son {n} mum · İstanbul saati. Son mum kapanmamış olabilir.", { n: c.length })}</p>
    </K.Card>
  );
}

export default function Overview() {
  const { t, lang } = useLang();
  const navigate = useNavigate();
  const q = useData("overview", "/overview");
  const extras = useData("extras", "/extras", LIVE);
  const macro = useData("macro", "/macro");
  const today = new Date().toLocaleString(lang === "en" ? "en-GB" : "tr-TR", { timeZone: "Europe/Istanbul", weekday: "long", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
  return (
    <DataView query={q} loadingText={t("Panel özeti hazırlanıyor…")}>
      {(d) => {
        const ex = extras.data || {};
        const markets = marketRows(ex.portfoy);
        const usd = ex.usdtry;
        const totalTl = usd ? markets.reduce((a, m) => a + (m.cur === "TRY" ? m.value : m.value * usd), 0) : null;
        const tl = ex.takip_listesi?.piyasalar || {};
        const movers = Object.entries(tl).flatMap(([m, rs]) => rs.filter((r) => !r.hata && r.gun_yuzde != null)
          .map((r) => ({ symbol: r.kod, price: r.fiyat, cur: m === "BIST" ? "TRY" : "USD", change: r.gun_yuzde, market: m })))
          .sort((a, b) => b.change - a.change);
        const moverItems = (list) => list.map((r) => ({ ...r, name: t(MARKET_UI[r.market]?.label), logo: logo(r.symbol, r.market) }));
        const m = Array.isArray(macro.data) ? macro.data[0] : macro.data;
        const fresh = (d.veri_durumu || []).map((r) => ({ source: r.kaynak, status: r.durum, age: r.yas, note: r.not, gate: r.kapiyi_etkiler }));
        const gateBad = fresh.filter((r) => r.gate && (r.status === "bayat" || r.status === "yok"));
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title={t("Genel bakış")} subtitle={`${today} (${t("İstanbul")})`} />
            {gateBad.length > 0 && (
              <K.Callout tone="down" title={t("Karar kapısını etkileyen veri eski")}>
                {gateBad.map((r) => r.source).join(", ")}: {t("veri tazelenene kadar yeni AL verilmez.")}
              </K.Callout>
            )}
            <div className="kp-grid kp-g-5">
              <K.StatCard label={`${t("Kripto")} · ${t(dayLabel("KRIPTO"))} ${t("K/Z")}`} value={U.fmtSignedMoney(d.day_pnl || 0, "USD")}
                tone={d.day_pnl >= 0 ? "up" : "down"} change={d.day_pnl_pct} sub={`${markets.find((x) => x.key === "KRIPTO")?.count || 0} coin`} />
              <K.StatCard label={`BIST · ${t(dayLabel("BIST")).toLowerCase()} ${t("K/Z")}`} value={U.fmtSignedMoney(d.bist_day_pnl || 0, "TRY")}
                tone={(d.bist_day_pnl || 0) >= 0 ? "up" : "down"} change={d.bist_day_pnl_pct} sub={`${markets.find((x) => x.key === "BIST")?.count || 0} ${t("hisse")}`} />
              <K.StatCard label={t("Açık risk")} value={`${U.fmtNum(d.open_r || 0, 1)} R`} sub={`${d.open_positions} ${t("pozisyon")}`} />
              <K.StatCard label={t("Kurulu alarm")} value={String(d.armed_alerts)} sub={t("kapanış bekliyor")} />
              <K.StatCard label={t("Bekleyen karar")} value={String(d.pending_decisions)} sub={d.pending_decisions ? t("Sinyaller sayfasında") : t("yok")} />
            </div>
            <div className="kp-grid kp-split">
              <div className="kp-col">
                {markets.length > 0 && (
                  <K.Card title={t("Portföy nabzı")} actions={<K.Button variant="ghost" onClick={() => navigate("/app/portfoy")}>{t("Portföye git")}</K.Button>}>
                    <K.PulseList items={markets.map((x) => ({ ...x, label: t(x.label) }))} />
                    <p className="kp-note">
                      {totalTl != null ? t("Toplam ₺ karşılığı {a} · 1 $ = ₺{b}", { a: U.fmtPrice(totalTl, "TRY", 0), b: U.fmtNum(usd, 2) }) : t("Rakamları bot kodla hesaplar.")}
                    </p>
                  </K.Card>
                )}
                {movers.length > 0 && (
                  <K.Card title={t("Takip listesi")} actions={<K.Button variant="ghost" onClick={() => navigate("/app/takip")}>{t("Tümü")}</K.Button>}>
                    <div className="kp-grid kp-g-2">
                      <div><p className="kp-sub">{t("En çok yükselen 3")}</p>
                        <K.MoverList items={moverItems(movers.slice(0, 3))} onOpen={(i) => navigate(chartHref(i.symbol, i.market))} /></div>
                      <div><p className="kp-sub">{t("En çok düşen 3")}</p>
                        <K.MoverList items={moverItems(movers.slice(-3).reverse())} onOpen={(i) => navigate(chartHref(i.symbol, i.market))} /></div>
                    </div>
                  </K.Card>
                )}
                <K.Card title={t("Öne çıkanlar")}>
                  <K.FeedList items={(d.highlights || []).map((h) => ({ time: istTime(d.updated_at), kind: t(feedKind(h.text)), tone: TONE[h.tone] || "flat", title: h.text }))} />
                </K.Card>
              </div>
              <div className="kp-col">
                <BtcCard />
                {m && (
                  <K.Card title={t("Makro rejim")}>
                    <K.RegimeGauge score={m.regime_score ?? d.regime_score} label={m.regime_label}
                      components={(m.components || []).map((c) => ({ name: c.name, value: Math.max(-1, Math.min(1, Math.round(c.score || 0))), detail: c.value }))}
                      note={t("Rüzgârı anlatır, tahmin değildir. Kaynak: FRED.")} />
                  </K.Card>
                )}
                {(ex.takvim || []).length > 0 && (
                  <K.Card title={t("Yaklaşan şirket olayları")}>
                    <K.FeedList items={ex.takvim.slice(0, 8).map((i) => ({
                      time: `${i.tarih.slice(8, 10)}.${i.tarih.slice(5, 7)}`, kind: t(i.etiket), tone: i.tur === "bilanco" ? "warn" : "info",
                      symbol: i.kod, title: i.portfoyde ? t("Portföyünde") : t("Takip listende"),
                      detail: i.tur === "bilanco" ? t("Bilanço günü fiyat sert oynayabilir.") : undefined,
                    }))} />
                    <p className="kp-note">{t("Tarihler Yahoo'dan; kesin tarih için KAP / şirket. Bir gün önce Telegram'dan hatırlatırım.")}{" "}
                      <Link to="/app/takvim" className="kp-link">{t("Tüm takvim →")}</Link></p>
                  </K.Card>
                )}
                <K.Card title={t("KAP bildirimleri")}>
                  {(ex.kap || []).length ? (
                    <K.FeedList items={ex.kap.slice(0, 6).map((k) => ({
                      time: String(k.zaman || "").slice(11, 16), kind: "KAP", tone: "info", symbol: (k.kodlar || []).join(", "),
                      title: k.konu, detail: k.ozet,
                    }))} />
                  ) : <p className="kp-note">{t("Bugün portföyündeki hisseler için KAP bildirimi yok. Yeni bildirim gelince 15 dk içinde Telegram'dan haber veririm.")}</p>}
                </K.Card>
                {fresh.length > 0 && <K.Card title={t("Veri güncelliği")}><K.FreshnessList items={fresh} /></K.Card>}
              </div>
            </div>
          </div>
        );
      }}
    </DataView>
  );
}
