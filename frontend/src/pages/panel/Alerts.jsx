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

const IND_OPTS = [
  { value: "sma20", label: "SMA 20" }, { value: "sma50", label: "SMA 50" }, { value: "sma200", label: "SMA 200" },
  { value: "rsi", label: "RSI" }, { value: "hacim", label: "Hacim (ortalamanın katı)" },
];
const TF_OPTS = { KRIPTO: ["1h", "4h", "1d"], BIST: ["1d", "1wk"], ABD: ["1d", "1wk"] };
const TF_LABEL = { "1h": "1 saat", "4h": "4 saat", "1d": "Günlük", "1wk": "Haftalık" };
const IND_NAME = { sma20: "SMA20", sma50: "SMA50", sma200: "SMA200", rsi: "RSI", hacim: "Hacim" };
const MK_LABEL = { KRIPTO: "Kripto", BIST: "BIST", ABD: "ABD" };

function indText(a) {
  const side = a.yon === "ustu" ? "üstüne çıkınca" : "altına inince";
  if (a.gosterge === "hacim") return `hacim ortalamanın ${U.fmtNum(a.deger, 1)} katını geçince`;
  if (a.gosterge === "rsi") return `RSI ${U.fmtNum(a.deger, 0)} ${side}`;
  return `kapanış ${IND_NAME[a.gosterge]} ${side}`;
}

