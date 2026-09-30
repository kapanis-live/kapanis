import { FlashValue } from "@/components/kp";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { chartHref } from "@/components/AssetLogo";
import api, { formatApiErrorDetail } from "@/lib/api";
import { logo } from "@/lib/dsmap";
import { usePortfolioStream } from "@/lib/live";

// Kullanıcının kendi gerçek portföyü (Claude Design "Kullanıcı paneli · Portföyüm").
// Yalnız onun hesabında tutulur; Kapanış işlem yapmaz, aracı kuruma bağlanmaz.
const MK = { BIST: { label: "BIST", cur: "TRY" }, KRIPTO: { label: "Kripto", cur: "USD" }, ABD: { label: "ABD", cur: "USD" } };
const FROM_FORM = { bist: "BIST", kripto: "KRIPTO", abd: "ABD" };
const CUR = { TL: "TRY", USD: "USD" };

async function call(fn, okText) {
  try {
    const r = await fn();
    if (okText) toast.success(okText);
    return r?.data ?? true;
  } catch (e) {
    toast.error(formatApiErrorDetail(e.response?.data?.detail) || "İşlem yapılamadı.");
    return null;
  }
}

function BuyCard({ onDone }) {
  const [n, setN] = useState(0); // yeni form: kayıttan sonra alanlar temizlensin
  const [tez, setTez] = useState("");
  const [sart, setSart] = useState("");
  const submit = async (r) => {
    const body = { piyasa: FROM_FORM[r.market], kod: r.code, adet: r.qty, maliyet: r.price, stop: r.stop, hedef: r.target,
      ...(tez.trim() ? { tez: tez.trim(), cikis_sarti: sart.trim() } : {}) };
    if (await call(() => api.post("/portfolio/positions", body), `${r.code} portföyüne eklendi.`)) {
      onDone();
      setTez(""); setSart("");
      setTimeout(() => setN((x) => x + 1), 1500);
    }
  };
  return <K.Card title="Alım ekle">
    <K.BuyForm key={n} onSubmit={submit} />
    <div className="mt-4 grid gap-3 border-t border-hairline pt-4 sm:grid-cols-2">
      <K.Field label="💊 Neden alıyorum? (karar kapsülü)" hint="30 gün sonra bu not ve o günden beri olan sana geri gelir">
        <K.TextInput value={tez} maxLength={500} placeholder="ör. bilanço iyi gelecek, sektör güçleniyor" onChange={(e) => setTez(e.target.value)} />
      </K.Field>
      <K.Field label="Ne olursa satarım?" hint="isteğe bağlı">
        <K.TextInput value={sart} maxLength={300} placeholder="ör. 90 altında kapanış ya da bilanço kötü gelirse" onChange={(e) => setSart(e.target.value)} />
      </K.Field>
    </div>
    <p className="mt-3 text-sm text-muted">Telegram’dan da eklenir (hesabın bağlıysa): <code>/ekle THYAO 10 300</code> · <code>/ekle BTC 0.05 62000</code> · <code>/ekle NVDA 3 120</code></p>
  </K.Card>;
}

function CashCard({ cash, onDone }) {
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({ TL: String(cash?.TL ?? 0), USD: String(cash?.USD ?? 0) });
  const save = async () => {
    for (const para of ["TL", "USD"]) {
      const v = U.parseTr(f[para]);
      if (!(v >= 0)) return toast.error("Nakit sıfır ya da pozitif olmalı.");
      if (v !== cash?.[para] && !(await call(() => api.put("/portfolio/cash", { para, tutar: v })))) return;
    }
    toast.success("Nakit güncellendi.");
    setEdit(false);
    onDone();
  };
  return (
    <K.Card title="Nakit" actions={<K.Button variant="ghost" onClick={() => setEdit(!edit)}>{edit ? "Vazgeç" : "Düzenle"}</K.Button>}>
      {edit ? (
        <div className="kp-col">
          <K.Field label="TL"><K.TextInput prefix="₺" inputMode="decimal" value={f.TL} onChange={(e) => setF({ ...f, TL: e.target.value })} /></K.Field>
          <K.Field label="Dolar"><K.TextInput prefix="$" inputMode="decimal" value={f.USD} onChange={(e) => setF({ ...f, USD: e.target.value })} /></K.Field>
          <K.Button variant="primary" onClick={save}>Kaydet</K.Button>
        </div>
      ) : (
        <dl className="kp-kv" style={{ gridTemplateColumns: "auto minmax(0,1fr)" }}>
          <dt>TL</dt><dd style={{ fontSize: "1.375rem", fontWeight: 700, textAlign: "right" }}>{U.fmtPrice(cash?.TL || 0, "TRY", 2)}</dd>
          <dt>Dolar</dt><dd style={{ fontSize: "1.375rem", fontWeight: 700, textAlign: "right" }}>{U.fmtPrice(cash?.USD || 0, "USD", 2)}</dd>
        </dl>
      )}
    </K.Card>
  );
}

