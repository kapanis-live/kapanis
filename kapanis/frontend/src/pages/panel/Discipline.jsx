import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { relDay, curOf, logo, splitAi } from "@/lib/dsmap";
import { sendAction } from "@/lib/actions";
import { useLang } from "@/lib/i18n";

const code = (s) => String(s || "").split("/")[0].replace(/\.(IS|US)$/i, "");
const MK = [["KRIPTO", "Kripto"], ["BIST", "BIST"], ["ABD", "ABD"]];

export default function Discipline() {
  const { t } = useLang();
  const q = useData("extras", "/extras", LIVE);
  const rq = useData("report", "/report");
  return (
    <DataView query={q} loadingText={t("Disiplin verisi yükleniyor...")}>
      {(d) => {
        if (!d.guncelleme) return <EmptyState text={t("Bot henüz bu verileri göndermedi (15 dakikada bir gönderir).")} />;
        const disc = d.disiplin || {};
        const markets = disc.piyasa || {};
        const blocked = MK.find(([m]) => markets[m]?.engel);
        const state = !disc.aktif ? "kapali" : disc.bekleme_bitis || blocked ? "engel" : disc.seri >= 1 ? "uyari" : "acik";
        const limitStreak = disc.seri_sinir ?? 2;
        const detail = !disc.aktif ? t("Kurallar kapalı. Aşağıdan açabilirsin.")
          : disc.bekleme_bitis ? t("Üst üste {n} zarar: {d}'e kadar yeni AL gösterilmez (tilt koruması).", { n: disc.seri, d: relDay(disc.bekleme_bitis) })
          : blocked ? markets[blocked[0]].engel
          : disc.seri >= 1 ? t("Üst üste {n} zarar. Seri {l}'ye ulaşırsa {h} saat boyunca yeni AL gösterilmez.", { n: disc.seri, l: limitStreak, h: disc.bekleme_saat ?? 24 })
          : t("Zarar serisi yok; yeni girişler serbest.");
        const trades = rq.data?.trades || [];
        const last10 = trades.slice(0, 10).reverse();
        const g = Object.entries(d.golge || {});
        const j = d.gunluk || {};
        const events = Object.entries(disc.olaylar || {});
        const fg = d.duygu?.korku_acgozluluk;
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title={t("Disiplin")} subtitle={t("Kurallar kodda. Bot hatırlatır, işlem yapmaz.")} />
            <K.ShieldStatus state={state} detail={detail} />
            <div className="flex flex-wrap gap-3">
              <K.Button onClick={() => sendAction("discipline.set", { islem: disc.aktif ? "kapat" : "ac" }, disc.aktif ? t("Disiplin kalkanı kapatılıyor (kayda geçer).") : t("Disiplin kalkanı açılıyor."))}>
                {disc.aktif ? t("Kalkanı kapat") : t("Kalkanı aç")}
              </K.Button>
              {disc.seri >= 1 && (
                <K.Button variant="ghost" onClick={() => sendAction("discipline.set", { islem: "sifirla" }, t("Zarar serisi sıfırlanıyor (kural olayı olarak kaydedilir)."))}>
                  {t("Zarar serisini sıfırla")}
                </K.Button>
              )}
            </div>
            <K.Card title={t("Haftanın dersi")} actions={<K.Button variant="ghost" onClick={() => sendAction("lesson.request", {}, t("Haftalık ders hazırlanıyor."))}>{t("Şimdi hazırla")}</K.Button>}>
              {d.ders ? (() => {
                const ai = splitAi(d.ders.metin);
                return (
                  <K.AiNote model={ai.model || t("Yapay zekâ")} time={relDay(d.ders.zaman)} title={t("Bu haftadan ders")} footnote={t("Sayıları kod hesapladı; model yalnız yorumladı. Öneri değildir.")}>
                    {ai.body.split(/\n{2,}/).map((seg, i) => <p key={i} style={{ whiteSpace: "pre-wrap" }}>{seg}</p>)}
                  </K.AiNote>
                );
              })() : <p className="kp-note">{t("Her pazar 20:10'da hangi kuralın işe yaradığını, pas geçip kaçırdığın ya da iyi ki pas geçtiğin sinyalleri ve en sık hatayı 5 cümlede yazarım. Beklemek istemezsen “Şimdi hazırla”.")}</p>}
            </K.Card>
            <div className="kp-grid kp-g-3">
              <K.Card title={t("Zarar serisi")}>
                {last10.length ? <K.StreakStrip results={last10.map((tr) => ({ r: tr.r, symbol: code(tr.symbol), date: relDay(tr.closed_at) }))} />
                  : <p className="kp-note">{t("Henüz kapanmış işlem yok.")}</p>}
                <p className="kp-note">{t("Son {n} kapanış, eskiden yeniye. Şu an seri {s} · sınır {l}.", { n: last10.length, s: disc.seri ?? 0, l: limitStreak })}</p>
              </K.Card>
              <K.Card title={t("Günlük zarar sınırı")}>
                <div className="kp-col">
                  {MK.filter(([m]) => markets[m]).map(([m, label]) => {
                    const p = markets[m];
                    return p.gunluk_sinir
                      ? <K.LimitMeter key={m} label={t(label)} used={Math.max(0, p.gunluk_zarar || 0)} limit={p.gunluk_sinir} cur={curOf(p.para)} note={t("bütçenin %{n}'ü", { n: U.fmtNum(disc.gunluk_zarar_yuzde ?? 3, 0) })} />
                      : <p key={m} className="kp-note">{t(label)}: {t("bütçe girilmediği için sınır yok (Telegram: /{cmd} ...)", { cmd: m === "ABD" ? "abd" : m === "BIST" ? "bist" : "bakiye" })}</p>;
                  })}
                </div>
                <p className="kp-note">{t("Sınır aşılırsa o piyasada gün sonuna kadar yeni giriş yok. Gerçekleşen zarar sayılır.")}</p>
              </K.Card>
              <K.Card title={t("Korku-açgözlülük")}>
                {fg?.deger != null ? <K.FearGreedGauge value={fg.deger}
                  note={`${t("Kripto kapısında yalnız ilk kademenin boyutunu etkiler; giriş nedeni değildir.")}${d.duygu?.piyasa?.btc_dominans ? ` ${t("BTC dominansı %{n}.", { n: U.fmtNum(d.duygu.piyasa.btc_dominans, 1) })}` : ""}`} />
                  : <p className="kp-note">{t("Veri yok.")}</p>}
              </K.Card>
            </div>

            <h2 className="kp-card__title" style={{ marginTop: "0.5rem" }}>{t("Gölge portföy · son 30 gün")}</h2>
            {g.length ? g.map(([cur, o]) => {
              const c = curOf(cur);
              const shadow = (o.net || 0) + (o.acik_net || 0);
              const real = o.gercek_net || 0;
              return (
                <div key={cur} className="kp-grid kp-g-4">
                  <K.StatCard label={`${c === "TRY" ? "BIST" : t("Kripto")} · ${t("botun AL sinyali")}`} value={String(o.sinyal)} sub={t("{a} kapandı · {b} açık", { a: o.kapanan, b: o.acik })} />
                  <K.StatCard label={t("Botun her AL'ı (gölge)")} value={U.fmtSignedMoney(shadow, c)} tone={shadow >= 0 ? "up" : "down"} sub={t("{n} kazanan", { n: o.kazanan })} />
                  <K.StatCard label={t("Benim sonucum")} value={U.fmtSignedMoney(real, c)} tone={real >= 0 ? "up" : "down"} sub={t("{n} alım", { n: o.aldigin })} />
                  <K.StatCard label={t("Fark")} value={U.fmtSignedMoney(real - shadow, c)} tone={real - shadow >= 0 ? "up" : "down"} sub={real - shadow >= 0 ? t("botun önündesin") : t("botun gerisindesin")} />
                </div>
              );
            }) : <p className="kp-note">{t("Henüz kapıdan geçmiş AL sinyali yok.")}</p>}
            <p className="kp-note">{t("Gölge portföy: botun her AL'ı sinyal kapanışından alınmış, iptal ve hedefi kapanışlarla uygulanmış sayılır.")}</p>

            <K.Card title={t("İşlem günlüğü")}>
              {events.length > 0 && <K.Callout tone="warn" title={t("Son 7 günde {n} kural olayı", { n: events.reduce((a, [, v]) => a + v, 0) })}>{events.map(([k, v]) => `${k}: ${v}`).join(" · ")}</K.Callout>}
              {j.en_sik_hata && <K.Callout tone="info" title={t("En sık hata")}>{j.en_sik_hata.hata} ({t("{n} kez", { n: j.en_sik_hata.sayi })})</K.Callout>}
              {trades.length ? (
                <div style={{ marginTop: "1rem" }}>
                  <K.DataTable rows={trades.slice(0, 20)} mobileEnd={(r) => <span className={r.r >= 0 ? "kp-num-up" : "kp-num-down"}>{(r.r >= 0 ? "+" : "−") + U.fmtNum(Math.abs(r.r), 1)} R</span>}
                    columns={[
                      { key: "symbol", label: t("Kod"), render: (r) => <K.Ticker symbol={code(r.symbol)} logo={logo(code(r.symbol), r.market)} /> },
                      { key: "closed_at", label: t("Kapanış"), render: (r) => relDay(r.closed_at) },
                      { key: "entry", label: t("Giriş"), num: true, render: (r) => U.fmtPrice(r.entry, curOf(r.currency)) },
                      { key: "exit", label: t("Çıkış"), num: true, strong: true, render: (r) => U.fmtPrice(r.exit, curOf(r.currency)) },
                      { key: "r", label: t("Sonuç"), num: true, mobile: false, render: (r) => <span className={r.r >= 0 ? "kp-num-up" : "kp-num-down"}>{(r.r >= 0 ? "+" : "−") + U.fmtNum(Math.abs(r.r), 1)} R</span> },
                    ]} />
                </div>
              ) : <p className="kp-note">{t("Son 30 günde kapanan işlem yok. Neden aldım / sattım notları: Telegram /gunluk")}</p>}
              {j.plan_uyumu && <p className="kp-note">{t("Plana uyum: stop uygulandı {a} · hedefte {b} · arada {c}", { a: j.plan_uyumu.stop_uygulandi, b: j.plan_uyumu.hedef, c: j.plan_uyumu.arada })}{j.plan_uyumu.gec_stop ? t(" · geç stop {n}", { n: j.plan_uyumu.gec_stop }) : ""}</p>}
            </K.Card>
          </div>
        );
      }}
    </DataView>
  );
}
