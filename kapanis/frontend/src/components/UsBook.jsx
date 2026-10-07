import { useState } from "react";
import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { sendAction } from "@/lib/actions";
import { relDay } from "@/lib/dsmap";

// Portföy sağlığı: ABD hisselerinin ortak yanı (sektör, tema, birlikte hareket, beta, senaryolar). Bot hesaplar.
const pct = (v, d = 1) => (v == null ? "—" : `%${U.fmtNum(v, d)}`);
const signed = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 1)}`);
const RULER = "Senaryo cetvelidir, tahmin değildir.";

function Bars({ rows }) {
  return (
    <div className="flex flex-col gap-2">
      {rows.map(([name, value, note]) => (
        <div key={name}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-t-1">{name}{note ? <span className="text-t-3"> · {note}</span> : null}</span>
            <b className="num text-t-1">{pct(value)}</b>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-raised" aria-hidden="true">
            <div className="h-full rounded-full bg-brand" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function UsBook() {
  const q = useData(["sonuclar", "abd_portfoy"], "/sonuclar/abd_portfoy", LIVE);
  const [asked, setAsked] = useState(null);
  const d = q.data || {};
  const waiting = asked && (!d.zaman || new Date(d.zaman).getTime() < asked - 2000);
  const run = async () => {
    if (await sendAction("us.portfolio", {}, "ABD portföyü hesaplanıyor.")) setAsked(Date.now());
  };
  const action = <K.Button variant="secondary" onClick={run} disabled={!!waiting} data-testid="us-book-run">{waiting ? "Hesaplanıyor…" : d.zaman ? "Yenile" : "Hesapla"}</K.Button>;
  const ready = !waiting && d.zaman && !d.hata && !d.bos && d.agirlik_yuzde;
  return (
    <K.Card title="ABD hisseleri: ortak risk" actions={action}>
      <p className="m-0 text-t-2">Yedi ayrı hisse, aynı hikâyeye bağlıysa tek pozisyon gibi davranır. Bu bölüm botun portföyündeki ABD hisselerini
        sektör, tema, birlikte hareket ve dört senaryo üzerinden gösterir. Öneri içermez.</p>
      {waiting && <p className="kp-note" aria-busy="true">Bot bir yıllık fiyatları ve sektörleri topluyor (10–40 sn)…</p>}
      {!waiting && d.hata && <K.Callout tone="warn" title="Hesaplanamadı">{d.hata}</K.Callout>}
      {!waiting && d.bos && <p className="kp-note">Botta açık ABD pozisyonu yok. Telegram: /portfoy ekle NVDA 2 230</p>}
      {!waiting && !d.zaman && <p className="kp-note">Henüz hesaplanmadı. "Hesapla"ya bas; sonuç burada kalır.</p>}
      {ready && (
        <div className="mt-4 flex flex-col gap-5" data-testid="us-book">
          <div className="kp-grid kp-g-4">
            <K.StatCard label="ABD toplamı" value={`$${U.fmtNum(d.toplam_usd, 0)}`} sub={`${Object.keys(d.agirlik_yuzde).length} hisse · ${relDay(d.zaman)}`} />
            <K.StatCard label="Beta (S&P 500)" value={d.beta?.SPY ?? "—"} sub="1 = endeks kadar oynar" />
            <K.StatCard label="Beta (Nasdaq-100)" value={d.beta?.QQQ ?? "—"} sub="1 = endeks kadar oynar" />
            <K.StatCard label="Ortalama korelasyon" value={d.korelasyon?.ortalama ?? "—"} sub="1 yıl, günlük; 1'e yakın = birlikte hareket" />
          </div>

          {d.dikkat?.length > 0 && (
            <K.Callout tone="warn" title={`${d.dikkat.length} yoğunlaşma notu`}>
              <ul className="m-0 pl-5">{d.dikkat.map((x) => <li key={x}>{x}</li>)}</ul>
            </K.Callout>
          )}

          <div className="kp-grid kp-g-2">
            <section>
              <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>Hisse ağırlıkları</h3>
              <Bars rows={Object.entries(d.agirlik_yuzde).map(([k, v]) => [k, v])} />
            </section>
            <section>
              <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>Sektör dağılımı</h3>
              <Bars rows={Object.entries(d.sektor_yuzde).map(([k, v]) => [k, v])} />
            </section>
          </div>

          <section>
            <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>Tema dağılımı</h3>
            {Object.keys(d.tema || {}).length
              ? <Bars rows={Object.entries(d.tema).map(([k, v]) => [k, v.agirlik_yuzde, v.hisseler.join(", ")])} />
              : <p className="kp-note m-0">Tanımlı temalarda hisse yok.</p>}
            <p className="kp-note">Bir hisse birden çok temada olabilir, toplam %100'ü geçer. Temalar elle tanımlı listelerdir:
              mega teknoloji, yarı iletken, yapay zekâ, yapay zekâ enerjisi, banka/finans, savunmacı.</p>
          </section>

          {d.korelasyon?.en_bagli?.length > 0 && (
            <section>
              <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>Birlikte hareket</h3>
              <K.DataTable rows={[...d.korelasyon.en_bagli.map((x) => ({ ...x, tur: "en bağlı" })), ...(d.korelasyon.en_bagimsiz || []).map((x) => ({ ...x, tur: "en bağımsız" }))]
                .map((x, i) => ({ ...x, _k: i }))} rowKey="_k" columns={[
                { key: "cift", label: "Çift", render: (x) => <b>{x.cift}</b> },
                { key: "korelasyon", label: "Korelasyon", num: true, render: (x) => U.fmtNum(x.korelasyon, 2) },
                { key: "tur", label: "" },
              ]} />
            </section>
          )}

          <section>
            <h3 className="kp-card__title" style={{ margin: "0 0 0.75rem" }}>Senaryolar</h3>
            <K.DataTable rows={(d.senaryolar || []).map((x, i) => ({ ...x, _k: i }))} rowKey="_k" columns={[
              { key: "senaryo", label: "Senaryo", render: (x) => <span><b>{x.senaryo}</b><br /><span className="text-xs text-t-3">{RULER}</span></span> },
              { key: "portfoy_yuzde", label: "Portföy", num: true, strong: true, render: (x) => <span className={x.portfoy_yuzde < 0 ? "kp-num-down" : "kp-num-up"}>{signed(x.portfoy_yuzde)}</span> },
              { key: "tutar_usd", label: "Tutar", num: true, render: (x) => `${x.tutar_usd < 0 ? "−" : "+"}$${U.fmtNum(Math.abs(x.tutar_usd), 0)}` },
              { key: "en", label: "En çok etkilenen", mobile: false, render: (x) => (x.en_cok_etkilenen || []).map(([m, t]) => `${t} ${signed(m)}`).join(" · ") || "—" },
            ]} />
            <p className="kp-note">Tek etkenli hesap: son bir yılın günlük birlikte hareketinden. Şu an VIX {U.fmtNum(d.vix, 1)}, 10 yıllık faiz %{U.fmtNum(d.tnx, 2)}.
              Gerçek bir satışta etkenler birlikte hareket eder ve duyarlılıklar değişir; satırlar toplanmaz.</p>
          </section>

          {d.kaynaklar?.length > 0 && (
            <p className="kp-note m-0">Kaynaklar: {d.kaynaklar.map((x) => `${x.veri}: ${x.kaynak} (${x.tarih})`).join(" · ")}
              {d.kapsam_yuzde < 99.9 ? ` · beta ve senaryolar portföyün %${U.fmtNum(d.kapsam_yuzde, 0)}'ini kapsar` : ""}</p>
          )}
        </div>
      )}
    </K.Card>
  );
}
