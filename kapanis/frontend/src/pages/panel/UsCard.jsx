import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { sendAction } from "@/lib/actions";
import { relDay } from "@/lib/dsmap";
import { Segmented } from "@/components/kp";
import { useLang } from "@/lib/i18n";
import { useAuth } from "@/context/AuthContext";
import api, { formatApiErrorDetail } from "@/lib/api";

// Hisse kartı (ABD ve BIST): karar desteği. Hiçbir alan AL/SAT demez; her sayının kaynağı ve tarihi altta yazar.
const TONE = { "GÜÇLÜ": "kp-num-up", ZAYIF: "kp-num-down", YUKARI: "kp-num-up", "AŞAĞI": "kp-num-down", "YÜKSEK": "kp-num-down", ORTA: "text-wait",
  "DÜŞÜK": "kp-num-up", PAHALI: "kp-num-down", UCUZ: "kp-num-up" };
const MARKETS = ["ABD", "BIST"];
const sign = (v, suffix = "") => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${U.fmtNum(Math.abs(v), 1)}${suffix}`);
const val = (v, d = 1) => (v == null ? "—" : U.fmtNum(v, d));

function Label({ v }) {
  const { t } = useLang();
  return <b className={TONE[v] || "text-t-1"}>{v ? t(v) : "—"}</b>;
}

function Line({ label, children }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-hairline py-2 last:border-0">
      <span className="text-sm text-t-3">{label}</span>
      <span className="text-right text-sm text-t-1">{children}</span>
    </div>
  );
}

function Card({ c }) {
  const { t, td } = useLang();
  const us = c.piyasa !== "BIST";
  const g = c.guc, e = c.bilanco, r = c.revizyon, v = c.degerleme, s = c.son_bilanco, tr = c.trend;
  const rc = s?.tepki;
  const money = us ? `$${U.fmtNum(c.fiyat, 2)}` : `₺${U.fmtNum(c.fiyat, 2)}`;
  const points = t(" puan");
  return (
    <div className="kp-col" data-testid="us-card" data-market={c.piyasa || "ABD"}>
      <div className="kp-grid kp-g-4">
        <K.StatCard label={t("Fiyat")} value={money} sub={[c.sektor, c.endustri].filter(Boolean).join(" / ") || "—"} />
        <K.StatCard label={t("Temel puan")} value={`${c.temel.skor}/100`} sub={t(c.temel.durum)} />
        <K.StatCard label={t("Sonraki bilanço")} value={e.gun == null ? t("bilinmiyor") : e.gun < 0 ? t("açıklanmadı") : t("{n} gün", { n: e.gun })}
          tone={e.risk === "YÜKSEK" ? "down" : undefined} sub={`risk ${t(e.risk)}${e.tarih ? ` · ${e.tarih}` : ""}`} />
        <K.StatCard label={t("Değerleme (kaba)")} value={t(v.etiket)} tone={v.etiket === "PAHALI" ? "down" : v.etiket === "UCUZ" ? "up" : undefined}
          sub={us ? t("ileri F/K {a} · PEG {b}", { a: val(v.ileri_fk), b: val(v.peg, 2) }) : t("F/K {a} · PD/DD {b}", { a: val(v.fk), b: val(v.pd_dd, 2) })} />
      </div>

      {c.dikkat?.length > 0 && (
        <K.Callout tone="warn" title={t("{n} dikkat noktası", { n: c.dikkat.length })}>
          <ul className="m-0 pl-5">{c.dikkat.map((x) => <li key={x}>{td(x)}</li>)}</ul>
        </K.Callout>
      )}

      <div className="kp-grid kp-g-2">
        <K.Card title={t("Trend ve güç")}>
          <Line label={us ? t("Günlük / haftalık / aylık") : t("Günlük / haftalık")}>{(us ? ["günlük", "haftalık", "aylık"] : ["günlük", "haftalık"]).map((k) => t(tr[k] || "—")).join(" · ")}</Line>
          <Line label={t("Ortalamalar")}>{td(tr.hizalama)}</Line>
          <Line label={t("52 hafta zirvesine uzaklık")}>%{U.fmtNum(tr.zirveye_uzaklik_yuzde, 1)}</Line>
          {us ? (
            <>
              <Line label={t("S&P 500'e göre (6 ay)")}>{sign(g.spy_6a, points)} · <Label v={g.spy} /></Line>
              <Line label={t("Nasdaq-100'e göre (6 ay)")}>{sign(g.qqq_6a, points)} · <Label v={g.qqq} /></Line>
              {g.sektor_etf && <Line label={t("Sektöre göre ({etf}, 6 ay)", { etf: g.sektor_etf })}>{sign(g.sektor_6a, points)} · <Label v={g.sektor} /></Line>}
            </>
          ) : (
            <>
              <Line label={t("BIST 100'e göre (6 ay)")}>{sign(g.endeks_6a, points)} · <Label v={g.etiket} /></Line>
              {c.stage && <Line label={t("Haftalık evre")}>{td(c.stage)}</Line>}
            </>
          )}
          <p className="kp-note">{t("Güç: 6 aylık getirinin endeksten farkı. 10 puan üstü GÜÇLÜ, 10 puan altı ZAYIF.")}</p>
        </K.Card>

        <K.Card title={us ? t("Bilanço") : t("Bilanço ve temettü")}>
          <Line label={t("Sonraki bilanço")}>{e.tarih ? `${e.tarih} · ${e.gun >= 0 ? t("{n} gün sonra", { n: e.gun }) : t("tarih geçmiş")}` : t("bilinmiyor")} · risk <Label v={e.risk} /></Line>
          {e.kaynak && <Line label={t("Tarihin kaynağı")}>{td(e.kaynak)}</Line>}
          {us && (rc ? (
            <>
              <Line label={t("Son açıklama")}>{rc.aciklama}</Line>
              <Line label={t("İlk seans tepkisi")}>{sign(rc.tepki_yuzde, "%")} {t("(S&P 500'e göre {x})", { x: sign(rc.spy_gore_yuzde, points) })}</Line>
              <Line label={t("O günden beri")}>{sign(rc.o_gunden_beri_yuzde, "%")} · {t("{n} seans önce", { n: rc.seans_once })}</Line>
            </>
          ) : <Line label={t("Son açıklama")}>{t("SEC kaydında bulunamadı")}</Line>)}
          {us && s?.surpriz_yuzde != null && <Line label={t("EPS sürprizi ({q})", { q: s.ceyrek })}>{sign(s.surpriz_yuzde, "%")}</Line>}
          {!us && <Line label={t("Temettü hak kullanım")}>{c.temettu?.hak_kullanim || t("açıklanmış tarih yok")}</Line>}
          {!us && c.temettu?.odeme && <Line label={t("Temettü ödeme")}>{c.temettu.odeme}</Line>}
          {us ? (
            <p className="kp-note"><b>{t("Bağlamdır, sinyal değildir.")}</b>{" "}
              {t("Geçmiş testte iyi bilanço tepkisinden sonra piyasanın üstünde getiri çıkmadı. Bilançoya 5 gün ve daha az kala açılış boşluğu (gap) riski yüksektir.")}</p>
          ) : (
            <p className="kp-note">{t("Bilançoya 5 gün ve daha az kala açılış boşluğu riski yüksektir. Tarihler Yahoo'dan; kesin tarih için KAP. Geçmiş bilanço tepkisi ve analist tahmin revizyonu BIST için ücretsiz kaynakta yok.")}</p>
          )}
        </K.Card>

        {us && r && (
          <K.Card title={t("Analist tahminleri")}>
            <Line label={t("Kâr tahmini yönü (30 gün)")}><Label v={r.etiket} /></Line>
            <Line label={t("EPS tahmini değişimi")}>{t("30 gün {a} · 90 gün {b}", { a: sign(r.eps_30g_yuzde, "%"), b: sign(r.eps_90g_yuzde, "%") })}</Line>
            <Line label={t("Revizyon sayısı (30 gün)")}>{t("yukarı {a} · aşağı {b}", { a: r.yukari_30g ?? "—", b: r.asagi_30g ?? "—" })}</Line>
            <p className="kp-note">{t("Analistlerin gelecek yıl kâr tahminindeki değişim. Tahmin yönü fiyat yönü demek değildir.")}</p>
          </K.Card>
        )}

        <K.Card title={t("Değerleme")}>
          <Line label={t("Etiket")}><Label v={v.etiket} /></Line>
          {us ? (
            <>
              <Line label={t("İleri F/K")}>{val(v.ileri_fk)}</Line>
              <Line label="PEG">{val(v.peg, 2)}</Line>
            </>
          ) : (
            <>
              <Line label={t("F/K")}>{val(v.fk)}</Line>
              <Line label={t("PD/DD")}>{val(v.pd_dd, 2)}</Line>
              <Line label={t("FD/FAVÖK")}>{val(v.fd_favok)}</Line>
            </>
          )}
          <Line label={t("Serbest nakit akışı verimi")}>{v.fcf_verimi_yuzde == null ? "—" : `%${U.fmtNum(v.fcf_verimi_yuzde, 1)}`}</Line>
          <p className="kp-note"><b>{t("Kaba yön göstergesidir, adil değer hesabı değildir.")}</b>{" "}
            {us ? t("Sabit eşikler: ileri F/K 35 üstü ya da PEG 2,5 üstü PAHALI; ileri F/K 15 altı (PEG 1,5 altı) UCUZ.")
              : t("Sabit eşikler: F/K 25 üstü ya da PD/DD 6 üstü PAHALI; F/K 8 altı (PD/DD 1,5 altı) UCUZ. Enflasyon muhasebesinde F/K dönemden döneme çok oynar.")}</p>
        </K.Card>
      </div>

      <K.Card title={t("Kaynaklar ve denetim izi")}>
        <K.DataTable rows={c.kaynaklar.map((x, i) => ({ veri: td(x.veri), kaynak: td(x.kaynak), tarih: td(x.tarih), _k: i }))} rowKey="_k" columns={[
          { key: "veri", label: t("Veri") }, { key: "kaynak", label: t("Kaynak") }, { key: "tarih", label: t("Tarih / dönem") },
        ]} />
        <p className="kp-note">{t("Üretildi {z}", { z: String(c.uretildi).slice(0, 16).replace("T", " ") })}{c.kod ? ` · ${t("kod sürümü {k}", { k: c.kod })}` : ""}.{" "}
          {t("Her kart sunucuda denetim kaydına yazılır. Karar desteğidir; AL/SAT önerisi değildir. Hisselerde test edilen zamanlama kurallarının hiçbiri hisseyi elde tutmayı geçemedi.")}</p>
      </K.Card>
    </div>
  );
}

export default function UsCard() {
  const { t, td } = useLang();
  // Sistem sahibi: botun kendi sonucu. Diğer hesaplar: kendi kartı (günde 10), yalnız o hesaba görünür.
  const { owner } = useAuth();
  const q = useData(owner ? ["sonuclar", "temel"] : ["stock-card"], owner ? "/sonuclar/temel" : "/stock-card", LIVE);
  const [params] = useSearchParams();
  const [market, setMarket] = useState(params.get("piyasa") === "BIST" ? "BIST" : "ABD");
  const [kod, setKod] = useState((params.get("kod") || "").toUpperCase());
  const [asked, setAsked] = useState(null);
  const d = q.data || {};
  const waiting = asked && (!d.zaman || new Date(d.zaman).getTime() < asked - 2000);
  const run = async () => {
    const code = kod.trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.-]{0,6}$/.test(code)) return toast.error(market === "ABD" ? t("ABD hisse kodu yaz (ör. NVDA).") : t("BIST hisse kodu yaz (ör. THYAO)."));
    if (owner) {
      if (await sendAction("fundamentals.request", { kod: code, piyasa: market }, t("{k} kartı hazırlanıyor.", { k: code }))) setAsked(Date.now());
      return;
    }
    try {
      await api.post("/stock-card", { kod: code, piyasa: market });
      toast.success(t("{k} kartı hazırlanıyor.", { k: code }));
      setAsked(Date.now());
    } catch (e) {
      toast.error(td(formatApiErrorDetail(e.response?.data?.detail)) || t("Kart hazırlanamadı"));
    }
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
      <PageHeader title={t("Hisse kartı")} subtitle={t("Tek ekranda bir hisse: trend, endekse göre güç, bilanço riski, temel puan, değerleme. Karar desteği; sinyal değil.")} />
      <K.Card title={t("Hisse seç")}>
        <div className="flex flex-wrap items-end gap-3">
          <Segmented ariaLabel={t("Piyasa")} value={market} onChange={setMarket} options={MARKETS.map((m) => ({ value: m, label: t(m) }))} />
          <K.Field label={t("Kod")}><K.TextInput value={kod} placeholder={market === "ABD" ? "NVDA, MSFT, JPM" : "THYAO, ASELS, BIMAS"} onChange={(e) => setKod(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()} data-testid="us-card-input" /></K.Field>
          <K.Button variant="primary" onClick={run} disabled={!!waiting} data-testid="us-card-run">{waiting ? t("Hazırlanıyor…") : t("Kartı getir")}</K.Button>
        </div>
        <p className="kp-note">{t("Veriler istek anında çekilir. ABD: SEC (resmi bilanço ve açıklama zamanı), Yahoo (analist tahminleri, takvim). BIST: İş Yatırım mali tabloları, Yahoo (fiyat ~15 dk gecikmeli, takvim). Hazırlanması 10–40 saniye sürer.")}{" "}
          {owner ? "Telegram: /abd kart NVDA · /bist kart THYAO" : t("Günde 10 kart isteyebilirsin.")}</p>
        {waiting && <p className="kp-note" aria-busy="true">{t("Bot verileri topluyor…")}</p>}
        {!waiting && d.hata && <K.Callout tone="warn" title={t("Kart hazırlanamadı")}>{td(d.hata)}</K.Callout>}
      </K.Card>
      {card ? (
        <>
          <h2 className="kp-card__title" style={{ margin: "1.5rem 0 1rem" }}>{card.hisse} · {t(card.piyasa || "ABD")} · {relDay(d.zaman)}</h2>
          <Card c={card} />
        </>
      ) : !waiting && !d.hata && (
        <K.Card title={t("Henüz kart yok")}><p className="kp-note m-0">{t("Piyasayı seç, kodu yaz, \"Kartı getir\"e bas. Son istenen kart burada kalır.")}</p></K.Card>
      )}
    </div>
  );
}
