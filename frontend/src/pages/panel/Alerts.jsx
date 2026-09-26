import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { K } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import api, { formatApiErrorDetail } from "@/lib/api";
import { logo, relDay } from "@/lib/dsmap";

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
          </div>
        );
      }}
    </DataView>
  );
}
