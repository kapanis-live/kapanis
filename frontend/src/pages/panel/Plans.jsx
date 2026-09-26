import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { chartHref } from "@/components/AssetLogo";
import { sendAction } from "@/lib/actions";
import { logo, MARKET_UI, relDay, priceFmt } from "@/lib/dsmap";

const STATE_TONE = {
  "tetiğin üstünde": "up", "tetiğe yakın": "warn", bekliyor: "flat", hedefte: "info", bozuldu: "down", "veri yok": "flat",
};
const STATE_CLS = { up: "kp-num-up", down: "kp-num-down", warn: "text-wait", info: "text-info", flat: "text-t-2" };
const pctTxt = (v) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}%${U.fmtNum(Math.abs(v), 2)}`);

function Opportunity() {
  const q = useData("firsat", "/firsat", LIVE);
  const [asked, setAsked] = useState(null);
  const d = q.data || {};
  const waiting = asked && (!d.zaman || new Date(d.zaman).getTime() < asked);
  const run = async () => {
    if (await sendAction("firsat.run", {}, "Fırsat taraması başlatıldı.")) setAsked(Date.now());
  };
  const buyable = d.alinabilir || [];
  return (
    <K.Card title="Şu an alınabilecek bir şey var mı?" actions={<K.Button variant="primary" onClick={run} disabled={!!waiting}>{waiting ? "Taranıyor…" : "Şimdi tara"}</K.Button>}>
      {waiting && <p className="kp-note">Bot bütün planları, son sinyalleri, tarayıcıyı ve piyasa kapılarını kontrol ediyor (15–30 sn).</p>}
      {!d.zaman ? <p className="kp-note">Henüz tarama yapılmadı. “Şimdi tara”ya bas; aynı tarama Telegram'da /firsat.</p> : (
        <>
          <K.Callout tone={buyable.length ? "info" : "warn"} title={buyable.length ? `${buyable.length} kalem kurallara uyuyor` : "Şu an kurallara uyan giriş yok"}>
            {relDay(d.zaman)} · {d.kalemler?.length || 0} kalem incelendi · {d.sure_sn} sn
          </K.Callout>
          <pre className="mt-4 whitespace-pre-wrap text-[0.9375rem] leading-relaxed text-t-2" style={{ fontFamily: "inherit" }}>
            {String(d.metin || "").replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, "").trim()}
          </pre>
        </>
      )}
    </K.Card>
  );
}

export default function Plans() {
  const navigate = useNavigate();
  const q = useData("extras", "/extras", LIVE);
  const [draft, setDraft] = useState("");
  const add = async (v) => {
    const kod = String(v || "").trim().toUpperCase();
    if (kod && (await sendAction("plan.add", { kod }, `${kod} plan listesine ekleniyor.`))) setDraft("");
  };
  return (
    <DataView query={q} loadingText="Planlar yükleniyor...">
      {(d) => {
        const plans = d.planlar || [];
        const cols = [
          { key: "kod", label: "Kod", render: (r) => <K.Ticker symbol={r.kod} name={MARKET_UI[r.piyasa]?.label} logo={logo(r.kod, r.piyasa)} /> },
          { key: "fiyat", label: "Fiyat", num: true, strong: true, render: (r) => priceFmt(r.fiyat, r.piyasa === "BIST" ? "TRY" : "USD") },
          { key: "tetik", label: "Tetik", num: true, render: (r) => (r.tetik ? <span>{priceFmt(r.tetik, r.piyasa === "BIST" ? "TRY" : "USD")} <span className="kp-muted">{pctTxt(r.tetige)}</span></span> : "—") },
          { key: "iptal", label: "İptal", num: true, mobile: false, render: (r) => (r.iptal ? <span>{priceFmt(r.iptal, r.piyasa === "BIST" ? "TRY" : "USD")} <span className="kp-muted">{pctTxt(r.iptale)}</span></span> : "—") },
          { key: "hedef", label: "Hedef", num: true, mobile: false, render: (r) => (r.hedef ? <span>{priceFmt(r.hedef, r.piyasa === "BIST" ? "TRY" : "USD")} <span className="kp-muted">{pctTxt(r.hedefe)}</span></span> : "—") },
          { key: "durum", label: "Durum", render: (r) => (r.plan ? <b className={STATE_CLS[STATE_TONE[r.durum] || "flat"]}>{r.durum}</b> : <span className="kp-muted">plan yok</span>) },
          { key: "sil", label: "", render: (r) => r.listede && (
            <K.Button variant="ghost" onClick={(e) => { e.stopPropagation(); sendAction("plan.remove", { key: r.key }, `${r.kod} listeden çıkarılıyor.`); }}>Çıkar</K.Button>) },
        ];
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title="Planlar ve fırsatlar"
              subtitle="Yapay zekânın kurduğu planlar kodla izlenir: tetik ve teyit yalnız mum kapanışıyla sayılır." />
            <Opportunity />
            <K.Card title={`Planlar (${plans.filter((p) => p.plan).length})`}
              actions={<K.SearchField value={draft} onChange={setDraft} onSubmit={add} placeholder="Listeye ekle: BTC, THYAO, NVDA" />}>
              {!plans.length ? <EmptyState text="Kayıtlı plan yok. Bir kodu analiz ettirince yapay zekâ plan kurar; ya da listeye ekle." /> : (
                <K.DataTable columns={cols} rows={plans} rowKey="key" onRowClick={(r) => navigate(chartHref(r.kod, r.piyasa))}
                  mobileEnd={(r) => (r.plan ? <b className={STATE_CLS[STATE_TONE[r.durum] || "flat"]}>{r.durum}</b> : "—")} />
              )}
              <p className="kp-note">Yüzdeler şu anki fiyata göre uzaklık. “Tetiğin üstünde” AL demek değildir: teyit kapanışı ve kod kapısı gerekir. Satıra tıkla: grafikte seviyeler çizili açılır.</p>
            </K.Card>
          </div>
        );
      }}
    </DataView>
  );
}
