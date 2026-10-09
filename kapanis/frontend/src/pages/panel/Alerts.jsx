import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { sendAction } from "@/lib/actions";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import api, { formatApiErrorDetail } from "@/lib/api";
import { logo, relDay } from "@/lib/dsmap";
import { useLang, translate, currentLang } from "@/lib/i18n";

const tx = (s, v) => translate(currentLang(), s, v);

const IND_OPTS = [
  { value: "sma20", label: "SMA 20" }, { value: "sma50", label: "SMA 50" }, { value: "sma200", label: "SMA 200" },
  { value: "rsi", label: "RSI" }, { value: "hacim", label: "Hacim (ortalamanın katı)" },
];
const TF_OPTS = { KRIPTO: ["1h", "4h", "1d"], BIST: ["1d", "1wk"], ABD: ["1d", "1wk"] };
const TF_LABEL = { "1h": "1 saat", "4h": "4 saat", "1d": "Günlük§mum", "1wk": "Haftalık§mum" };
const IND_NAME = { sma20: "SMA20", sma50: "SMA50", sma200: "SMA200", rsi: "RSI", hacim: "Hacim" };
const MK_LABEL = { KRIPTO: "Kripto", BIST: "BIST", ABD: "ABD" };

function indText(a) {
  if (a.gosterge === "hacim") return tx("hacim ortalamanın {n} katını geçince", { n: U.fmtNum(a.deger, 1) });
  if (a.gosterge === "rsi") return a.yon === "ustu" ? tx("RSI {n} üstüne çıkınca", { n: U.fmtNum(a.deger, 0) }) : tx("RSI {n} altına inince", { n: U.fmtNum(a.deger, 0) });
  const g = IND_NAME[a.gosterge];
  return a.yon === "ustu" ? tx("kapanış {g} üstüne çıkınca", { g }) : tx("kapanış {g} altına inince", { g });
}

