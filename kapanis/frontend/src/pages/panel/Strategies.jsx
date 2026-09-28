import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { relDay } from "@/lib/dsmap";
import { PageHeader } from "@/components/PanelLayout";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useData, LIVE } from "@/lib/useData";

const empty = { name: "", fk_max: "", momentum_min: "", quality_min: "" };
const numberOrNull = (s) => (String(s).trim() === "" ? null : U.parseTr(String(s)));

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 2)}`);
const tone = (v) => (v == null ? "" : v >= 0 ? "kp-num-up" : "kp-num-down");

// Geçmiş sonuçlar: her taramada seçilenlerin o günden bu yana getirisi, BIST 100 ile yan yana (ileriye dönük kayıt)
function History({ id }) {
  const q = useData(["strategy-history", id], `/strategies/${encodeURIComponent(id)}/history`);
  const runs = q.data?.kosular || [];
  if (q.isLoading) return <p className="kp-note">Geçmiş yükleniyor…</p>;
  if (!runs.length) return <p className="kp-note">Henüz tarama yok. İlk taramadan sonra seçilen hisselerin o günden bu yana sonucu burada izlenir.</p>;
  return (
    <div className="mt-3">
      <K.DataTable rows={runs} rowKey="id" columns={[
        { key: "zaman", label: "Tarama", render: (r) => relDay(r.zaman) },
        { key: "secilen", label: "Seçilenler", render: (r) => r.secilen.map((p) => p.kod).join(", ") || "yok" },
        { key: "ortalama_getiri", label: "O günden bu yana", num: true, strong: true, render: (r) => <span className={tone(r.ortalama_getiri)}>{pct(r.ortalama_getiri)}</span> },
        { key: "xu100_getiri", label: "BIST 100", num: true, render: (r) => <span className={tone(r.xu100_getiri)}>{pct(r.xu100_getiri)}</span> },
      ]} />
      <p className="kp-note">{q.data?.not}</p>
    </div>
  );
}

const pctCell = (v) => <span className={tone(v)}>{v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`}</span>;