function FirstRun({ tg, keys, onAdd }) {
  const navigate = useNavigate();
  const hasKey = Object.values(keys?.anahtarlar || {}).some(Boolean);
  return (
    <>
      <K.SetupChecklist title="İlk kurulum" steps={[
        { title: "İlk alımını ekle", detail: "Kod, adet, alış fiyatı ve stop. Portföyün ve K/Z buradan hesaplanır.",
          action: <K.Button variant="primary" icon={<K.Icon name="plus" size={18} />} onClick={onAdd}>Alım ekle</K.Button> },
        { title: "Telegram’ı bağla", detail: "İstediğin analizlerin sonucu telefonuna da gelir.", done: !!tg?.bagli,
          action: <K.Button variant="secondary" icon={<K.Icon name="send" size={18} />} onClick={() => navigate("/app/hesap")}>Bağla</K.Button> },
        { title: "Kendi yapay zekâ anahtarını ekle", optional: true, done: hasKey, detail: "Günlük analiz hakkın artar. Eklemesen de olur.",
          action: <K.Button variant="secondary" icon={<K.Icon name="key" size={18} />} onClick={() => navigate("/app/hesap")}>Anahtar ekle</K.Button> },
      ]} />
      <section className="kp-card">
        <div className="kp-card__head"><h2 className="kp-card__title">Örnek görünüm</h2><span className="kp-alarm__status is-flat">Alım ekleyince dolar</span></div>
        <div aria-hidden style={{ opacity: 0.55 }}>
          <K.Skeleton tiles={4} rows={0} label=" " />
        </div>
        <div style={{ marginTop: "1rem" }}>
          <K.EmptyState bordered={false} icon="portfolio" title="Henüz pozisyon yok"
            action={<K.Button variant="secondary" icon={<K.Icon name="plus" size={18} />} onClick={onAdd}>İlk alımını ekle</K.Button>}>
            İlk alımını eklediğinde burada piyasa özetleri, açık pozisyonların ve nakdin görünür.
          </K.EmptyState>
        </div>
      </section>
    </>
  );
}

