import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { K } from "@/ds";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { AssetLogo, chartHref } from "@/components/AssetLogo";
import { Segmented } from "@/components/kp";

// Şirket takvimi: portföydeki ve takip listesindeki hisselerin bilanço ve temettü günleri (bot her gün yeniler).
const RISK_CLASS = { "YÜKSEK": "bg-down/15 text-down", ORTA: "is-warn", "DÜŞÜK": "is-flat" };
const FILTERS = [{ value: "hepsi", label: "Hepsi" }, { value: "portfoy", label: "Portföyüm" }, { value: "bilanco", label: "Yalnız bilanço" }];
const DAYS = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"];
const MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];

function dayLabel(iso) {
  const d = new Date(`${iso}T12:00:00`);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${DAYS[d.getDay()]}`;
}
const left = (n) => (n === 0 ? "bugün" : n === 1 ? "yarın" : `${n} gün`);

// Aynı haftanın olayları tek başlık altında: "Bu hafta", "Gelecek hafta", sonra "3 hafta sonra"...
function weekTitle(days) {
  const w = Math.floor(days / 7);
  return w === 0 ? "Önümüzdeki 7 gün" : w === 1 ? "8–14 gün" : `${w * 7 + 1}–${w * 7 + 7} gün`;
}

export default function CompanyCalendar() {
  const q = useData("extras", "/extras", LIVE);
  const navigate = useNavigate();
  const [filter, setFilter] = useState("hepsi");
  const items = useMemo(() => (q.data?.takvim || []).filter((i) => typeof i.gun === "number"), [q.data]);
  const shown = items.filter((i) => (filter === "portfoy" ? i.portfoyde : filter === "bilanco" ? i.tur === "bilanco" : true));
  const groups = useMemo(() => {
    const out = [];
    shown.forEach((i) => {
      const title = weekTitle(i.gun);
      const last = out[out.length - 1];
      if (last && last.title === title) last.rows.push(i);
      else out.push({ title, rows: [i] });
    });
    return out;
  }, [shown]);
  const soon = items.filter((i) => i.risk === "YÜKSEK");
  return (
    <div className="kp-page">
      <PageHeader title="Şirket takvimi" testid="page-calendar"
        subtitle="Portföyündeki ve takip listendeki hisselerin bilanço ve temettü günleri. Bilanço günü fiyat açılışta sıçrayabilir." />
      <DataView query={q} loadingText="Takvim yükleniyor...">
        {() => (
          <div className="kp-col">
            {soon.length > 0 && (
              <K.Callout tone="warn" title={`${soon.length} hissede bilanço 5 gün içinde`}>
                {soon.map((i) => `${i.kod} (${left(i.gun)})`).join(" · ")}. Açılış boşluğu (gap) riski yüksek: stop seviyesi atlanabilir.
                Bu bir uyarıdır, öneri değildir.
              </K.Callout>
            )}
            <Segmented ariaLabel="Takvim filtresi" value={filter} onChange={setFilter} options={FILTERS} />
            {!groups.length ? (
              <K.Card title="Yaklaşan olay yok">
                <p className="kp-note m-0">{items.length ? "Bu filtreye uyan olay yok." : "Önümüzdeki günlerde bilanço ya da temettü tarihi görünmüyor. Takip listene hisse ekleyince burada çıkar."}</p>
              </K.Card>
            ) : groups.map((g) => (
              <K.Card key={g.title} title={g.title}>
                <ul className="m-0 flex list-none flex-col p-0" data-testid="calendar-rows">
                  {g.rows.map((i) => (
                    <li key={`${i.kod}-${i.tur}-${i.tarih}`} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-hairline py-3 last:border-0">
                      <button type="button" onClick={() => navigate(chartHref(i.kod, i.piyasa))} className="flex min-w-0 items-center gap-3 text-left"
                        aria-label={`${i.kod} grafiğini aç`}>
                        <AssetLogo code={i.kod} market={i.piyasa} />
                        <span className="min-w-0">
                          <b className="block text-base text-t-1">{i.kod} <span className="text-sm font-normal text-t-3">· {i.piyasa}{i.portfoyde ? " · portföyünde" : " · takipte"}</span></b>
                          <span className="block text-sm text-t-2">{i.etiket} · {dayLabel(i.tarih)}</span>
                        </span>
                      </button>
                      <span className="flex items-center gap-2">
                        <span className="num text-sm font-semibold text-t-1">{left(i.gun)}</span>
                        {i.risk && <span className={`kp-alarm__status ${RISK_CLASS[i.risk] || "is-flat"}`}>boşluk riski {i.risk}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              </K.Card>
            ))}
            <p className="kp-note m-0">Tarihler Yahoo'dan, günde bir kez yenilenir; kesin tarih için KAP ya da şirketin yatırımcı sayfası. Bilançoya 5 gün ve daha az
              kala risk YÜKSEK, 14 güne kadar ORTA sayılır. Bir gün önce Telegram'dan hatırlatma gelir. Telegram: /olaylar</p>
          </div>
        )}
      </DataView>
    </div>
  );
}
