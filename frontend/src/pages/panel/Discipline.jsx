import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { DataView, StatCard, Panel } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { formatNumber, formatPct, formatTime } from "@/lib/format";
import { money, qty } from "@/lib/portfolio";
import { cn } from "@/lib/utils";
import { MarketTag } from "@/components/bits";
import { ShieldCheck, ShieldOff, Flame, Ban, CheckCircle2 } from "lucide-react";

// Korku & açgözlülük 0–100 yarım daire göstergesi
function Gauge({ value, label }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  const angle = Math.PI * (1 - v / 100);
  const x = 60 + 48 * Math.cos(angle);
  const y = 60 - 48 * Math.sin(angle);
  const tone = v >= 75 ? "text-down" : v >= 55 ? "text-wait" : v <= 25 ? "text-info" : "text-t-1";
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 120 70" className="w-48">
        <defs>
          <linearGradient id="fg" x1="0" x2="1">
            <stop offset="0%" stopColor="rgb(var(--c-info))" />
            <stop offset="50%" stopColor="rgb(var(--c-t3))" />
            <stop offset="75%" stopColor="rgb(var(--c-wait))" />
            <stop offset="100%" stopColor="rgb(var(--c-down))" />
          </linearGradient>
        </defs>
        <path d="M12 60 A48 48 0 0 1 108 60" fill="none" stroke="url(#fg)" strokeWidth="9" strokeLinecap="round" />
        <circle cx={x} cy={y} r="6" fill="rgb(var(--c-t1))" stroke="rgb(var(--c-surface))" strokeWidth="2" />
      </svg>
      <div className={cn("num -mt-2 text-3xl font-semibold", tone)}>{v}</div>
      <div className="text-sm text-t-2">{label}</div>
    </div>
  );
}

function ShadowCard({ cur, o }) {
  const shadow = (o.net || 0) + (o.acik_net || 0);
  const real = o.gercek_net || 0;
  const max = Math.max(Math.abs(shadow), Math.abs(real), 1);
  const Bar = ({ label, v }) => (
    <div>
      <div className="mb-1 flex justify-between text-xs text-t-2"><span>{label}</span><span className={cn("num font-semibold", v >= 0 ? "text-up" : "text-down")}>{formatNumber(v, { decimals: 2, sign: true })} {cur}</span></div>
      <div className="h-2 rounded-full bg-raised">
        <div className={cn("h-2 rounded-full", v >= 0 ? "bg-up" : "bg-down")} style={{ width: `${(Math.abs(v) / max) * 100}%` }} />
      </div>
    </div>
  );
  return (
    <div className="space-y-3 rounded-lg border border-hairline p-4">
      <div className="flex items-center justify-between">
        <MarketTag m={cur === "TL" ? "BIST" : "KRIPTO"} className="font-semibold text-t-1" />
        <span className="text-xs text-t-3">{o.sinyal} sinyal · {o.kapanan} kapandı ({o.kazanan} kazanan) · {o.acik} açık</span>
      </div>
      <Bar label="Botun her ŞİMDİ AL'ını alsaydın" v={shadow} />
      <Bar label={`Senin gerçek sonucun (${o.aldigin} alım)`} v={real} />
    </div>
  );
}

