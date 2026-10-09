import { Link, useSearchParams } from "react-router-dom";
import { K, U } from "@/ds";
import { usePendingCommands } from "@/lib/useData";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { splitAi, relDay } from "@/lib/dsmap";
import { useLang } from "@/lib/i18n";

const RULE_NAMES = { fk: "F/K koşulu", momentum: "3 aylık göreli getiri koşulu", kalite: "kalite puanı koşulu", veri_eksik: "bilanço/fiyat verisi eksik" };

// Strateji sonucu: seçilenler, neden seçildikleri, elenenler ve verinin tarihi
function WhyCard({ a }) {
  const { t } = useLang();
  const rules = a.rules || {};
  const elim = Object.entries(a.elenen || {}).filter(([, n]) => n > 0);
  return (
    <section className="kp-tile" style={{ gap: "0.75rem", marginBottom: "1rem" }}>
      <h3 className="kp-card__title" style={{ margin: 0 }}>{t("Neden seçildi?")}</h3>
      <K.DataTable rows={a.rows} rowKey="kod" columns={[
        { key: "kod", label: t("Kod"), render: (r) => <b>{r.kod}</b> },
        { key: "kalite", label: t("Kalite /100"), num: true, render: (r) => U.fmtNum(r.kalite, 1) },
        { key: "momentum_goreli", label: t("3 ay (BIST 100’e göre)"), num: true, render: (r) => `${r.momentum_goreli >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(r.momentum_goreli), 2)}` },
        { key: "fk", label: t("F/K"), num: true, render: (r) => (r.fk == null ? t("yok") : U.fmtNum(r.fk, 1)) },
        { key: "birlesik_skor", label: t("Birleşik sıra /100"), num: true, strong: true, render: (r) => U.fmtNum(r.birlesik_skor, 1) },
        { key: "veri", label: t("Veri"), mobile: false, render: (r) => `${r.veri_tarihi ? r.veri_tarihi.slice(8, 10) + "." + r.veri_tarihi.slice(5, 7) : "—"} · ${r.bilanco_donemi || "—"}` },
      ]} />
      <p className="kp-note">
        {t("Koşullar")}: {[rules.fk_max != null && `${t("F/K")} < ${rules.fk_max}`, rules.momentum_min != null && `${t("3 ay")} ≥ %${rules.momentum_min}`,
          rules.quality_min != null && `${t("kalite")} ≥ ${rules.quality_min}`].filter(Boolean).join(" · ") || t("koşul yok")}.
        {" "}{t("{n} hisseden {m} tanesi koşulları geçti; kalite ve momentum sırasının ortalamasıyla sıralandı.", { n: a.universe_count, m: a.gecen ?? a.rows.length })}
      </p>
      {elim.length > 0 && <p className="kp-note">{t("Elenenler")}: {elim.map(([k, n]) => `${n} ${t("hisse")} ${t(RULE_NAMES[k] || k)}`).join(" · ")} {t("(bir hisse birden fazla koşuldan kalabilir).")}</p>}
      <p className="kp-note">{t("Hesap zamanı")} {a.hesap_zamani ? relDay(a.hesap_zamani) : "—"}{a.xu100 ? ` · ${t("o gün BIST 100")} ${U.fmtNum(a.xu100, 2)} (${a.xu100_tarih})` : ""}.{" "}
        {t("Fiyatlar gecikmeli, bilançolar son açıklanan dönem. Puan getiri olasılığı değildir.")}</p>
    </section>
  );
}

export default function MyAnalyses() {
  const { t } = useLang();
  const [params, setParams] = useSearchParams();
  const q = useData("my-analyses", "/analyses", LIVE);
  const rows = q.data || [];
  const selected = rows.find((r) => r.id === params.get("id")) || rows[0];
  const pend = usePendingCommands();
  const waiting = pend.pending.filter((c) => ["analysis.request", "strategy.scan"].includes(c.type));
  return <div className="kp-page">
    <PageHeader title={t("Son Analizlerim")} subtitle={t("Telegram ve panelden istediğin analizler, yalnız kendi hesabında.")} />
    {waiting.length > 0 && <K.Callout tone="info" title={t("{n} istek hazırlanıyor", { n: waiting.length })}>
      {waiting.map((c) => c.type === "strategy.scan" ? t("strateji taraması") : (c.payload?.kodlar || []).join(", ") || t("analiz")).join(" · ")}
      {" "}· {t("sırayla işlenir; ilk BIST 100 taraması birkaç dakika sürebilir. Sonuç hazır olunca burada ve bağlı Telegram’da görünür.")}
    </K.Callout>}
    {q.isLoading ? <p className="kp-note">{t("Analizler yükleniyor…")}</p> : q.isError ?
      <p className="kp-note">{t("Analizler şu an alınamadı.")}</p> : !rows.length ?
      <K.EmptyState icon="chart" title={t("Henüz analiz yok")}>{t("Grafik sayfasında bir kod seçip “Analiz et”e bas.")}</K.EmptyState> :
      <div className="kp-grid kp-split-l">
        <K.Card title={`${t("Kayıtlı analizler")} (${rows.length})`}>
          <div className="flex flex-col gap-2">{rows.map((r) =>
            <button key={r.id} type="button" onClick={() => setParams({ id: r.id })}
              aria-current={selected?.id === r.id ? "true" : undefined}
              className={`rounded-lg border p-3 text-left ${selected?.id === r.id ? "border-strong bg-raised" : "border-hairline hover:bg-raised"}`}>
              <span className="block font-semibold text-t-1">{(r.kodlar || []).join(", ") || t("Analiz")}</span>
              <span className="text-sm text-t-3">{t(r.piyasa || "Piyasa")} · {relDay(r.zaman)}</span>
            </button>)}</div>
        </K.Card>
        {selected && <K.Card title={(selected.kodlar || []).join(", ") || t("Analiz")}>
          <p className="kp-note">{t(selected.piyasa)} · {relDay(selected.zaman)}</p>
          {selected.rows?.length ? <WhyCard a={selected} /> : null}
          <div className="whitespace-pre-wrap leading-relaxed text-t-1">{splitAi(selected.metin || "").body}</div>
          {(selected.kodlar || []).map((code) => <Link key={code} className="mr-3 mt-4 inline-block font-semibold text-info"
            to={`/app/grafik?kod=${encodeURIComponent(code)}&piyasa=${encodeURIComponent(selected.piyasa || "BIST")}`}>
            {t("{k} grafiğini aç →", { k: code })}
          </Link>)}
        </K.Card>}
      </div>}
  </div>;
}
