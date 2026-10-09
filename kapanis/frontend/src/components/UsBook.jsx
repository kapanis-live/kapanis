import { useState } from "react";
import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { sendAction } from "@/lib/actions";
import { relDay } from "@/lib/dsmap";
import { useLang } from "@/lib/i18n";

// Portföy sağlığı: ABD hisselerinin ortak yanı (sektör, tema, birlikte hareket, beta, senaryolar). Bot hesaplar.
const pct = (v, d = 1) => (v == null ? "—" : `%${U.fmtNum(v, d)}`);
const signed = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`);
const RULER = "Senaryo cetvelidir, tahmin değildir.";

function Bars({ rows }) {
  return (
    <div className="flex flex-col gap-2">
      {rows.map(([name, value, note]) => (
        <div key={name}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-t-1">{name}{note ? <span className="text-t-3"> · {note}</span> : null}</span>
            <b className="num text-t-1">{pct(value)}</b>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-raised" aria-hidden="true">
            <div className="h-full rounded-full bg-brand" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function UsBook() {
  const { t, td } = useLang();
  const q = useData(["sonuclar", "abd_portfoy"], "/sonuclar/abd_portfoy", LIVE);
  const [asked, setAsked] = useState(null);
  const d = q.data || {};
  const waiting = asked && (!d.zaman || new Date(d.zaman).getTime() < asked - 2000);
  const run = async () => {
    if (await sendAction("us.portfolio", {}, t("ABD portföyü hesaplanıyor."))) setAsked(Date.now());
  };
  const action = <K.Button variant="secondary" onClick={run} disabled={!!waiting} data-testid="us-book-run">{waiting ? t("Hesaplanıyor…") : d.zaman ? t("Yenile") : t("Hesapla")}</K.Button>;
  const ready = !waiting && d.zaman && !d.hata && !d.bos && d.agirlik_yuzde;
  const swings = t("1 = endeks kadar oynar");
  return (
    <K.Card title={t("ABD hisseleri: ortak risk")} actions={action}>
      <p className="m-0 text-t-2">{t("Yedi ayrı hisse, aynı hikâyeye bağlıysa tek pozisyon gibi davranır. Bu bölüm botun portföyündeki ABD hisselerini sektör, tema, birlikte hareket ve dört senaryo üzerinden gösterir. Öneri içermez.")}</p>
      {waiting && <p className="kp-note" aria-busy="true">{t("Bot bir yıllık fiyatları ve sektörleri topluyor (10–40 sn)…")}</p>}
      {!waiting && d.hata && <K.Callout tone="warn" title={t("Hesaplanamadı")}>{d.hata}</K.Callout>}
      {!waiting && d.bos && <p className="kp-note">{t("Botta açık ABD pozisyonu yok.")} Telegram: /portfoy ekle NVDA 2 230</p>}
      {!waiting && !d.zaman && <p className="kp-note">{t("Henüz hesaplanmadı. \"Hesapla\"ya bas; sonuç burada kalır.")}</p>}
      {ready && (
        <div className="mt-4 flex flex-col gap-5" data-testid="us-book">
          <div className="kp-grid kp-g-4">
            <K.StatCard label={t("ABD toplamı")} value={`$${U.fmtNum(d.toplam_usd, 0)}`} sub={`${Object.keys(d.agirlik_yuzde).length} ${t("hisse")} · ${relDay(d.zaman)}`} />
            <K.StatCard label="Beta (S&P 500)" value={d.beta?.SPY ?? "—"} sub={swings} />
            <K.StatCard label="Beta (Nasdaq-100)" value={d.beta?.QQQ ?? "—"} sub={swings} />
            <K.StatCard label={t("Ortalama korelasyon")} value={d.korelasyon?.ortalama ?? "—"} sub={t("1 yıl, günlük; 1'e yakın = birlikte hareket")} />
          </div>

          {d.dikkat?.length > 0 && (
            <K.Callout tone="warn" title={t("{n} yoğunlaşma notu", { n: d.dikkat.length })}>
              <ul className="m-0 pl-5">{d.dikkat.map((x) => <li key={x}>{x}</li>)}</ul>
            </K.Callout>
          )}

          <div className="kp-grid kp-g-2">
            <section>
              <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>{t("Hisse ağırlıkları")}</h3>
              <Bars rows={Object.entries(d.agirlik_yuzde).map(([k, v]) => [k, v])} />
            </section>
            <section>
              <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>{t("Sektör dağılımı")}</h3>
              <Bars rows={Object.entries(d.sektor_yuzde).map(([k, v]) => [k, v])} />
            </section>
          </div>

          <section>
            <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>{t("Tema dağılımı")}</h3>
            {Object.keys(d.tema || {}).length
              ? <Bars rows={Object.entries(d.tema).map(([k, v]) => [t(k), v.agirlik_yuzde, v.hisseler.join(", ")])} />
              : <p className="kp-note m-0">{t("Tanımlı temalarda hisse yok.")}</p>}
            <p className="kp-note">{t("Bir hisse birden çok temada olabilir, toplam %100'ü geçer. Temalar elle tanımlı listelerdir: mega teknoloji, yarı iletken, yapay zekâ, yapay zekâ enerjisi, banka/finans, savunmacı.")}</p>
          </section>

          {d.korelasyon?.en_bagli?.length > 0 && (
            <section>
              <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>{t("Birlikte hareket")}</h3>
              <K.DataTable rows={[...d.korelasyon.en_bagli.map((x) => ({ ...x, tur: t("en bağlı") })), ...(d.korelasyon.en_bagimsiz || []).map((x) => ({ ...x, tur: t("en bağımsız") }))]
                .map((x, i) => ({ ...x, _k: i }))} rowKey="_k" columns={[
                { key: "cift", label: t("Çift"), render: (x) => <b>{x.cift}</b> },
                { key: "korelasyon", label: t("Korelasyon"), num: true, render: (x) => U.fmtNum(x.korelasyon, 2) },
                { key: "tur", label: "" },
              ]} />
            </section>
          )}

          <section>
            <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>{t("Senaryolar")}</h3>
            <K.DataTable rows={(d.senaryolar || []).map((x, i) => ({ ...x, _k: i }))} rowKey="_k" columns={[
              { key: "senaryo", label: t("Senaryo"), render: (x) => <span><b>{t(x.senaryo)}</b><br /><span className="text-xs text-t-3">{t(RULER)}</span></span> },
              { key: "portfoy_yuzde", label: t("Portföy"), num: true, strong: true, render: (x) => <span className={x.portfoy_yuzde < 0 ? "kp-num-down" : "kp-num-up"}>{signed(x.portfoy_yuzde)}</span> },
              { key: "tutar_usd", label: t("Tutar"), num: true, render: (x) => `${x.tutar_usd < 0 ? "−" : "+"}$${U.fmtNum(Math.abs(x.tutar_usd), 0)}` },
              { key: "en", label: t("En çok etkilenen"), mobile: false, render: (x) => (x.en_cok_etkilenen || []).map(([m, code]) => `${code} ${signed(m)}`).join(" · ") || "—" },
            ]} />
            <p className="kp-note">{t("Tek etkenli hesap: son bir yılın günlük birlikte hareketinden. Şu an VIX {vix}, 10 yıllık faiz %{tnx}. Gerçek bir satışta etkenler birlikte hareket eder ve duyarlılıklar değişir; satırlar toplanmaz.",
              { vix: U.fmtNum(d.vix, 1), tnx: U.fmtNum(d.tnx, 2) })}</p>
          </section>

          {d.kaynaklar?.length > 0 && (
            <p className="kp-note m-0">{t("Kaynaklar")}: {d.kaynaklar.map((x) => `${td(x.veri)}: ${td(x.kaynak)} (${td(x.tarih)})`).join(" · ")}
              {d.kapsam_yuzde < 99.9 ? ` · ${t("beta ve senaryolar portföyün %{n}'ini kapsar", { n: U.fmtNum(d.kapsam_yuzde, 0) })}` : ""}</p>
          )}
        </div>
      )}
    </K.Card>
  );
}
