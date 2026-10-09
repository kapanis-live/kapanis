import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { relDay } from "@/lib/dsmap";
import { PageHeader } from "@/components/PanelLayout";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useData, LIVE } from "@/lib/useData";
import { useLang, currentLang } from "@/lib/i18n";

const empty = { name: "", fk_max: "", momentum_min: "", quality_min: "" };
const numberOrNull = (s) => (String(s).trim() === "" ? null : U.parseTr(String(s)));

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 2)}`);
const tone = (v) => (v == null || v === 0 ? "" : v > 0 ? "kp-num-up" : "kp-num-down");

// Geçmiş sonuçlar: her taramada seçilenlerin o günden bu yana getirisi, BIST 100 ile yan yana (ileriye dönük kayıt)
function History({ id }) {
  const { t } = useLang();
  const q = useData(["strategy-history", id], `/strategies/${encodeURIComponent(id)}/history`);
  const runs = q.data?.kosular || [];
  if (q.isLoading) return <p className="kp-note">{t("Geçmiş yükleniyor…")}</p>;
  if (!runs.length) return <p className="kp-note">{t("Henüz tarama yok. İlk taramadan sonra seçilen hisselerin o günden bu yana sonucu burada izlenir.")}</p>;
  return (
    <div className="mt-3">
      <K.DataTable rows={runs} rowKey="id" columns={[
        { key: "zaman", label: t("Tarama"), render: (r) => relDay(r.zaman) },
        { key: "secilen", label: t("Seçilenler"), render: (r) => r.secilen.map((p) => p.kod).join(", ") || t("yok") },
        { key: "ortalama_getiri", label: t("O günden bu yana"), num: true, strong: true, render: (r) => <span className={tone(r.ortalama_getiri)}>{pct(r.ortalama_getiri)}</span> },
        { key: "xu100_getiri", label: "BIST 100", num: true, render: (r) => <span className={tone(r.xu100_getiri)}>{pct(r.xu100_getiri)}</span> },
      ]} />
      <p className="kp-note">{t(q.data?.not)}</p>
    </div>
  );
}

const pctCell = (v) => <span className={tone(v)}>{v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`}</span>;

// Canlı karne: kural yayına girdiği günden sonra verdiği her giriş/çıkış ve gerçek sonucu (geriye dönük doldurma yok)
function LiveRecord({ r }) {
  const { t } = useLang();
  const rows = (r.islemler || []).map((x) => ({ ...x, _k: x.id }));
  return <div className="mt-2 rounded-lg border border-hairline p-3">
    <p className="m-0 font-semibold text-t-1">{t("Canlı karne")} {r.baslangic ? `· ${t("başlangıç")} ${relDay(r.baslangic)}` : ""}</p>
    <p className="kp-note">{r.kapali ? t("{n} kapalı işlem · isabet %{h} · ortalama {a} (maliyet düşülmüş)", { n: r.kapali, h: r.isabet_yuzde, a: pct(r.ort_getiri_yuzde) }) : t("Henüz kapanmış işlem yok.")}
      {r.acik ? ` · ${t("{n} açık işlem.", { n: r.acik })}` : ""} {t("Yalnız başlangıçtan sonra gelen girişler sayılır; geriye dönük kazanan eklenmez.")}</p>
    {!!rows.length && <K.DataTable rows={rows} rowKey="_k" columns={[
      { key: "kod", label: "Coin", render: (x) => <b>{x.kod}</b> },
      { key: "giris_t", label: t("Giriş"), render: (x) => `${relDay(new Date(x.giris_t * 1000).toISOString())} · ${x.giris ?? "—"}` },
      { key: "durum", label: t("Durum"), render: (x) => (x.durum === "acik" ? t("açık") : `${t("çıktı")} · ${x.cikis}`) },
      { key: "sonuc", label: t("Sonuç"), num: true, strong: true, render: (x) => {
        const v = x.durum === "acik" ? x.simdi_yuzde : x.getiri_yuzde;
        return <span className={tone(v)}>{pct(v)}{x.durum === "acik" ? ` ${t("(şimdilik)")}` : ""}</span>;
      } },
    ]} />}
  </div>;
}

