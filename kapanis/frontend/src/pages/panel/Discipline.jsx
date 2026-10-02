import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { relDay, curOf, logo, splitAi } from "@/lib/dsmap";
import { sendAction } from "@/lib/actions";

const code = (s) => String(s || "").split("/")[0].replace(/\.(IS|US)$/i, "");
const MK = [["KRIPTO", "Kripto"], ["BIST", "BIST"], ["ABD", "ABD"]];

export default function Discipline() {
  const q = useData("extras", "/extras", LIVE);
  const rq = useData("report", "/report");
  return (
    <DataView query={q} loadingText="Disiplin verisi yükleniyor...">
      {(d) => {
        if (!d.guncelleme) return <EmptyState text="Bot henüz bu verileri göndermedi (15 dakikada bir gönderir)." />;
        const disc = d.disiplin || {};
        const markets = disc.piyasa || {};
        const blocked = MK.find(([m]) => markets[m]?.engel);
        const state = !disc.aktif ? "kapali" : disc.bekleme_bitis || blocked ? "engel" : disc.seri >= 1 ? "uyari" : "acik";
        const limitStreak = disc.seri_sinir ?? 2;
        const detail = !disc.aktif ? "Kurallar kapalı. Aşağıdan açabilirsin."
          : disc.bekleme_bitis ? `Üst üste ${disc.seri} zarar: ${relDay(disc.bekleme_bitis)}'e kadar yeni AL gösterilmez (tilt koruması).`
          : blocked ? markets[blocked[0]].engel
          : disc.seri >= 1 ? `Üst üste ${disc.seri} zarar. Seri ${limitStreak}'ye ulaşırsa ${disc.bekleme_saat ?? 24} saat boyunca yeni AL gösterilmez.`
          : "Zarar serisi yok; yeni girişler serbest.";
        const trades = rq.data?.trades || [];
        const last10 = trades.slice(0, 10).reverse();
        const g = Object.entries(d.golge || {});
        const j = d.gunluk || {};
        const events = Object.entries(disc.olaylar || {});
        const fg = d.duygu?.korku_acgozluluk;
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title="Disiplin" subtitle="Kurallar kodda. Bot hatırlatır, işlem yapmaz." />
            <K.ShieldStatus state={state} detail={detail} />
            <div className="flex flex-wrap gap-3">
              <K.Button onClick={() => sendAction("discipline.set", { islem: disc.aktif ? "kapat" : "ac" }, disc.aktif ? "Disiplin kalkanı kapatılıyor (kayda geçer)." : "Disiplin kalkanı açılıyor.")}>
                {disc.aktif ? "Kalkanı kapat" : "Kalkanı aç"}
              </K.Button>
              {disc.seri >= 1 && (
                <K.Button variant="ghost" onClick={() => sendAction("discipline.set", { islem: "sifirla" }, "Zarar serisi sıfırlanıyor (kural olayı olarak kaydedilir).")}>
                  Zarar serisini sıfırla
                </K.Button>
              )}
            </div>
            <K.Card title="Haftanın dersi" actions={<K.Button variant="ghost" onClick={() => sendAction("lesson.request", {}, "Haftalık ders hazırlanıyor.")}>Şimdi hazırla</K.Button>}>
              {d.ders ? (() => {
                const ai = splitAi(d.ders.metin);
                return (
                  <K.AiNote model={ai.model || "Yapay zekâ"} time={relDay(d.ders.zaman)} title="Bu haftadan ders" footnote="Sayıları kod hesapladı; model yalnız yorumladı. Öneri değildir.">
                    {ai.body.split(/\n{2,}/).map((t, i) => <p key={i} style={{ whiteSpace: "pre-wrap" }}>{t}</p>)}
                  </K.AiNote>
                );
              })() : <p className="kp-note">Her pazar 20:10'da hangi kuralın işe yaradığını, pas geçip kaçırdığın ya da iyi ki pas geçtiğin sinyalleri ve en sık hatayı 5 cümlede yazarım. Beklemek istemezsen “Şimdi hazırla”.</p>}
            </K.Card>
            <div className="kp-grid kp-g-3">
              <K.Card title="Zarar serisi">
                {last10.length ? <K.StreakStrip results={last10.map((t) => ({ r: t.r, symbol: code(t.symbol), date: relDay(t.closed_at) }))} />
                  : <p className="kp-note">Henüz kapanmış işlem yok.</p>}
                <p className="kp-note">Son {last10.length} kapanış, eskiden yeniye. Şu an seri {disc.seri ?? 0} · sınır {limitStreak}.</p>
              </K.Card>
              <K.Card title="Günlük zarar sınırı">
                <div className="kp-col">
                  {MK.filter(([m]) => markets[m]).map(([m, label]) => {
                    const p = markets[m];
                    return p.gunluk_sinir
                      ? <K.LimitMeter key={m} label={label} used={Math.max(0, p.gunluk_zarar || 0)} limit={p.gunluk_sinir} cur={curOf(p.para)} note={`bütçenin %${U.fmtNum(disc.gunluk_zarar_yuzde ?? 3, 0)}'ü`} />
                      : <p key={m} className="kp-note">{label}: bütçe girilmediği için sınır yok (Telegram: /{m === "ABD" ? "abd" : m === "BIST" ? "bist" : "bakiye"} ...)</p>;
                  })}
                </div>
                <p className="kp-note">Sınır aşılırsa o piyasada gün sonuna kadar yeni giriş yok. Gerçekleşen zarar sayılır.</p>
              </K.Card>
              <K.Card title="Korku-açgözlülük">
                {fg?.deger != null ? <K.FearGreedGauge value={fg.deger}
                  note={`Kripto kapısında yalnız ilk kademenin boyutunu etkiler; giriş nedeni değildir.${d.duygu?.piyasa?.btc_dominans ? ` BTC dominansı %${U.fmtNum(d.duygu.piyasa.btc_dominans, 1)}.` : ""}`} />
                  : <p className="kp-note">Veri yok.</p>}
              </K.Card>
            </div>

            <h2 className="kp-card__title" style={{ marginTop: "0.5rem" }}>Gölge portföy · son 30 gün</h2>
            {g.length ? g.map(([cur, o]) => {
              const c = curOf(cur);
              const shadow = (o.net || 0) + (o.acik_net || 0);
              const real = o.gercek_net || 0;
              return (
                <div key={cur} className="kp-grid kp-g-4">
                  <K.StatCard label={`${c === "TRY" ? "BIST" : "Kripto"} · botun AL sinyali`} value={String(o.sinyal)} sub={`${o.kapanan} kapandı · ${o.acik} açık`} />
                  <K.StatCard label="Botun her AL'ı (gölge)" value={U.fmtSignedMoney(shadow, c)} tone={shadow >= 0 ? "up" : "down"} sub={`${o.kazanan} kazanan`} />
                  <K.StatCard label="Benim sonucum" value={U.fmtSignedMoney(real, c)} tone={real >= 0 ? "up" : "down"} sub={`${o.aldigin} alım`} />
                  <K.StatCard label="Fark" value={U.fmtSignedMoney(real - shadow, c)} tone={real - shadow >= 0 ? "up" : "down"} sub={real - shadow >= 0 ? "botun önündesin" : "botun gerisindesin"} />
                </div>
              );
            }) : <p className="kp-note">Henüz kapıdan geçmiş AL sinyali yok.</p>}
            <p className="kp-note">Gölge portföy: botun her AL'ı sinyal kapanışından alınmış, iptal ve hedefi kapanışlarla uygulanmış sayılır.</p>

            <K.Card title="İşlem günlüğü">
              {events.length > 0 && <K.Callout tone="warn" title={`Son 7 günde ${events.reduce((a, [, v]) => a + v, 0)} kural olayı`}>{events.map(([k, v]) => `${k}: ${v}`).join(" · ")}</K.Callout>}
              {j.en_sik_hata && <K.Callout tone="info" title="En sık hata">{j.en_sik_hata.hata} ({j.en_sik_hata.sayi} kez)</K.Callout>}
              {trades.length ? (
                <div style={{ marginTop: "1rem" }}>
                  <K.DataTable rows={trades.slice(0, 20)} mobileEnd={(r) => <span className={r.r >= 0 ? "kp-num-up" : "kp-num-down"}>{(r.r >= 0 ? "+" : "−") + U.fmtNum(Math.abs(r.r), 1)} R</span>}
                    columns={[
                      { key: "symbol", label: "Kod", render: (r) => <K.Ticker symbol={code(r.symbol)} logo={logo(code(r.symbol), r.market)} /> },
                      { key: "closed_at", label: "Kapanış", render: (r) => relDay(r.closed_at) },
                      { key: "entry", label: "Giriş", num: true, render: (r) => U.fmtPrice(r.entry, curOf(r.currency)) },
                      { key: "exit", label: "Çıkış", num: true, strong: true, render: (r) => U.fmtPrice(r.exit, curOf(r.currency)) },
                      { key: "r", label: "Sonuç", num: true, mobile: false, render: (r) => <span className={r.r >= 0 ? "kp-num-up" : "kp-num-down"}>{(r.r >= 0 ? "+" : "−") + U.fmtNum(Math.abs(r.r), 1)} R</span> },
                    ]} />
                </div>
              ) : <p className="kp-note">Son 30 günde kapanan işlem yok. Neden aldım / sattım notları: Telegram /gunluk</p>}
              {j.plan_uyumu && <p className="kp-note">Plana uyum: stop uygulandı {j.plan_uyumu.stop_uygulandi} · hedefte {j.plan_uyumu.hedef} · arada {j.plan_uyumu.arada}{j.plan_uyumu.gec_stop ? ` · geç stop ${j.plan_uyumu.gec_stop}` : ""}</p>}
            </K.Card>
          </div>
        );
      }}
    </DataView>
  );
}