export default function MyPortfolio() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  // Anlık: Telegram'dan /ekle ya da başka sekmedeki değişiklik sunucudan olay olarak gelir; 8 sn'lik yenileme yedek
  const q = useData("my-portfolio", "/portfolio", LIVE);
  const quotes = useData("my-quotes", "/portfolio/quotes", { refetchInterval: 60_000 });
  const tg = useData("tg-status", "/telegram/status");
  const keys = useData("ai-keys", "/ai-keys");
  const [showBuy, setShowBuy] = useState(false);
  const buyRef = useRef(null);
  usePortfolioStream(() => {
    qc.invalidateQueries({ queryKey: ["my-portfolio"] });
    qc.invalidateQueries({ queryKey: ["my-quotes"] });
  });
  // Yeni gelen pozisyonu kısa süre vurgula (ilk yüklemede değil); Telegram'dan geldiyse haber ver
  const seen = useRef(null);
  const [newIds, setNewIds] = useState([]);
  useEffect(() => {
    const open = (q.data?.positions || []).filter((p) => p.durum === "acik");
    if (!q.data) return undefined;
    if (seen.current === null) {
      seen.current = new Set(open.map((p) => p.id));
      return undefined;
    }
    const added = open.filter((p) => !seen.current.has(p.id));
    open.forEach((p) => seen.current.add(p.id));
    if (!added.length) return undefined;
    added.filter((p) => p.kaynak === "telegram").forEach((p) => toast.success(`${p.kod} Telegram'dan portföyüne eklendi.`));
    setNewIds((f) => [...f, ...added.map((p) => p.id)]);
    const t = setTimeout(() => setNewIds((f) => f.filter((id) => !added.some((p) => p.id === id))), 4000);
    return () => clearTimeout(t);
  }, [q.data]);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["my-portfolio"] });
    qc.invalidateQueries({ queryKey: ["my-quotes"] });
  };
  const openBuy = () => {
    setShowBuy(true);
    setTimeout(() => buyRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };
  return (
    <DataView query={q} loadingText="Portföy yükleniyor...">
      {(d) => {
        const open = d.positions.filter((p) => p.durum === "acik");
        const closed = d.positions.filter((p) => p.durum !== "acik").slice(-10).reverse();
        const px = (p) => quotes.data?.[`${p.piyasa}:${p.kod}`] ?? null;
        const fresh = !d.positions.length && !d.transactions.length;
        const sum = (mkt) => {
          const rows = open.filter((p) => p.piyasa === mkt);
          const value = rows.reduce((a, p) => a + (px(p) ?? p.maliyet) * p.adet, 0);
          const cost = rows.reduce((a, p) => a + p.maliyet * p.adet, 0);
          return { n: rows.length, value, pl: value - cost, pct: cost ? (value / cost - 1) * 100 : 0 };
        };
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title="Portföyüm"
              subtitle={fresh ? "Hoş geldin. Üç adımda hazırsın." : "Son kapanmış günlük mumlara göre · yalnız senin hesabında"} />
            {!fresh && <div className="flex justify-end"><K.Button variant="secondary" onClick={() => navigate("/app/kriz")}>Kriz planını incele</K.Button></div>}
            {fresh ? (
              <FirstRun tg={tg.data} keys={keys.data} onAdd={openBuy} />
            ) : (
              <>
                <div className="kp-grid kp-g-4 kp-scroll">
                  {Object.entries(MK).map(([m, info]) => {
                    const s = sum(m);
                    return <K.StatCard key={m} label={`${info.label} · ${s.n} pozisyon`} value={<FlashValue value={s.value}>{U.fmtPrice(s.value, info.cur, 2)}</FlashValue>}
                      change={s.n ? s.pct : undefined} changeLabel="Açık" sub={s.n ? `K/Z ${U.fmtSignedMoney(s.pl, info.cur)}` : "pozisyon yok"} />;
                  })}
                  <CashCard key={JSON.stringify(d.cash_balance)} cash={d.cash_balance} onDone={refresh} />
                </div>
                <h2 className="kp-card__title" style={{ marginTop: "0.5rem" }}>Açık pozisyonlar ({open.length})</h2>
                {open.length ? (
                  <div className="kp-grid kp-g-2">
                    {open.map((p) => {
                      const price = px(p);
                      return (
                        <div key={p.id} className={newIds.includes(p.id) ? "kp-position-enter kp-position-new" : undefined}>
                          {p.kaynak === "telegram" && <span className="kp-alarm__status is-flat" style={{ display: "inline-block", marginBottom: "0.5rem" }}>Telegram’dan eklendi</span>}
                          <K.PositionCard symbol={p.kod} name={MK[p.piyasa]?.label} logo={logo(p.kod, p.piyasa)}
                          qty={p.adet} cost={p.maliyet} price={price ?? p.maliyet} cur={CUR[p.para]} stop={p.stop ?? undefined} target={p.hedef ?? undefined}
                          priceLabel={price == null ? "Fiyat alınamadı (alış)" : undefined}
                          onOpenChart={() => navigate(chartHref(p.kod, p.piyasa))}
                          onRaiseStop={async (e) => { if (await call(() => api.patch(`/portfolio/positions/${p.id}/stop`, { stop: e.stop }), "Stop yükseltildi.")) refresh(); }}
                          onSold={async (e) => {
                            const r = await call(() => api.post(`/portfolio/positions/${p.id}/sell`, { fiyat: e.price }));
                            if (r) { toast.success(`${p.kod} satışı kaydedildi: ${U.fmtSignedMoney(r.kar, CUR[p.para])}`); refresh(); }
                          }} /></div>
                      );
                    })}
                  </div>
                ) : (
                  <K.EmptyState icon="portfolio" title="Açık pozisyon yok"
                    action={<K.Button variant="secondary" icon={<K.Icon name="plus" size={18} />} onClick={openBuy}>Alım ekle</K.Button>}>
                    Yeni bir alım eklediğinde burada görünür.
                  </K.EmptyState>
                )}
              </>
            )}
            {(!fresh || showBuy) && (
              <div ref={buyRef} className="kp-grid kp-split-l" style={{ marginTop: "0.5rem" }}>
                <BuyCard onDone={refresh} />
                {!fresh && (
                  <K.Card title="Son kapananlar">
                    {closed.length ? (
                      <K.DataTable rows={closed} rowKey="id"
                        mobileEnd={(r) => <span className={r.kapanis_fiyat >= r.maliyet ? "kp-num-up" : "kp-num-down"}>{U.fmtSignedMoney((r.kapanis_fiyat - r.maliyet) * r.adet, CUR[r.para])}</span>}
                        columns={[
                          { key: "kod", label: "Kod", render: (r) => <K.Ticker symbol={r.kod} logo={logo(r.kod, r.piyasa)} /> },
                          { key: "bs", label: "Alış → satış", num: true, render: (r) => `${U.fmtPrice(r.maliyet, CUR[r.para])} → ${U.fmtPrice(r.kapanis_fiyat, CUR[r.para])}` },
                          { key: "pl", label: "K/Z", num: true, mobile: false, render: (r) => <span className={r.kapanis_fiyat >= r.maliyet ? "kp-num-up" : "kp-num-down"}>{U.fmtSignedMoney((r.kapanis_fiyat - r.maliyet) * r.adet, CUR[r.para])}</span> },
                          { key: "pct", label: "%", num: true, render: (r) => <K.ChangeBadge value={(r.kapanis_fiyat / r.maliyet - 1) * 100} /> },
                        ]} />
                    ) : <K.EmptyState icon="portfolio" title="Kapanan pozisyon yok" bordered={false}>“Sattım” dediğin pozisyonlar burada K/Z’siyle listelenir.</K.EmptyState>}
                  </K.Card>
                )}
              </div>
            )}
          </div>
        );
      }}
    </DataView>
  );
}