// Gösterge alarmları: kripto, BIST ve ABD; yalnız kapanmış mumla, her yeni kesişmede bir kez
function IndicatorAlarms({ items }) {
  const [f, setF] = useState({ piyasa: "BIST", kod: "", gosterge: "sma50", yon: "ustu", deger: "", tf: "1d" });
  const set = (k) => (e) => {
    const v = e.target.value;
    setF((o) => ({ ...o, [k]: v, ...(k === "piyasa" ? { tf: TF_OPTS[v].includes(o.tf) ? o.tf : TF_OPTS[v][0] } : {}),
      ...(k === "gosterge" ? { deger: v === "rsi" ? "30" : v === "hacim" ? "2" : "" } : {}) }));
  };
  const needsValue = f.gosterge === "rsi" || f.gosterge === "hacim";
  const save = async () => {
    const kod = f.kod.trim().toUpperCase();
    if (!kod) return toast.error("Kod yaz.");
    const deger = needsValue ? U.parseTr(f.deger) : null;
    if (needsValue && !(deger > 0)) return toast.error(f.gosterge === "rsi" ? "RSI seviyesi yaz (ör. 30)." : "Hacim katı yaz (ör. 2).");
    if (await sendAction("ind.create", { ...f, kod, deger }, `${kod} gösterge alarmı bota iletildi.`)) setF({ ...f, kod: "" });
  };
  return (
    <K.Card title="Gösterge alarmları" actions={<span className="kp-alarm__status is-flat">Kripto · BIST · ABD</span>}>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-7">
        <K.Field label="Piyasa"><K.Select value={f.piyasa} onChange={set("piyasa")} options={Object.entries(MK_LABEL).map(([value, label]) => ({ value, label }))} /></K.Field>
        <K.Field label="Kod"><K.TextInput value={f.kod} placeholder="THYAO" onChange={set("kod")} /></K.Field>
        <K.Field label="Gösterge"><K.Select value={f.gosterge} onChange={set("gosterge")} options={IND_OPTS} /></K.Field>
        <K.Field label="Yön"><K.Select value={f.gosterge === "hacim" ? "ustu" : f.yon} onChange={set("yon")} disabled={f.gosterge === "hacim"}
          options={[{ value: "ustu", label: "Üstüne" }, { value: "alti", label: "Altına" }]} /></K.Field>
        <K.Field label={f.gosterge === "hacim" ? "Kaç katı" : "Seviye"}>
          <K.TextInput inputMode="decimal" value={needsValue ? f.deger : ""} disabled={!needsValue} placeholder={needsValue ? "" : "—"} onChange={set("deger")} />
        </K.Field>
        <K.Field label="Mum"><K.Select value={f.tf} onChange={set("tf")} options={TF_OPTS[f.piyasa].map((v) => ({ value: v, label: TF_LABEL[v] }))} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={save}>Kur</K.Button></div>
      </div>
      {items.length ? (
        <ul className="mt-5 flex list-none flex-col divide-y divide-hairline p-0">
          {items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <span className="flex items-center gap-3">
                <K.Ticker symbol={a.kod} name={`${MK_LABEL[a.piyasa]} · ${TF_LABEL[a.tf]}`} logo={logo(a.kod, a.piyasa)} />
                <span className="text-[0.9375rem] text-t-1">{indText(a)}</span>
              </span>
              <span className="flex items-center gap-3">
                {a.tetikler?.length > 0 && <span className="kp-note m-0">son tetik {relDay(a.tetikler[a.tetikler.length - 1])}</span>}
                <K.Button variant="ghost" onClick={() => sendAction("ind.delete", { id: a.id }, `#${a.id} siliniyor.`)}>Sil</K.Button>
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="kp-note">Kurulu gösterge alarmı yok.</p>}
      <p className="kp-note">Yalnız kapanmış mumla ve kesişme anında bir kez haber verir; alarm sen silene kadar durur. Bu bir AL sinyali değildir: gelince “Kontrol & Karşılaştır” sayfasından kapıdan geçir. Telegram: /galarm</p>
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
    triggeredAt: status === "tetiklendi" && triggers ? `${triggers[1]} kez` : undefined,
    reason: status === "iptal" ? (/kapanışla kırıldı/.test(note) ? "İptal seviyesi kapanışla kırıldı" : /hedef/.test(note) ? "Hedef kapanışla görüldü" : "Elle silindi") : undefined,
  };
}

export default function Alerts() {
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
      toast.success("Silme isteği bota iletildi.", { description: "Telegram'a onay mesajı gelecek." });
    } catch (err) {
      setGone((g) => g.filter((x) => x !== id));
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Silinemedi.");
    }
  };

  const create = async (a) => {
    try {
      await api.post("/alerts", {
        symbol: `${a.symbol}/USDT`, side: a.direction === "ABOVE" ? "long" : "short", entry: a.trigger,
        stop: a.cancel ?? null, target: a.target ?? null, note: a.note || "", timeframe: "15m",
      });
      toast.success(`${a.symbol} alarmı bota iletildi.`, { description: "Bot kurunca Telegram'a mesaj gelir ve listede görünür." });
      qc.invalidateQueries({ queryKey: ["commands"] });
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Alarm kurulamadı.");
    }
  };

  return (
    <DataView query={q} loadingText="Alarmlar yükleniyor...">
      {(list) => {
        const all = (list || []).filter((a) => !gone.includes(a.id)).map((a) => toAlarm(a, prices));
        const count = (s) => all.filter((a) => a.status === s).length;
        const shown = all.filter((a) => a.status === tab);
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title="Alarmlar" subtitle="Yalnız kripto · mum kapanışıyla tetiklenir, sonra kod kapısından geçer" />
            <div className="kp-grid kp-split">
              <div className="kp-col">
                <K.Tabs ariaLabel="Alarm durumu" value={tab} onChange={setTab}
                  tabs={[{ value: "kurulu", label: "Kurulu", count: count("kurulu") }, { value: "tetiklendi", label: "Tetiklendi", count: count("tetiklendi") }, { value: "iptal", label: "İptal edilen", count: count("iptal") }]} />
                <div className="kp-col">
                  {shown.length ? shown.map((a) => <K.AlarmCard key={a.id} alarm={a} onDelete={remove} />)
                    : <EmptyState text={tab === "kurulu" ? "Kurulu alarm yok. Sağdaki formdan ya da Telegram'da düz yazıyla kurabilirsin: “BTC 90000 üstünde kapanırsa haber ver”." : "Bu sekmede alarm yok."} />}
                </div>
              </div>
              <K.Card title="Yeni alarm" actions={<span className="kp-alarm__status is-flat">Yalnız kripto</span>}>
                {coins.length ? <K.AlarmForm coins={coins} onSubmit={create} /> : <p className="kp-note">Coin listesi yükleniyor...</p>}
              </K.Card>
            </div>
            <IndicatorAlarms items={extras.data?.gosterge_alarmlari || []} />
          </div>
        );
      }}
    </DataView>
  );
}