// Geçmiş veri testinden geçen tek kural: kripto trend takibi. Kanıt tablosu + bugünkü durum + trend alarmı.
function TrendCard() {
  const { t } = useLang();
  const q = useData("trend-board", "/strategies/trend", { refetchInterval: 600_000 });
  const alarms = useData("my-alarms", "/alarms", LIVE);
  const qc = useQueryClient();
  const [busy, setBusy] = useState("");
  const k = q.data?.kanit;
  const watched = new Set((alarms.data?.alarmlar || []).filter((a) => a.tur === "trend" && a.durum === "aktif").map((a) => a.kod));
  const coins = [...(q.data?.coinler || [])].sort((a, b) => (b.trendde - a.trendde) ||
    ((a.trendde ? a.cikisa_uzaklik_yuzde : a.girise_uzaklik_yuzde) ?? 99) - ((b.trendde ? b.cikisa_uzaklik_yuzde : b.girise_uzaklik_yuzde) ?? 99));
  const follow = async (kod) => {
    setBusy(kod);
    try {
      await api.post("/alarms", { piyasa: "KRIPTO", kod, tur: "trend", tf: "1d" });
      qc.invalidateQueries({ queryKey: ["my-alarms"] });
      toast.success(t("{k}: trend girişi ve çıkışında haber vereceğim.", { k: kod }));
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  return (
    <K.Card title={t("🔬 En güçlü aday: Kripto trend takibi (araştırma)")}>
      <p className="m-0 text-t-2">{t("Günlük kapanış son 20 günün tepesini ve 200 günlük ortalamayı geçince gir, son 10 günün dibinin altına inince çık. Aşağıdaki sonuçlar, bu kural o dönemde kullanılsaydı ne olacağını gösterir.")}</p>
      {k && <>
        <K.DataTable rows={k.satirlar} rowKey="donem" columns={[
          { key: "donem", label: t("Dönem"), render: (r) => t(r.donem) },
          { key: "kural", label: t("Kural (yıllık)"), num: true, strong: true, render: (r) => pctCell(r.kural) },
          { key: "al_tut", label: t("Al-tut"), num: true, render: (r) => pctCell(r.al_tut) },
          { key: "rastgele", label: t("Rastgele gir-çık"), num: true, render: (r) => pctCell(r.rastgele) },
          { key: "gecen_varlik", label: t("Rastgeleyi geçen coin"), num: true, mobile: false, render: (r) => `%${r.gecen_varlik}` },
          { key: "kural_dusus", label: t("En büyük düşüş"), num: true, mobile: false, render: (r) => `%${r.kural_dusus}` },
          { key: "piyasada", label: t("Piyasada"), num: true, mobile: false, render: (r) => `%${r.piyasada}` },
        ]} />
        <p className="kp-note">{t(k.evren)}. {t(k.not)}</p>
      </>}
      {q.isLoading ? <p className="kp-note">{t("Coinler hesaplanıyor…")}</p> : !!coins.length && (
        <K.DataTable rows={coins} rowKey="kod" columns={[
          { key: "kod", label: "Coin", render: (r) => <K.Ticker symbol={r.kod} logo={{ code: r.kod, market: "KRIPTO" }} /> },
          { key: "trendde", label: t("Durum"), render: (r) => r.trendde
            ? <span className="kp-num-up font-semibold">{t("Trendde")}{r.giris_bugun ? ` · ${t("bugün girdi")}` : ""}</span>
            : <span className="text-t-3">{t("Dışarıda")}{r.cikis_bugun ? ` · ${t("bugün çıktı")}` : ""}</span> },
          { key: "mesafe", label: t("Mesafe"), num: true, render: (r) => r.trendde
            ? t("çıkışa %{x}", { x: U.fmtNum(r.cikisa_uzaklik_yuzde, 1) }) : t("girişe %{x}", { x: U.fmtNum(r.girise_uzaklik_yuzde, 1) }) },
          { key: "x", label: "", render: (r) => watched.has(r.kod) ? <span className="text-sm text-t-3">{t("takipte")}</span>
            : <K.Button variant="ghost" disabled={busy === r.kod} onClick={() => follow(r.kod)}>{t("Haber ver")}</K.Button> },
        ]} />
      )}
      {q.data?.canli && <LiveRecord r={q.data.canli} />}
      <p className="kp-note">{t("\"Haber ver\": kural bu coinde girince ya da çıkınca Telegram'a ve Alarmlarım'a mesaj gelir. Portföyündeki kriptolarda çıkış seviyesi kırılınca ayrıca uyarı gelir. Emir gönderilmez; kesinlik yok.")}</p>
    </K.Card>
  );
}

const VERDICT = { PRODUCTION: ["✅ Kanıtlandı", "kp-num-up"], RESEARCH: ["🔬 Araştırma", ""], REJECTED: ["✗ Elendi", "kp-num-down"] };

const MARKET_NAME = { KRIPTO: "kripto", BIST: "BIST", ABD: "ABD" };

// Strateji Laboratuvarı: denediğimiz her kural, aynı standartla, sonucuyla birlikte (elenenler dahil)
function LabCard() {
  const { t } = useLang();
  const q = useData("strategy-lab", "/strategies/lab");
  const d = q.data;
  if (!d) return null;
  const rows = d.sonuclar.map((r, i) => ({ ...r, _k: i }));
  return (
    <K.Card title={t("Strateji Laboratuvarı")}>
      <p className="m-0 text-t-2">{t("Bir kural ancak aynı sınavdan geçerse öneri olur. Şimdiye kadar denediklerimiz:")}</p>
      <K.DataTable rows={rows} rowKey="_k" columns={[
        { key: "strateji", label: t("Strateji"), render: (r) => <span><b>{t(r.strateji)}</b> <span className="text-t-3">· {t(MARKET_NAME[r.piyasa] || r.piyasa)}</span></span> },
        { key: "karar", label: t("Sonuç"), render: (r) => <span className={VERDICT[r.karar]?.[1]}>{t(VERDICT[r.karar]?.[0] || r.karar)}</span> },
        { key: "dev", label: t("Geliştirme: kural / rastgele"), num: true, render: (r) => <span>{pctCell(r.gelistirme["kural_yillik_%"])} / {pctCell(r.gelistirme["rastgele_%"])}</span> },
        { key: "hold", label: t("Kilitli 12 ay: kural / rastgele"), num: true, mobile: false, render: (r) => <span>{pctCell(r.kilitli["kural_yillik_%"])} / {pctCell(r.kilitli["rastgele_%"])}</span> },
        { key: "islem", label: t("İşlem"), num: true, mobile: false, render: (r) => r.islem?.islem ?? "—" },
      ]} />
      <ul className="kp-note m-0 pl-5">{d.standart.map((x) => <li key={x}>{t(x)}</li>)}</ul>
      <p className="kp-note">{t("Yıllık getiriler varlık başına ortanca. Test tarihi {d}. Elenen bir kural sistemde öneri olarak kullanılmaz.", { d: d.tarih })}</p>
    </K.Card>
  );
}

const fmtDay = (iso) => new Date(iso + "T12:00:00").toLocaleDateString(currentLang() === "en" ? "en-GB" : "tr-TR", { day: "numeric", month: "short", weekday: "short" });

function TurnOfMonthCard() {
  const { t } = useLang();
  const lab = useData("strategy-lab", "/strategies/lab");
  const tom = useData("tom", "/strategies/tom", { refetchInterval: 3_600_000 });
  const alarms = useData("my-alarms", "/alarms", LIVE);
  const qc = useQueryClient();
  const watching = new Set((alarms.data?.alarmlar || []).filter((a) => a.tur === "ay_donumu" && a.durum === "aktif").map((a) => a.piyasa));
  const follow = async (piyasa) => {
    try {
      await api.post("/alarms", { piyasa, kod: "-", tur: "ay_donumu", tf: "1d" });
      qc.invalidateQueries({ queryKey: ["my-alarms"] });
      toast.success(t("Pencerenin ilk ve son günü Telegram'a ve Alarmlarım'a haber gelecek."));
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  };
  const rows = (lab.data?.sonuclar || []).filter((r) => r.strateji.startsWith("Ay dönümü"));
  return (
    <K.Card title={t("✅ Testten geçen kural: Ay dönümü")}>
      <p className="m-0 text-t-2">{t("Ayın son 2 ve yeni ayın ilk 3 işlem gününde elde tut, diğer günlerde nakitte bekle. Maaş, fon girişleri ve ay sonu dengelemesi bu günlerde alımı artırır; akademide on yıllardır bilinen bir etki. Geçmiş testte kripto ve BIST'te, hiç bakılmadan saklanan son 12 ay dahil, aynı sürede rastgele piyasada kalmayı geçti. ABD hisselerinde (S&P 100) aynı sınavı geçemedi; orada öneri değildir.")}</p>
      {!!rows.length && <K.DataTable rows={rows.map((r, i) => ({ ...r, _k: i }))} rowKey="_k" columns={[
        { key: "piyasa", label: t("Piyasa"), render: (r) => t(MARKET_NAME[r.piyasa] || r.piyasa) + (r.karar === "PRODUCTION" ? "" : ` ${t("(geçmedi)")}`) },
        { key: "dev", label: t("Geliştirme: kural / rastgele"), num: true, render: (r) => <span>{pctCell(r.gelistirme["kural_yillik_%"])} / {pctCell(r.gelistirme["rastgele_%"])}</span> },
        { key: "hold", label: t("Kilitli 12 ay: kural / rastgele"), num: true, render: (r) => <span>{pctCell(r.kilitli["kural_yillik_%"])} / {pctCell(r.kilitli["rastgele_%"])}</span> },
        { key: "gecen", label: t("Rastgeleyi geçen varlık"), num: true, mobile: false, render: (r) => `%${r.kilitli["rastgeleyi_gecen_varlik_%"]}` },
      ]} />}
      {(tom.data?.pencereler || []).map((w) => {
        const name = w.piyasa === "BIST" ? "BIST" : t("Kripto");
        const on = watching.has(w.piyasa);
        return <div key={w.piyasa} className="flex flex-wrap items-center justify-between gap-2">
          <p className="m-0 text-t-1"><b>{name}</b>: {w.icinde ? t("şu an pencerenin içindesin") : t("sıradaki pencere")} · {w.gunler.map(fmtDay).join(" · ")}
            <span className="text-t-3"> · {t("giriş {a} kapanışı, çıkış {b} kapanışı", { a: fmtDay(w.gunler[0]), b: fmtDay(w.gunler[w.gunler.length - 1]) })}</span>
            {w.takvim_eksik && <span className="text-t-3"> {t("(dini bayram takvimi henüz eklenmedi)")}</span>}</p>
          {on ? <span className="text-sm text-t-3">{t("Telegram'a bildirim açık")}</span>
            : <K.Button variant="ghost" onClick={() => follow(w.piyasa)}>{t("Giriş/çıkış günü haber ver")}</K.Button>}
        </div>;
      })}
      <p className="kp-note">{t("Getiriler varlık başına ortanca yıllık, maliyet düşülmüş. Kural kazancı büyük değil ve tek başına zengin etmez; asıl değeri, ayın geri kalanında piyasada olmamanın riski azaltması. BIST'te resmi tatiller ve yarım günler hesaba katıldı. Geçmiş sonuç geleceği garanti etmez; karar senin.")}</p>
    </K.Card>
  );
}

export default function Strategies() {
  const { t } = useLang();
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState(null);
  const qc = useQueryClient();
  const q = useData("strategies", "/strategies", LIVE);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const save = async () => {
    if (!form.name.trim()) return toast.error(t("Stratejiye bir ad ver."));
    if (["fk_max", "momentum_min", "quality_min"].some((key) => form[key] !== "" && !Number.isFinite(numberOrNull(form[key]))))
      return toast.error(t("Koşullar sayı olmalı."));
    setBusy("save");
    try {
      await api.post("/strategies", { name: form.name, rules: {
        fk_max: numberOrNull(form.fk_max), momentum_min: numberOrNull(form.momentum_min), quality_min: numberOrNull(form.quality_min) } });
      setForm(empty);
      qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success(t("Strateji kaydedildi."));
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  const run = async (id) => {
    setBusy(id);
    try {
      await api.post(`/strategies/${encodeURIComponent(id)}/run`);
      toast.success(t("BIST 100 taraması başladı. Sonuç Son Analizlerim'e ve bağlı Telegram'a gelecek."));
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  const remove = async (id) => {
    setBusy(id);
    try {
      await api.delete(`/strategies/${encodeURIComponent(id)}`);
      qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success(t("Strateji silindi."));
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  return <div className="kp-page">
    <PageHeader title={t("Strateji Kurucu")} subtitle={t("Bir kural ancak geçmiş veri sınavından geçerse öneri olur. Şu an geçen tek kural: ay dönümü.")} />
    <div className="mb-4"><TurnOfMonthCard /></div>
    <div className="mb-4"><TrendCard /></div>
    <div className="mb-4"><LabCard /></div>
    <div className="kp-grid kp-split-l">
      <K.Card title={t("BIST filtresi (test edilmedi)")}>
        <div className="grid gap-3">
          <K.Field label={t("Ad")}><K.TextInput value={form.name} onChange={set("name")} placeholder={t("Örn. Altın Vuruş")} maxLength={40} /></K.Field>
          <K.Field label={t("F/K bu değerden küçük")} hint={t("boş bırakırsan filtrelenmez")}><K.TextInput inputMode="decimal" value={form.fk_max} onChange={set("fk_max")} placeholder="10" /></K.Field>
          <K.Field label={t("3 aylık getiri BIST 100'den en az %")} hint={t("eksi değer de girilebilir")}><K.TextInput inputMode="decimal" value={form.momentum_min} onChange={set("momentum_min")} placeholder="0" /></K.Field>
          <K.Field label={t("Kalite puanı en az")} hint={t("0–100; getiri olasılığı değildir")}><K.TextInput inputMode="decimal" value={form.quality_min} onChange={set("quality_min")} placeholder="70" /></K.Field>
          <K.Button variant="primary" disabled={!!busy} onClick={save}>{t("Stratejiyi kaydet")}</K.Button>
        </div>
        <p className="kp-note"><b>{t("Test edilmedi:")}</b> {t("geçmiş bilanço verisi olmadığı için bu filtrenin geçmişte işe yarayıp yaramadığı ölçülemedi; ayrı test ettiğimiz \"en güçlü momentum\" seçimi, batan hisseler/coinler dahil edilince al-tut'u geçemedi. Sonuçlarını \"Geçmiş sonuçlar\"dan ileriye doğru izle.")}</p>
        <p className="kp-note">{t("Bilanço sürprizi koşulu için yayın tarihiyle eşleşen güvenilir geçmiş veri gerekir; henüz seçim olarak açılmadı. Tarama gerçek emir vermez.")}</p>
      </K.Card>
      <K.Card title={t("Kayıtlı stratejiler")}>
        {q.isLoading ? <p className="kp-note">{t("Yükleniyor…")}</p> : !q.data?.length ?
          <p className="kp-note">{t("Henüz strateji kaydetmedin.")}</p> : <div className="flex flex-col gap-3">{q.data.map((s) =>
            <div key={s.id} className="rounded-lg border border-hairline p-3">
              <b className="text-t-1">{s.name}</b>
              <p className="my-2 text-sm text-t-2">{[
                s.rules.fk_max != null && `${t("F/K")} < ${s.rules.fk_max}`,
                s.rules.momentum_min != null && `${t("Göreli 3 ay")} ≥ %${s.rules.momentum_min}`,
                s.rules.quality_min != null && `${t("Kalite")} ≥ ${s.rules.quality_min}`,
              ].filter(Boolean).join(" · ") || t("Filtre yok; kalite ve momentum birlikte sıralanır.")}</p>
              <div className="flex flex-wrap gap-2">
                <K.Button variant="primary" disabled={!!busy} onClick={() => run(s.id)}>{busy === s.id ? t("İşleniyor…") : t("BIST 100'ü tara")}</K.Button>
                <K.Button variant="ghost" onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? t("Geçmişi gizle") : t("Geçmiş sonuçlar")}</K.Button>
                <K.Button variant="ghost" disabled={!!busy} onClick={() => remove(s.id)}>{t("Sil")}</K.Button>
              </div>
              {open === s.id && <History id={s.id} />}
              <p className="mb-0 mt-2 text-xs text-t-3">Telegram: /tara {s.name}</p>
            </div>)}</div>}
        <Link to="/app/analizlerim" className="mt-4 inline-block font-semibold text-info">{t("Son Analizlerim →")}</Link>
      </K.Card>
    </div>
  </div>;
}
