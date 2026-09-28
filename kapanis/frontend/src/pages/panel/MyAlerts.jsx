import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { relDay } from "@/lib/dsmap";
import { PageHeader } from "@/components/PanelLayout";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useData, LIVE } from "@/lib/useData";
import { px } from "@/lib/portfolio";

const TF_LABEL = { "1h": "1 saatlik", "4h": "4 saatlik", "1d": "Günlük" };
const MARKETS = [{ value: "KRIPTO", label: "Kripto" }, { value: "BIST", label: "BIST" }, { value: "ABD", label: "ABD" }];
const empty = { piyasa: "BIST", kod: "", tur: "fiyat", yon: "ustu", seviye: "", tf: "1d" };

const describe = (a) =>
  `${TF_LABEL[a.tf] || a.tf} ${a.tur === "rsi" ? "RSI" : "kapanış"} ${a.tur === "rsi" ? U.fmtNum(a.seviye, 0) : px(a.seviye)} ${a.yon === "ustu" ? "üstünde" : "altında"}`;

// Kullanıcının kendi alarmları: yalnız mum kapanışında çalışır; tetiklenince bağlı Telegram'a gider.
export default function MyAlerts() {
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState("");
  const qc = useQueryClient();
  const q = useData("my-alarms", "/alarms", LIVE);
  const tfs = q.data?.zaman_dilimleri?.[form.piyasa] || ["1d"];
  const set = (key) => (e) => setForm((f) => {
    const next = { ...f, [key]: e.target.value };
    if (key === "piyasa" && !(q.data?.zaman_dilimleri?.[next.piyasa] || ["1d"]).includes(next.tf)) next.tf = "1d";
    return next;
  });
  const alarms = q.data?.alarmlar || [];
  const active = alarms.filter((a) => a.durum === "aktif");
  const fired = alarms.filter((a) => a.durum !== "aktif");

  const save = async () => {
    const seviye = U.parseTr(String(form.seviye));
    if (!form.kod.trim()) return toast.error("Kod yaz (ör. THYAO, BTC, NVDA).");
    if (!Number.isFinite(seviye) || seviye <= 0) return toast.error("Seviye sayı olmalı.");
    setBusy("save");
    try {
      const a = (await api.post("/alarms", { ...form, kod: form.kod.trim(), seviye })).data;
      setForm((f) => ({ ...f, kod: "", seviye: "" }));
      qc.invalidateQueries({ queryKey: ["my-alarms"] });
      toast.success(`${a.kod} alarmı kuruldu.`, { description: a.son_kapanis != null ? `Son kapanış ${px(a.son_kapanis)}` : undefined });
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  const remove = async (id) => {
    setBusy(id);
    try {
      await api.delete(`/alarms/${encodeURIComponent(id)}`);
      qc.invalidateQueries({ queryKey: ["my-alarms"] });
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };

  const row = (a) => (
    <div key={a.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-hairline p-3">
      <div className="min-w-0">
        <K.Ticker symbol={a.kod} name={describe(a)} logo={{ code: a.kod, market: a.piyasa }} />
        <p className="m-0 mt-1 text-sm text-t-3">
          {a.durum === "aktif"
            ? `Son kapanış ${a.son_kapanis != null ? px(a.son_kapanis) : "—"}${a.son_rsi != null ? ` · RSI ${U.fmtNum(a.son_rsi, 0)}` : ""}`
            : `Tetiklendi ${a.tetik ? relDay(a.tetik.zaman) : ""} · kapanış ${a.tetik ? px(a.tetik.kapanis) : "—"}`}
        </p>
      </div>
      <div className="flex gap-2">
        <Link to={`/app/grafik?kod=${encodeURIComponent(a.kod)}&piyasa=${a.piyasa}`} className="self-center text-sm font-semibold text-info">Grafik</Link>
        <K.Button variant="ghost" disabled={busy === a.id} onClick={() => remove(a.id)}>Sil</K.Button>
      </div>
    </div>
  );

  return <div className="kp-page">
    <PageHeader title="Alarmlarım" subtitle="Fiyat ya da RSI seviyesinde kapanış olunca haber ver. Dokunma sayılmaz, yalnız kapanış." />
    {q.data && !q.data.telegram && <K.Callout tone="info" title="Telegram bağlı değil">
      Alarmlar tetiklenince burada görünür. Telefonuna da gelsin istiyorsan <Link to="/app/hesap" className="font-semibold text-info">Hesap & Telegram</Link> sayfasından bağla.
    </K.Callout>}
    <div className="kp-grid kp-split-l">
      <K.Card title="Yeni alarm">
        <div className="grid gap-3">
          <K.Field label="Piyasa"><K.Select value={form.piyasa} onChange={set("piyasa")} options={MARKETS} /></K.Field>
          <K.Field label="Kod"><K.TextInput value={form.kod} onChange={set("kod")} placeholder={form.piyasa === "KRIPTO" ? "BTC" : form.piyasa === "ABD" ? "NVDA" : "THYAO"} maxLength={15} /></K.Field>
          <K.Field label="Ne izlensin?"><K.Select value={form.tur} onChange={set("tur")}
            options={[{ value: "fiyat", label: "Kapanış fiyatı" }, { value: "rsi", label: "RSI (14)" }]} /></K.Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <K.Field label="Kapanış"><K.Select value={form.yon} onChange={set("yon")}
              options={[{ value: "ustu", label: "Üstünde" }, { value: "alti", label: "Altında" }]} /></K.Field>
            <K.Field label={form.tur === "rsi" ? "RSI seviyesi" : "Fiyat"}><K.TextInput inputMode="decimal" value={form.seviye} onChange={set("seviye")} placeholder={form.tur === "rsi" ? "30" : "0,00"} /></K.Field>
          </div>
          <K.Field label="Mum" hint={form.piyasa === "KRIPTO" ? undefined : "BIST ve ABD'de günlük kapanış (seans sonu)"}>
            <K.Select value={form.tf} onChange={set("tf")} options={tfs.map((t) => ({ value: t, label: TF_LABEL[t] || t }))} />
          </K.Field>
          <K.Button variant="primary" disabled={busy === "save"} onClick={save}>{busy === "save" ? "Kuruluyor…" : "Alarmı kur"}</K.Button>
        </div>
        <p className="kp-note">Alarm bir kez çalışır, sonra "tetiklenenler" listesine geçer. En fazla {q.data?.sinir ?? 20} aktif alarm.
          Portföyündeki pozisyonların stop ve hedefi ayrıca kendiliğinden izlenir (günlük kapanış). Alarm emir göndermez.</p>
      </K.Card>
      <div className="flex flex-col gap-4">
        <K.Card title={`Aktif alarmlar (${active.length})`}>
          {q.isLoading ? <p className="kp-note">Yükleniyor…</p> : !active.length
            ? <p className="kp-note">Aktif alarm yok.</p> : <div className="flex flex-col gap-2">{active.map(row)}</div>}
        </K.Card>
        <K.Card title="Son uyarılar">
          {!(q.data?.olaylar || []).length ? <p className="kp-note">Henüz uyarı yok. Alarm ya da pozisyon stop/hedefi kapanışla görülünce burada listelenir.</p> :
            <div className="flex flex-col gap-2">{q.data.olaylar.map((e) =>
              <div key={e.id} className="rounded-lg border border-hairline p-3">
                <p className="m-0 text-t-1">{e.metin}</p>
                <p className="m-0 mt-1 text-xs text-t-3">{relDay(e.zaman)}{e.gonderildi && q.data.telegram ? " · Telegram'a gönderildi" : ""}</p>
              </div>)}</div>}
        </K.Card>
        {!!fired.length && <K.Card title={`Tetiklenenler (${fired.length})`}><div className="flex flex-col gap-2">{fired.map(row)}</div></K.Card>}
      </div>
    </div>
  </div>;
}