// Gösterge alarmları: kripto, BIST ve ABD; yalnız kapanmış mumla, her yeni kesişmede bir kez
function IndicatorAlarms({ items }) {
  const { t } = useLang();
  const [f, setF] = useState({ piyasa: "BIST", kod: "", gosterge: "sma50", yon: "ustu", deger: "", tf: "1d" });
  const set = (k) => (e) => {
    const v = e.target.value;
    setF((o) => ({ ...o, [k]: v, ...(k === "piyasa" ? { tf: TF_OPTS[v].includes(o.tf) ? o.tf : TF_OPTS[v][0] } : {}),
      ...(k === "gosterge" ? { deger: v === "rsi" ? "30" : v === "hacim" ? "2" : "" } : {}) }));
  };
  const needsValue = f.gosterge === "rsi" || f.gosterge === "hacim";
  const save = async () => {
    const kod = f.kod.trim().toUpperCase();
    if (!kod) return toast.error(t("Kod yaz."));
    const deger = needsValue ? U.parseTr(f.deger) : null;
    if (needsValue && !(deger > 0)) return toast.error(f.gosterge === "rsi" ? t("RSI seviyesi yaz (ör. 30).") : t("Hacim katı yaz (ör. 2)."));
    if (await sendAction("ind.create", { ...f, kod, deger }, t("{k} gösterge alarmı bota iletildi.", { k: kod }))) setF({ ...f, kod: "" });
  };
  return (
    <K.Card title={t("Gösterge alarmları")} actions={<span className="kp-alarm__status is-flat">{t("Kripto")} · {t("BIST")} · {t("ABD")}</span>}>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-7">
        <K.Field label={t("Piyasa")}><K.Select value={f.piyasa} onChange={set("piyasa")} options={Object.entries(MK_LABEL).map(([value, label]) => ({ value, label: t(label) }))} /></K.Field>
        <K.Field label={t("Kod")}><K.TextInput value={f.kod} placeholder="THYAO" onChange={set("kod")} /></K.Field>
        <K.Field label={t("Gösterge")}><K.Select value={f.gosterge} onChange={set("gosterge")} options={IND_OPTS.map((o) => ({ value: o.value, label: t(o.label) }))} /></K.Field>
        <K.Field label={t("Yön")}><K.Select value={f.gosterge === "hacim" ? "ustu" : f.yon} onChange={set("yon")} disabled={f.gosterge === "hacim"}
          options={[{ value: "ustu", label: t("Üstüne") }, { value: "alti", label: t("Altına") }]} /></K.Field>
        <K.Field label={f.gosterge === "hacim" ? t("Kaç katı") : t("Seviye")}>
          <K.TextInput inputMode="decimal" value={needsValue ? f.deger : ""} disabled={!needsValue} placeholder={needsValue ? "" : "—"} onChange={set("deger")} />
        </K.Field>
        <K.Field label={t("Mum")}><K.Select value={f.tf} onChange={set("tf")} options={TF_OPTS[f.piyasa].map((v) => ({ value: v, label: t(TF_LABEL[v]) }))} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={save}>{t("Kur")}</K.Button></div>
      </div>
      {items.length ? (
        <ul className="mt-5 flex list-none flex-col divide-y divide-hairline p-0">
          {items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <span className="flex items-center gap-3">
                <K.Ticker symbol={a.kod} name={`${t(MK_LABEL[a.piyasa])} · ${t(TF_LABEL[a.tf])}`} logo={logo(a.kod, a.piyasa)} />
                <span className="text-[0.9375rem] text-t-1">{indText(a)}</span>
              </span>
              <span className="flex items-center gap-3">
                {a.tetikler?.length > 0 && <span className="kp-note m-0">{t("son tetik")} {relDay(a.tetikler[a.tetikler.length - 1])}</span>}
                <K.Button variant="ghost" onClick={() => sendAction("ind.delete", { id: a.id }, t("#{n} siliniyor.", { n: a.id }))}>{t("Sil")}</K.Button>
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="kp-note">{t("Kurulu gösterge alarmı yok.")}</p>}
      <p className="kp-note">{t("Yalnız kapanmış mumla ve kesişme anında bir kez haber verir; alarm sen silene kadar durur. Bu bir AL sinyali değildir: gelince “Kontrol & Karşılaştır” sayfasından kapıdan geçir. Telegram: /galarm")}</p>
    </K.Card>
  );
}

const STATUS = { armed: "kurulu", triggered: "tetiklendi", cancelled: "iptal" };
const code = (s) => String(s || "").split("/")[0];

// Botun alarm kaydı -> tasarım sistemindeki AlarmCard alanları
function toAlarm(a, prices) {
  const note = String(a.note || "");
  const status = STATUS[a.status] || "kurulu";
  const triggers = note.match(/(\d+) kez tetiklendi/);
  return {
    id: a.id, status, symbol: code(a.symbol), direction: a.side === "short" ? "BELOW" : "ABOVE", cur: "USD",
    trigger: a.entry, cancel: a.stop ?? undefined, target: a.target ?? undefined, rr: a.rr ?? undefined,
    price: prices[code(a.symbol)], created: relDay(a.created_at), logo: logo(code(a.symbol), "KRIPTO"),
    note: note.split(" · ").filter((x) => !/^KAPANIŞ|cooldown|tetiklendi$/.test(x)).join(" · ") || undefined,
    triggeredAt: status === "tetiklendi" && triggers ? tx("{n} kez", { n: triggers[1] }) : undefined,
    reason: status === "iptal" ? (/kapanışla kırıldı/.test(note) ? tx("İptal seviyesi kapanışla kırıldı") : /hedef/.test(note) ? tx("Hedef kapanışla görüldü") : tx("Elle silindi")) : undefined,
  };
}

export default function Alerts() {
  const { t } = useLang();
  const q = useData("alerts", "/alerts", LIVE);
  const extras = useData("extras", "/extras", LIVE);
  const qc = useQueryClient();
  const [tab, setTab] = useState("kurulu");
  const [gone, setGone] = useState([]);

  const crypto = extras.data?.takip_listesi?.piyasalar?.KRIPTO || [];
  const prices = Object.fromEntries(crypto.filter((r) => !r.hata).map((r) => [r.kod, r.fiyat]));
  const coins = crypto.filter((r) => !r.hata).map((r) => ({ symbol: r.kod, name: r.kod, price: r.fiyat }));

  const remove = async (id) => {
    setGone((g) => [...g, id]);
    try {
      await api.delete(`/alerts/${id}`);
      toast.success(t("Silme isteği bota iletildi."), { description: t("Telegram'a onay mesajı gelecek.") });
    } catch (err) {
      setGone((g) => g.filter((x) => x !== id));
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || t("Silinemedi."));
    }
  };

  const create = async (a) => {
    try {
      await api.post("/alerts", {
        symbol: `${a.symbol}/USDT`, side: a.direction === "ABOVE" ? "long" : "short", entry: a.trigger,
        stop: a.cancel ?? null, target: a.target ?? null, note: a.note || "", timeframe: "15m",
      });
      toast.success(t("{k} alarmı bota iletildi.", { k: a.symbol }), { description: t("Bot kurunca Telegram'a mesaj gelir ve listede görünür.") });
      qc.invalidateQueries({ queryKey: ["commands"] });
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || t("Alarm kurulamadı."));
    }
  };

  return (
    <DataView query={q} loadingText={t("Alarmlar yükleniyor...")}>
      {(list) => {
        const all = (list || []).filter((a) => !gone.includes(a.id)).map((a) => toAlarm(a, prices));
        const count = (s) => all.filter((a) => a.status === s).length;
        const shown = all.filter((a) => a.status === tab);
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title={t("Alarmlar")} subtitle={t("Yalnız kripto · mum kapanışıyla tetiklenir, sonra kod kapısından geçer")} />
            <div className="kp-grid kp-split">
              <div className="kp-col">
                <K.Tabs ariaLabel={t("Alarm durumu")} value={tab} onChange={setTab}
                  tabs={[{ value: "kurulu", label: t("Kurulu"), count: count("kurulu") }, { value: "tetiklendi", label: t("Tetiklendi"), count: count("tetiklendi") }, { value: "iptal", label: t("İptal edilen"), count: count("iptal") }]} />
                <div className="kp-col">
                  {shown.length ? shown.map((a) => <K.AlarmCard key={a.id} alarm={a} onDelete={remove} />)
                    : <EmptyState text={tab === "kurulu" ? t("Kurulu alarm yok. Sağdaki formdan ya da Telegram'da düz yazıyla kurabilirsin: “BTC 90000 üstünde kapanırsa haber ver”.") : t("Bu sekmede alarm yok.")} />}
                </div>
              </div>
              <K.Card title={t("Yeni alarm")} actions={<span className="kp-alarm__status is-flat">{t("Yalnız kripto")}</span>}>
                {coins.length ? <K.AlarmForm coins={coins} onSubmit={create} /> : <p className="kp-note">{t("Coin listesi yükleniyor...")}</p>}
              </K.Card>
            </div>
            <IndicatorAlarms items={extras.data?.gosterge_alarmlari || []} />
          </div>
        );
      }}
    </DataView>
  );
}
