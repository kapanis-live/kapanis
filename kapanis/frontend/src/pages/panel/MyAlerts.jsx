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
import { useLang } from "@/lib/i18n";

const TF_LABEL = { "1h": "1 saatlik", "4h": "4 saatlik", "1d": "Günlük§mum" };
const MARKETS = [{ value: "KRIPTO", label: "Kripto" }, { value: "BIST", label: "BIST" }, { value: "ABD", label: "ABD" }];
const empty = { piyasa: "BIST", kod: "", tur: "fiyat", yon: "ustu", seviye: "", tf: "1d" };

const describe = (a, t) => t("{tf} {w} {l} {y}", { tf: t(TF_LABEL[a.tf] || a.tf), w: a.tur === "rsi" ? "RSI" : t("kapanış"),
  l: a.tur === "rsi" ? U.fmtNum(a.seviye, 0) : px(a.seviye), y: t(a.yon === "ustu" ? "üstünde" : "altında") });

// Kullanıcının kendi alarmları: yalnız mum kapanışında çalışır; tetiklenince bağlı Telegram'a gider.
export default function MyAlerts() {
  const { t } = useLang();
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
    if (!form.kod.trim()) return toast.error(t("Kod yaz (ör. THYAO, BTC, NVDA)."));
    if (!Number.isFinite(seviye) || seviye <= 0) return toast.error(t("Seviye sayı olmalı."));
    setBusy("save");
    try {
      const a = (await api.post("/alarms", { ...form, kod: form.kod.trim(), seviye })).data;
      setForm((f) => ({ ...f, kod: "", seviye: "" }));
      qc.invalidateQueries({ queryKey: ["my-alarms"] });
      toast.success(t("{k} alarmı kuruldu.", { k: a.kod }), { description: a.son_kapanis != null ? `${t("Son kapanış")} ${px(a.son_kapanis)}` : undefined });
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
        <K.Ticker symbol={a.kod} name={describe(a, t)} logo={{ code: a.kod, market: a.piyasa }} />
        <p className="m-0 mt-1 text-sm text-t-3">
          {a.durum === "aktif"
            ? `${t("Son kapanış")} ${a.son_kapanis != null ? px(a.son_kapanis) : "—"}${a.son_rsi != null ? ` · RSI ${U.fmtNum(a.son_rsi, 0)}` : ""}`
            : `${t("Tetiklendi")} ${a.tetik ? relDay(a.tetik.zaman) : ""} · ${t("kapanış")} ${a.tetik ? px(a.tetik.kapanis) : "—"}`}
        </p>
      </div>
      <div className="flex gap-2">
        <Link to={`/app/grafik?kod=${encodeURIComponent(a.kod)}&piyasa=${a.piyasa}`} className="self-center text-sm font-semibold text-info">{t("Grafik")}</Link>
        <K.Button variant="ghost" disabled={busy === a.id} onClick={() => remove(a.id)}>{t("Sil")}</K.Button>
      </div>
    </div>
  );

  return <div className="kp-page">
    <PageHeader title={t("Alarmlarım")} subtitle={t("Fiyat ya da RSI seviyesinde kapanış olunca haber ver. Dokunma sayılmaz, yalnız kapanış.")} />
    {q.data && !q.data.telegram && <K.Callout tone="info" title={t("Telegram bağlı değil")}>
      {t("Alarmlar tetiklenince burada görünür. Telefonuna da gelsin istiyorsan bağla:")} <Link to="/app/hesap" className="font-semibold text-info">{t("Hesap & Telegram")}</Link>
    </K.Callout>}
    <div className="kp-grid kp-split-l">
      <K.Card title={t("Yeni alarm")}>
        <div className="grid gap-3">
          <K.Field label={t("Piyasa")}><K.Select value={form.piyasa} onChange={set("piyasa")} options={MARKETS.map((o) => ({ ...o, label: t(o.label) }))} /></K.Field>
          <K.Field label={t("Kod")}><K.TextInput value={form.kod} onChange={set("kod")} placeholder={form.piyasa === "KRIPTO" ? "BTC" : form.piyasa === "ABD" ? "NVDA" : "THYAO"} maxLength={15} /></K.Field>
          <K.Field label={t("Ne izlensin?")}><K.Select value={form.tur} onChange={set("tur")}
            options={[{ value: "fiyat", label: t("Kapanış fiyatı") }, { value: "rsi", label: "RSI (14)" }]} /></K.Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <K.Field label={t("Kapanış")}><K.Select value={form.yon} onChange={set("yon")}
              options={[{ value: "ustu", label: t("Üstünde") }, { value: "alti", label: t("Altında") }]} /></K.Field>
            <K.Field label={form.tur === "rsi" ? t("RSI seviyesi") : t("Fiyat")}><K.TextInput inputMode="decimal" value={form.seviye} onChange={set("seviye")} placeholder={form.tur === "rsi" ? "30" : "0,00"} /></K.Field>
          </div>
          <K.Field label={t("Mum")} hint={form.piyasa === "KRIPTO" ? undefined : t("BIST ve ABD'de günlük kapanış (seans sonu)")}>
            <K.Select value={form.tf} onChange={set("tf")} options={tfs.map((x) => ({ value: x, label: t(TF_LABEL[x] || x) }))} />
          </K.Field>
          <K.Button variant="primary" disabled={busy === "save"} onClick={save}>{busy === "save" ? t("Kuruluyor…") : t("Alarmı kur")}</K.Button>
        </div>
        <p className="kp-note">{t("Alarm bir kez çalışır, sonra \"tetiklenenler\" listesine geçer. En fazla {n} aktif alarm. Portföyündeki pozisyonların stop ve hedefi ayrıca kendiliğinden izlenir (günlük kapanış). Alarm emir göndermez.", { n: q.data?.sinir ?? 20 })}</p>
      </K.Card>
      <div className="flex flex-col gap-4">
        <K.Card title={`${t("Aktif alarmlar")} (${active.length})`}>
          {q.isLoading ? <div className="kp-skel h-40" aria-busy="true" /> : !active.length
            ? <p className="kp-note">{t("Aktif alarm yok.")}</p> : <div className="flex flex-col gap-2">{active.map(row)}</div>}
        </K.Card>
        <K.Card title={t("Son uyarılar")}>
          {!(q.data?.olaylar || []).length ? <p className="kp-note">{t("Henüz uyarı yok. Alarm ya da pozisyon stop/hedefi kapanışla görülünce burada listelenir.")}</p> :
            <div className="flex flex-col gap-2">{q.data.olaylar.map((e) =>
              <div key={e.id} className="rounded-lg border border-hairline p-3">
                <p className="m-0 text-t-1">{e.metin}</p>
                <p className="m-0 mt-1 text-xs text-t-3">{relDay(e.zaman)}{e.gonderildi && q.data.telegram ? ` · ${t("Telegram'a gönderildi")}` : ""}</p>
              </div>)}</div>}
        </K.Card>
        {!!fired.length && <K.Card title={`${t("Tetiklenenler")} (${fired.length})`}><div className="flex flex-col gap-2">{fired.map(row)}</div></K.Card>}
      </div>
    </div>
  </div>;
}
