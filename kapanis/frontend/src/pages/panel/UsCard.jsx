import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { sendAction } from "@/lib/actions";
import { relDay } from "@/lib/dsmap";
import { Segmented } from "@/components/kp";

// Hisse kartı (ABD ve BIST): karar desteği. Hiçbir alan AL/SAT demez; her sayının kaynağı ve tarihi altta yazar.
const TONE = { "GÜÇLÜ": "kp-num-up", ZAYIF: "kp-num-down", YUKARI: "kp-num-up", "AŞAĞI": "kp-num-down", "YÜKSEK": "kp-num-down", ORTA: "text-wait",
  "DÜŞÜK": "kp-num-up", PAHALI: "kp-num-down", UCUZ: "kp-num-up" };
const MARKETS = [{ value: "ABD", label: "ABD" }, { value: "BIST", label: "BIST" }];
const sign = (v, suffix = "") => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${U.fmtNum(Math.abs(v), 1)}${suffix}`);
const val = (v, d = 1) => (v == null ? "—" : U.fmtNum(v, d));
const Label = ({ v }) => <b className={TONE[v] || "text-t-1"}>{v || "—"}</b>;

function Line({ label, children }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-hairline py-2 last:border-0">
      <span className="text-sm text-t-3">{label}</span>
      <span className="text-right text-sm text-t-1">{children}</span>
    </div>
  );
}

function Card({ c }) {
  const us = c.piyasa !== "BIST";
  const g = c.guc, e = c.bilanco, r = c.revizyon, v = c.degerleme, s = c.son_bilanco, t = c.trend;
  const rc = s?.tepki;
  const money = us ? `$${U.fmtNum(c.fiyat, 2)}` : `₺${U.fmtNum(c.fiyat, 2)}`;
  return (
    <div className="kp-col" data-testid="us-card" data-market={c.piyasa || "ABD"}>
      <div className="kp-grid kp-g-4">
        <K.StatCard label="Fiyat" value={money} sub={[c.sektor, c.endustri].filter(Boolean).join(" / ") || "—"} />
        <K.StatCard label="Temel puan" value={`${c.temel.skor}/100`} sub={c.temel.durum} />
        <K.StatCard label="Sonraki bilanço" value={e.gun == null ? "bilinmiyor" : e.gun < 0 ? "açıklanmadı" : `${e.gun} gün`}
          tone={e.risk === "YÜKSEK" ? "down" : undefined} sub={`risk ${e.risk}${e.tarih ? ` · ${e.tarih}` : ""}`} />
        <K.StatCard label="Değerleme (kaba)" value={v.etiket} tone={v.etiket === "PAHALI" ? "down" : v.etiket === "UCUZ" ? "up" : undefined}
          sub={us ? `ileri F/K ${val(v.ileri_fk)} · PEG ${val(v.peg, 2)}` : `F/K ${val(v.fk)} · PD/DD ${val(v.pd_dd, 2)}`} />
      </div>

      {c.dikkat?.length > 0 && (
        <K.Callout tone="warn" title={`${c.dikkat.length} dikkat noktası`}>
          <ul className="m-0 pl-5">{c.dikkat.map((x) => <li key={x}>{x}</li>)}</ul>
        </K.Callout>
      )}

      <div className="kp-grid kp-g-2">
        <K.Card title="Trend ve güç">
          <Line label={us ? "Günlük / haftalık / aylık" : "Günlük / haftalık"}>{(us ? ["günlük", "haftalık", "aylık"] : ["günlük", "haftalık"]).map((k) => t[k] || "—").join(" · ")}</Line>
          <Line label="Ortalamalar">{t.hizalama}</Line>
          <Line label="52 hafta zirvesine uzaklık">%{U.fmtNum(t.zirveye_uzaklik_yuzde, 1)}</Line>
          {us ? (
            <>
              <Line label="S&P 500'e göre (6 ay)">{sign(g.spy_6a, " puan")} · <Label v={g.spy} /></Line>
              <Line label="Nasdaq-100'e göre (6 ay)">{sign(g.qqq_6a, " puan")} · <Label v={g.qqq} /></Line>
              {g.sektor_etf && <Line label={`Sektöre göre (${g.sektor_etf}, 6 ay)`}>{sign(g.sektor_6a, " puan")} · <Label v={g.sektor} /></Line>}
            </>
          ) : (
            <>
              <Line label="BIST 100'e göre (6 ay)">{sign(g.endeks_6a, " puan")} · <Label v={g.etiket} /></Line>
              {c.stage && <Line label="Haftalık evre">{c.stage}</Line>}
            </>
          )}
          <p className="kp-note">Güç: 6 aylık getirinin endeksten farkı. 10 puan üstü GÜÇLÜ, 10 puan altı ZAYIF.</p>
        </K.Card>

        <K.Card title={us ? "Bilanço" : "Bilanço ve temettü"}>
          <Line label="Sonraki bilanço">{e.tarih ? `${e.tarih} · ${e.gun >= 0 ? `${e.gun} gün sonra` : "tarih geçmiş"}` : "bilinmiyor"} · risk <Label v={e.risk} /></Line>
          {e.kaynak && <Line label="Tarihin kaynağı">{e.kaynak}</Line>}
          {us && (rc ? (
            <>
              <Line label="Son açıklama">{rc.aciklama}</Line>
              <Line label="İlk seans tepkisi">{sign(rc.tepki_yuzde, "%")} (S&P 500'e göre {sign(rc.spy_gore_yuzde, " puan")})</Line>
              <Line label="O günden beri">{sign(rc.o_gunden_beri_yuzde, "%")} · {rc.seans_once} seans önce</Line>
            </>
          ) : <Line label="Son açıklama">SEC kaydında bulunamadı</Line>)}
          {us && s?.surpriz_yuzde != null && <Line label={`EPS sürprizi (${s.ceyrek})`}>{sign(s.surpriz_yuzde, "%")}</Line>}
          {!us && <Line label="Temettü hak kullanım">{c.temettu?.hak_kullanim || "açıklanmış tarih yok"}</Line>}
          {!us && c.temettu?.odeme && <Line label="Temettü ödeme">{c.temettu.odeme}</Line>}
          {us ? (
            <p className="kp-note"><b>Bağlamdır, sinyal değildir.</b> Geçmiş testte iyi bilanço tepkisinden sonra piyasanın üstünde getiri çıkmadı.
              Bilançoya 5 gün ve daha az kala açılış boşluğu (gap) riski yüksektir.</p>
          ) : (
            <p className="kp-note">Bilançoya 5 gün ve daha az kala açılış boşluğu riski yüksektir. Tarihler Yahoo'dan; kesin tarih için KAP.
              Geçmiş bilanço tepkisi ve analist tahmin revizyonu BIST için ücretsiz kaynakta yok.</p>
          )}
        </K.Card>

        {us && r && (
          <K.Card title="Analist tahminleri">
            <Line label="Kâr tahmini yönü (30 gün)"><Label v={r.etiket} /></Line>
            <Line label="EPS tahmini değişimi">30 gün {sign(r.eps_30g_yuzde, "%")} · 90 gün {sign(r.eps_90g_yuzde, "%")}</Line>
            <Line label="Revizyon sayısı (30 gün)">yukarı {r.yukari_30g ?? "—"} · aşağı {r.asagi_30g ?? "—"}</Line>
            <p className="kp-note">Analistlerin gelecek yıl kâr tahminindeki değişim. Tahmin yönü fiyat yönü demek değildir.</p>
          </K.Card>
        )}

        <K.Card title="Değerleme">
          <Line label="Etiket"><Label v={v.etiket} /></Line>
          {us ? (
            <>
              <Line label="İleri F/K">{val(v.ileri_fk)}</Line>
              <Line label="PEG">{val(v.peg, 2)}</Line>
            </>
          ) : (
            <>
              <Line label="F/K">{val(v.fk)}</Line>
              <Line label="PD/DD">{val(v.pd_dd, 2)}</Line>
              <Line label="FD/FAVÖK">{val(v.fd_favok)}</Line>
            </>
          )}
          <Line label="Serbest nakit akışı verimi">{v.fcf_verimi_yuzde == null ? "—" : `%${U.fmtNum(v.fcf_verimi_yuzde, 1)}`}</Line>
          <p className="kp-note"><b>Kaba yön göstergesidir, adil değer hesabı değildir.</b>{" "}
            {us ? "Sabit eşikler: ileri F/K 35 üstü ya da PEG 2,5 üstü PAHALI; ileri F/K 15 altı (PEG 1,5 altı) UCUZ."
              : "Sabit eşikler: F/K 25 üstü ya da PD/DD 6 üstü PAHALI; F/K 8 altı (PD/DD 1,5 altı) UCUZ. Enflasyon muhasebesinde F/K dönemden döneme çok oynar."}</p>
        </K.Card>
      </div>

      <K.Card title="Kaynaklar ve denetim izi">
        <K.DataTable rows={c.kaynaklar.map((x, i) => ({ ...x, _k: i }))} rowKey="_k" columns={[
          { key: "veri", label: "Veri" }, { key: "kaynak", label: "Kaynak" }, { key: "tarih", label: "Tarih / dönem" },
        ]} />
        <p className="kp-note">Üretildi {String(c.uretildi).slice(0, 16).replace("T", " ")}{c.kod ? ` · kod sürümü ${c.kod}` : ""}. Her kart sunucuda denetim kaydına yazılır.
          Karar desteğidir; AL/SAT önerisi değildir. Hisselerde test edilen zamanlama kurallarının hiçbiri hisseyi elde tutmayı geçemedi.</p>
      </K.Card>
    </div>
  );
}

export default function UsCard() {
  const q = useData(["sonuclar", "temel"], "/sonuclar/temel", LIVE);
  const [params] = useSearchParams();
  const [market, setMarket] = useState(params.get("piyasa") === "BIST" ? "BIST" : "ABD");
  const [kod, setKod] = useState((params.get("kod") || "").toUpperCase());
  const [asked, setAsked] = useState(null);
  const d = q.data || {};
  const waiting = asked && (!d.zaman || new Date(d.zaman).getTime() < asked - 2000);
  const run = async () => {
    const code = kod.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.-]{0,6}$/.test(code)) return toast.error(market === "ABD" ? "ABD hisse kodu yaz (ör. NVDA)." : "BIST hisse kodu yaz (ör. THYAO).");
    if (await sendAction("fundamentals.request", { kod: code, piyasa: market }, `${code} kartı hazırlanıyor.`)) setAsked(Date.now());
  };
  // Hisse tablosundan gelindiyse (?kod=...) kart bir kez kendiliğinden istenir
  const auto = useRef(false);
  useEffect(() => {
    if (params.get("kod") && !auto.current) { auto.current = true; run(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const card = !waiting && d.kart ? d.kart : null;
  return (
    <div className="kp-page">
      <PageHeader title="Hisse kartı" subtitle="Tek ekranda bir hisse: trend, endekse göre güç, bilanço riski, temel puan, değerleme. Karar desteği; sinyal değil." />
      <K.Card title="Hisse seç">
        <div className="flex flex-wrap items-end gap-3">
          <Segmented ariaLabel="Piyasa" value={market} onChange={setMarket} options={MARKETS} />
          <K.Field label="Kod"><K.TextInput value={kod} placeholder={market === "ABD" ? "NVDA, MSFT, JPM" : "THYAO, ASELS, BIMAS"} onChange={(e) => setKod(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()} data-testid="us-card-input" /></K.Field>
          <K.Button variant="primary" onClick={run} disabled={!!waiting} data-testid="us-card-run">{waiting ? "Hazırlanıyor…" : "Kartı getir"}</K.Button>
        </div>
        <p className="kp-note">Veriler istek anında çekilir. ABD: SEC (resmi bilanço ve açıklama zamanı), Yahoo (analist tahminleri, takvim).
          BIST: İş Yatırım mali tabloları, Yahoo (fiyat ~15 dk gecikmeli, takvim). Hazırlanması 10–40 saniye sürer.
          Telegram: /abd kart NVDA · /bist kart THYAO</p>
        {waiting && <p className="kp-note" aria-busy="true">Bot verileri topluyor…</p>}
        {!waiting && d.hata && <K.Callout tone="warn" title="Kart hazırlanamadı">{d.hata}</K.Callout>}
      </K.Card>
      {card ? (
        <>
          <h2 className="kp-card__title" style={{ margin: "1.5rem 0 1rem" }}>{card.hisse} · {card.piyasa || "ABD"} · {relDay(d.zaman)}</h2>
          <Card c={card} />
        </>
      ) : !waiting && !d.hata && (
        <K.Card title="Henüz kart yok"><p className="kp-note m-0">Piyasayı seç, kodu yaz, "Kartı getir"e bas. Son istenen kart burada kalır.</p></K.Card>
      )}
    </div>
  );
}