// Geçmiş veri testinden geçen tek kural: kripto trend takibi. Kanıt tablosu + bugünkü durum + trend alarmı.
function TrendCard() {
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
      toast.success(`${kod}: trend girişi ve çıkışında haber vereceğim.`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  return (
    <K.Card title="✅ Testten geçen kural: Kripto trend takibi">
      <p className="m-0 text-t-2">Günlük kapanış son 20 günün tepesini ve 200 günlük ortalamayı geçince <b>gir</b>, son 10 günün dibinin altına inince <b>çık</b>.
        Aşağıdaki sonuçlar, bu kural o dönemde kullanılsaydı ne olacağını gösterir.</p>
      {k && <>
        <K.DataTable rows={k.satirlar} rowKey="donem" columns={[
          { key: "donem", label: "Dönem" },
          { key: "kural", label: "Kural (yıllık)", num: true, strong: true, render: (r) => pctCell(r.kural) },
          { key: "al_tut", label: "Al-tut", num: true, render: (r) => pctCell(r.al_tut) },
          { key: "rastgele", label: "Rastgele gir-çık", num: true, render: (r) => pctCell(r.rastgele) },
          { key: "kural_dusus", label: "En büyük düşüş", num: true, mobile: false, render: (r) => `%${r.kural_dusus} (al-tut %${r.al_tut_dusus})` },
          { key: "piyasada", label: "Piyasada", num: true, mobile: false, render: (r) => `%${r.piyasada}` },
        ]} />
        <p className="kp-note">{k.evren}. {k.not}</p>
      </>}
      {q.isLoading ? <p className="kp-note">Coinler hesaplanıyor…</p> : !!coins.length && (
        <K.DataTable rows={coins} rowKey="kod" columns={[
          { key: "kod", label: "Coin", render: (r) => <K.Ticker symbol={r.kod} logo={{ code: r.kod, market: "KRIPTO" }} /> },
          { key: "trendde", label: "Durum", render: (r) => r.trendde
            ? <span className="kp-num-up font-semibold">Trendde{r.giris_bugun ? " · bugün girdi" : ""}</span>
            : <span className="text-t-3">Dışarıda{r.cikis_bugun ? " · bugün çıktı" : ""}</span> },
          { key: "mesafe", label: "Mesafe", num: true, render: (r) => r.trendde
            ? `çıkışa %${U.fmtNum(r.cikisa_uzaklik_yuzde, 1)}` : `girişe %${U.fmtNum(r.girise_uzaklik_yuzde, 1)}` },
          { key: "x", label: "", render: (r) => watched.has(r.kod) ? <span className="text-sm text-t-3">takipte</span>
            : <K.Button variant="ghost" disabled={busy === r.kod} onClick={() => follow(r.kod)}>Haber ver</K.Button> },
        ]} />
      )}
      <p className="kp-note">"Haber ver": kural bu coinde girince ya da çıkınca Telegram'a ve Alarmlarım'a mesaj gelir. Portföyündeki kriptolarda çıkış seviyesi kırılınca
        ayrıca uyarı gelir. Emir gönderilmez; kesinlik yok.</p>
    </K.Card>
  );
}

export default function Strategies() {
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState(null);
  const qc = useQueryClient();
  const q = useData("strategies", "/strategies", LIVE);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const save = async () => {
    if (!form.name.trim()) return toast.error("Stratejiye bir ad ver.");
    if (["fk_max", "momentum_min", "quality_min"].some((key) => form[key] !== "" && !Number.isFinite(numberOrNull(form[key]))))
      return toast.error("Koşullar sayı olmalı.");
    setBusy("save");
    try {
      await api.post("/strategies", { name: form.name, rules: {
        fk_max: numberOrNull(form.fk_max), momentum_min: numberOrNull(form.momentum_min), quality_min: numberOrNull(form.quality_min) } });
      setForm(empty);
      qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success("Strateji kaydedildi.");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  const run = async (id) => {
    setBusy(id);
    try {
      await api.post(`/strategies/${encodeURIComponent(id)}/run`);
      toast.success("BIST 100 taraması başladı. Sonuç Son Analizlerim'e ve bağlı Telegram'a gelecek.");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  const remove = async (id) => {
    setBusy(id);
    try {
      await api.delete(`/strategies/${encodeURIComponent(id)}`);
      qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success("Strateji silindi.");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  return <div className="kp-page">
    <PageHeader title="Strateji Kurucu" subtitle="Yalnız geçmiş veride test edilmiş kurallar öneri olarak gösterilir; diğerleri deneme aracıdır." />
    <div className="mb-4"><TrendCard /></div>
    <div className="kp-grid kp-split-l">
      <K.Card title="BIST filtresi (test edilmedi)">
        <div className="grid gap-3">
          <K.Field label="Ad"><K.TextInput value={form.name} onChange={set("name")} placeholder="Örn. Altın Vuruş" maxLength={40} /></K.Field>
          <K.Field label="F/K bu değerden küçük" hint="boş bırakırsan filtrelenmez"><K.TextInput inputMode="decimal" value={form.fk_max} onChange={set("fk_max")} placeholder="10" /></K.Field>
          <K.Field label="3 aylık getiri BIST 100'den en az %" hint="eksi değer de girilebilir"><K.TextInput inputMode="decimal" value={form.momentum_min} onChange={set("momentum_min")} placeholder="0" /></K.Field>
          <K.Field label="Kalite puanı en az" hint="0–100; getiri olasılığı değildir"><K.TextInput inputMode="decimal" value={form.quality_min} onChange={set("quality_min")} placeholder="70" /></K.Field>
          <K.Button variant="primary" disabled={!!busy} onClick={save}>Stratejiyi kaydet</K.Button>
        </div>
        <p className="kp-note"><b>Test edilmedi:</b> geçmiş bilanço verisi olmadığı için bu filtrenin geçmişte işe yarayıp yaramadığı ölçülemedi;
          ayrı test ettiğimiz "en güçlü momentum" seçimi, batan hisseler/coinler dahil edilince al-tut'u geçemedi. Sonuçlarını "Geçmiş sonuçlar"dan ileriye doğru izle.</p>
        <p className="kp-note">Bilanço sürprizi koşulu için yayın tarihiyle eşleşen güvenilir geçmiş veri gerekir; henüz seçim olarak açılmadı. Tarama gerçek emir vermez.</p>
      </K.Card>
      <K.Card title="Kayıtlı stratejiler">
        {q.isLoading ? <p className="kp-note">Yükleniyor…</p> : !q.data?.length ?
          <p className="kp-note">Henüz strateji kaydetmedin.</p> : <div className="flex flex-col gap-3">{q.data.map((s) =>
            <div key={s.id} className="rounded-lg border border-hairline p-3">
              <b className="text-t-1">{s.name}</b>
              <p className="my-2 text-sm text-t-2">{[
                s.rules.fk_max != null && `F/K < ${s.rules.fk_max}`,
                s.rules.momentum_min != null && `Göreli 3 ay ≥ %${s.rules.momentum_min}`,
                s.rules.quality_min != null && `Kalite ≥ ${s.rules.quality_min}`,
              ].filter(Boolean).join(" · ") || "Filtre yok; kalite ve momentum birlikte sıralanır."}</p>
              <div className="flex flex-wrap gap-2">
                <K.Button variant="primary" disabled={!!busy} onClick={() => run(s.id)}>{busy === s.id ? "İşleniyor…" : "BIST 100'ü tara"}</K.Button>
                <K.Button variant="ghost" onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? "Geçmişi gizle" : "Geçmiş sonuçlar"}</K.Button>
                <K.Button variant="ghost" disabled={!!busy} onClick={() => remove(s.id)}>Sil</K.Button>
              </div>
              {open === s.id && <History id={s.id} />}
              <p className="mb-0 mt-2 text-xs text-t-3">Telegram: /tara {s.name}</p>
            </div>)}</div>}
        <Link to="/app/analizlerim" className="mt-4 inline-block font-semibold text-info">Son Analizlerim →</Link>
      </K.Card>
    </div>
  </div>;
}