export default function Discipline() {
  const q = useData("extras", "/extras", LIVE);
  return (
    <div>
      <PageHeader title="Disiplin ve günlük"
        subtitle="Tilt koruması, gölge portföy, işlem günlüğü ve birikim planları." testid="page-discipline" />
      <DataView query={q} loadingText="Disiplin verisi yükleniyor...">
        {(d) => {
          if (!d.guncelleme) return <EmptyState text="Bot henüz bu verileri göndermedi (15 dakikada bir gönderir)." />;
          const disc = d.disiplin || {};
          const j = d.gunluk || {};
          const golge = Object.entries(d.golge || {});
          const events = Object.entries(disc.olaylar || {});
          const fg = d.duygu?.korku_acgozluluk;
          return (
            <div className="space-y-6">
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard label="Disiplin kalkanı" value={disc.aktif ? "Açık" : "Kapalı"} tone={disc.aktif ? "up" : "down"} glow
                  icon={disc.aktif ? ShieldCheck : ShieldOff} sub={disc.aktif ? "kurallar devrede" : "Telegram: /disiplin"} />
                <StatCard label="Zarar serisi" value={formatNumber(disc.seri ?? 0, { decimals: 0 })} icon={Flame}
                  tone={disc.bekleme_bitis ? "down" : undefined}
                  sub={disc.bekleme_bitis ? `bekleme ${formatTime(disc.bekleme_bitis)}'e kadar` : "yeni giriş serbest"} />
                {["KRIPTO", "BIST"].map((m) => {
                  const p = disc.piyasa?.[m] || {};
                  return (
                    <StatCard key={m} label={<MarketTag m={m} label={`${m === "KRIPTO" ? "Kripto" : "BIST"} bugün`} />}
                      value={money(-(p.gunluk_zarar || 0), m === "KRIPTO" ? "USD" : "TL")}
                      tone={p.engel ? "down" : undefined} icon={p.engel ? Ban : CheckCircle2}
                      sub={p.engel ? "Günlük zarar sınırı doldu: yeni giriş yok" : "Yeni giriş serbest"} />
                  );
                })}
              </div>

              <div className="grid gap-6 lg:grid-cols-2">
                <Panel title="Gölge portföy (son 30 gün)" testid="dc-shadow">
                  {!golge.length ? <p className="text-sm text-t-2">Henüz kapıdan geçmiş ŞİMDİ AL sinyali yok.</p> : (
                    <div className="space-y-3">{golge.map(([cur, o]) => <ShadowCard key={cur} cur={cur} o={o} />)}</div>
                  )}
                </Panel>

                <Panel title="İşlem günlüğü (son 30 gün)" testid="dc-journal">
                  <div className="grid grid-cols-2 gap-3">
                    <StatCard label="Kapanan işlem" value={formatNumber(j.islem || 0, { decimals: 0 })} />
                    <StatCard label="En sık hata" value={j.en_sik_hata ? j.en_sik_hata.sayi : "—"}
                      sub={j.en_sik_hata ? j.en_sik_hata.hata : "tekrarlayan hata yok"} tone={j.en_sik_hata ? "wait" : "up"} />
                  </div>
                  <div className="mt-4 space-y-2 text-sm text-t-2">
                    {j.plan_uyumu && (
                      <p>Plana uyum: stop uygulandı <b className="text-t-1">{j.plan_uyumu.stop_uygulandi}</b> · hedefte <b className="text-t-1">{j.plan_uyumu.hedef}</b> · arada <b className="text-t-1">{j.plan_uyumu.arada}</b>
                        {j.plan_uyumu.gec_stop ? <span className="text-wait"> · geç stop {j.plan_uyumu.gec_stop}</span> : null}</p>
                    )}
                    {j.satis_sonrasi?.n ? (
                      <p>Satıştan 5 gün sonra ortalama <b className="num text-t-1">{formatPct(j.satis_sonrasi.ort_5g)}</b> · erken satış {j.satis_sonrasi.erken} · iyi çıkış {j.satis_sonrasi.iyi}</p>
                    ) : null}
                    {events.length > 0 && (
                      <div className="flex flex-wrap gap-2 pt-1">
                        {events.map(([k, v]) => <span key={k} className="rounded-md bg-wait/15 px-2 py-0.5 text-xs font-semibold text-wait">{k}: {v}</span>)}
                      </div>
                    )}
                    <p className="text-xs text-t-3">Neden aldım / sattım notları: Telegram /gunluk</p>
                  </div>
                </Panel>
              </div>

              <div className="grid gap-6 lg:grid-cols-3">
                <Panel title="Birikim planları" testid="dc-dca" className="lg:col-span-2">
                  {!d.birikim?.length ? <p className="text-sm text-t-2">Birikim planı yok. Telegram: /birikim ekle BTC 50 gun=5</p> : (
                    <div className="grid gap-3 sm:grid-cols-2">
                      {d.birikim.map((b) => (
                        <div key={b.id} className="rounded-lg border border-hairline p-4">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-t-1">{b.varlik}</span>
                            <span className="text-xs text-t-3">#{b.id}</span>
                          </div>
                          <p className="mt-1 text-sm text-t-2">Her ayın {b.gun}'i <b className="num text-t-1">{money(b.tutar, b.para)}</b></p>
                          <p className="mt-1 text-xs text-t-3">{b.adet ? `${qty(b.adet)} adet · ort. ${formatNumber(b.ortalama, { decimals: 2 })}` : "henüz alım yok"}</p>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="mt-4 border-t border-hairline pt-4">
                    <p className="mb-2 text-xs font-semibold text-t-2">Plan listesi</p>
                    {d.plan_listesi?.length ? (
                      <div className="flex flex-wrap gap-2">{d.plan_listesi.map((p) => <span key={p} className="rounded-md border border-hairline bg-raised px-2 py-1 text-xs font-semibold text-t-1">{p}</span>)}</div>
                    ) : <p className="text-sm text-t-2">Boş (tüm planlar izlenir). Telegram: /plan ekle BTC THYAO</p>}
                  </div>
                </Panel>

                <Panel title="Kripto piyasa duygusu" testid="dc-sentiment">
                  {fg?.deger === undefined ? <p className="text-sm text-t-2">Veri yok.</p> : (
                    <>
                      <Gauge value={fg.deger} label={fg.etiket} />
                      {d.duygu?.piyasa?.btc_dominans ? (
                        <p className="mt-4 text-center text-xs text-t-2">BTC dominansı <span className="num text-t-1">{formatPct(d.duygu.piyasa.btc_dominans, { sign: false })}</span></p>
                      ) : null}
                      <p className="mt-2 text-center text-xs text-t-3">Aşırı açgözlülükte bot yeni girişte daha seçici olur.</p>
                    </>
                  )}
                </Panel>
              </div>
            </div>
          );
        }}
      </DataView>
    </div>
  );
}
