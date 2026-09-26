import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { chartHref } from "@/components/AssetLogo";
import { marketRows, curOf, logo, MARKET_UI, priceFmt } from "@/lib/dsmap";
import { formatTime } from "@/lib/format";
import { baseCode } from "@/lib/portfolio";
import { sendAction } from "@/lib/actions";
import { cn } from "@/lib/utils";

const TARGET_NAMES = { BIST: "BIST", KRIPTO: "Kripto", ABD: "ABD", NAKIT: "Nakit" };
const TARGET_COLORS = { BIST: "var(--cat-1)", KRIPTO: "var(--cat-2)", ABD: "var(--cat-3)", NAKIT: "var(--cat-5)" };

// Bugünkü varlıklar ve kıyaslar: aynı ilk güne göre yüzde değişim
function HistoryCard({ rows }) {
  const [period, setPeriod] = useState("90 gün");
  const latest = rows?.[rows.length - 1]?.tarih;
  const start = latest && new Date(`${latest}T12:00:00Z`);
  if (start) start.setUTCDate(start.getUTCDate() - (period === "30 gün" ? 30 : 90));
  const r = (rows || []).filter((x) => x.toplam_tl && (!start || x.tarih >= start.toISOString().slice(0, 10)));
  if (r.length < 5) return null;
  const base = r[0].toplam_tl;
  const idx = r[0].xu100;
  const gold = r[0].gram_altin;
  const mine = r.map((x) => (x.toplam_tl / base - 1) * 100);
  const bist = idx && r.every((x) => x.xu100) ? r.map((x) => (x.xu100 / idx - 1) * 100) : null;
  const altin = gold && r.every((x) => x.gram_altin) ? r.map((x) => (x.gram_altin / gold - 1) * 100) : null;
  const months = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];
  // İlk gün, ay başları ve son gün; birbirine çok yakın etiketler atlanır (üst üste binmesin)
  const gap = Math.max(4, Math.round(r.length / 10));
  let lastAt = -gap;
  const labels = r.map((x, i) => {
    const want = i === 0 || x.tarih.slice(8) === "01" || i === r.length - 1;
    if (!want || i - lastAt < gap || (i !== r.length - 1 && r.length - 1 - i < gap)) return "";
    lastAt = i;
    return `${+x.tarih.slice(8)} ${months[+x.tarih.slice(5, 7) - 1]}`;
  });
  const last = r[r.length - 1];
  return (
    <K.Card title="Portföy geçmişi" actions={<K.Segmented ariaLabel="Dönem" value={period} onChange={setPeriod} options={["30 gün", "90 gün"]} />}>
      <K.LineChart height={240} labels={labels} series={[
        { label: "Portföyüm (₺)", color: "var(--text)", values: mine },
        ...(bist ? [{ label: "BIST 100", color: "var(--cat-1)", values: bist, dashed: true }] : []),
        ...(altin ? [{ label: "Gram altın", color: "var(--cat-5)", values: altin, dashed: true }] : []),
      ]} />
      <p className="kp-note">
        Bugünkü varlıklarının her gün ne ettiği (kripto ve ABD o günün kuruyla ₺). Alış tarihleri bilinmediği için bu bir
        “eldekiler” görünümüdür. Bugün ₺{U.fmtNum(last.toplam_tl, 0)} · 1 $ = ₺{U.fmtNum(last.usdtry, 2)}.
      </p>
    </K.Card>
  );
}

function TargetCard({ dagilim, hedef }) {
  const [edit, setEdit] = useState(false);
  const [form, setForm] = useState(() => ({ BIST: 50, KRIPTO: 20, ABD: 20, NAKIT: 10, tolerans: 5, ...(hedef || {}) }));
  if (!dagilim) return null;
  const save = async () => {
    const payload = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, U.parseTr(String(v)) || 0]));
    if (await sendAction("target.set", payload, "Hedef dağılım kaydediliyor.")) setEdit(false);
  };
  return (
    <K.Card title="Hedef dağılım" actions={<K.Button variant="ghost" onClick={() => setEdit(!edit)}>{edit ? "Vazgeç" : dagilim.hedef_var ? "Değiştir" : "Hedef koy"}</K.Button>}>
      <div className="kp-col">
        {dagilim.satirlar.map((r) => {
          const over = r.sapma != null && Math.abs(r.sapma) > dagilim.tolerans;
          return (
            <div key={r.piyasa}>
              <div className="flex items-center justify-between gap-3 text-[0.9375rem]">
                <span className="flex items-center gap-2 font-semibold text-t-1"><i style={{ width: 10, height: 10, borderRadius: 3, background: TARGET_COLORS[r.piyasa] }} />{TARGET_NAMES[r.piyasa]}</span>
                <span className="num text-t-2">
                  <b className="text-t-1">%{U.fmtNum(r.gercek, 1)}</b>
                  {r.hedef != null && <> · hedef %{U.fmtNum(r.hedef, 0)} · <b className={cn(over ? "text-wait" : "text-t-2")}>{r.sapma > 0 ? "+" : r.sapma < 0 ? "\u2212" : ""}{U.fmtNum(Math.abs(r.sapma), 1)} puan</b></>}
                </span>
              </div>
              <div className="relative mt-1.5 h-2 rounded-full bg-hairline">
                <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(100, r.gercek)}%`, background: TARGET_COLORS[r.piyasa] }} />
                {r.hedef != null && <span className="absolute -top-1 h-4 w-0.5 bg-t-1" style={{ left: `${Math.min(100, r.hedef)}%` }} title="hedef" />}
              </div>
            </div>
          );
        })}
      </div>
      {edit ? (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[...Object.keys(TARGET_NAMES), "tolerans"].map((k) => (
            <K.Field key={k} label={k === "tolerans" ? "Tolerans (puan)" : `${TARGET_NAMES[k]} %`}>
              <K.TextInput inputMode="decimal" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
            </K.Field>
          ))}
          <div className="col-span-2 flex items-end sm:col-span-5"><K.Button variant="primary" onClick={save}>Kaydet</K.Button></div>
        </div>
      ) : (
        <p className="kp-note">
          {dagilim.hedef_var
            ? dagilim.asanlar.length ? `Tolerans (±${U.fmtNum(dagilim.tolerans, 0)} puan) dışında: ${dagilim.asanlar.map((r) => TARGET_NAMES[r.piyasa]).join(", ")}. Her akşam 19:15'te Telegram'dan hatırlatırım.` : `Hepsi tolerans (±${U.fmtNum(dagilim.tolerans, 0)} puan) içinde.`
            : "Hedef koyarsan sapma olduğunda haber veririm. "}
          Nakit: /bakiye nakit ile girilen tutarlar. Bu bir öneri değil, yalnız sapma hatırlatması.
        </p>
      )}
    </K.Card>
  );
}

const QTY = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 8 });

export default function Portfolio() {
  const navigate = useNavigate();
  const q = useData("extras", "/extras", LIVE);
  const [tab, setTab] = useState("Tümü");
  return (
    <DataView query={q} loadingText="Portföy verisi yükleniyor...">
      {(d) => {
        if (!d.guncelleme) return <EmptyState text="Bot henüz portföy verisini göndermedi (15 dakikada bir gönderir)." />;
        const all = (d.portfoy || []).map((g) => {
          const cur = curOf(g.para);
          const code = baseCode(g.ad);
          return {
            id: g.piyasa + code, code, market: g.piyasa, marketLabel: MARKET_UI[g.piyasa]?.label || g.piyasa, cur,
            qty: g.adet, cost: g.adet ? g.maliyet / g.adet : 0, price: g.fiyat, value: g.deger, costv: g.maliyet,
            day: g.gun_yuzde, total: g.toplam_yuzde, pl: g.deger - g.maliyet,
          };
        });
        if (!all.length) return <EmptyState text="Portföy boş. Telegram'da ekle: /portfoy ya da düz yazıyla “astordan 4 tane 260 TL'den aldım”." />;
        const markets = marketRows(d.portfoy);
        const usd = d.usdtry;
        const tl = (m) => (m.cur === "TRY" ? m.value : usd ? m.value * usd : null);
        const totalTl = usd ? markets.reduce((a, m) => a + tl(m), 0) : null;
        const filters = ["Tümü", ...markets.map((m) => m.label)];
        const rows = all.filter((r) => tab === "Tümü" || r.marketLabel === tab);
        const cols = [
          { key: "code", label: "Kod", render: (r) => <K.Ticker symbol={r.code} name={r.marketLabel} logo={logo(r.code, r.market)} /> },
          { key: "qty", label: "Adet", num: true, render: (r) => QTY.format(r.qty) },
          { key: "cost", label: "Ort. maliyet", num: true, render: (r) => priceFmt(r.cost, r.cur) },
          { key: "price", label: "Fiyat", num: true, strong: true, render: (r) => priceFmt(r.price, r.cur) },
          { key: "value", label: "Değer", num: true, strong: true, mobile: false, render: (r) => U.fmtPrice(r.value, r.cur, 2) },
          { key: "day", label: "Gün", num: true, render: (r) => (r.day == null ? "—" : <K.ChangeBadge value={r.day} />) },
          { key: "total", label: "Toplam", num: true, render: (r) => <K.ChangeBadge value={r.total} /> },
          { key: "pl", label: "K/Z", num: true, render: (r) => <span className={r.pl >= 0 ? "kp-num-up" : "kp-num-down"}>{U.fmtSignedMoney(r.pl, r.cur)}</span> },
        ];
        const warnings = d.yogunlasma?.uyarilar || [];
        const kiyas = d.kiyas?.kiyas || [];
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title="Portföy"
              subtitle={totalTl != null ? `Toplam ${U.fmtPrice(totalTl, "TRY", 2)} · 1 $ = ₺${U.fmtNum(usd, 2)} · güncelleme ${formatTime(d.guncelleme)}` : `Güncelleme ${formatTime(d.guncelleme)}`} />
            <div className="kp-grid kp-g-3">{markets.map((m) => <K.MarketCard key={m.key} {...m} />)}</div>
            {warnings.length > 0 && <K.Callout tone="warn" title="Yoğunlaşma uyarısı">{warnings.join(" ")}</K.Callout>}
            <K.Card title="Varlıklar" actions={<K.Segmented ariaLabel="Piyasa" value={tab} onChange={setTab} options={filters} />}>
              <K.DataTable columns={cols} rows={rows} onRowClick={(r) => navigate(chartHref(r.code, r.market))}
                mobileEnd={(r) => U.fmtPrice(r.value, r.cur, 2)} />
              <p className="kp-note">Satıra dokun: o kodun grafiği açılır. Toplam % alış maliyetine göre; rakamları bot kodla hesaplar.</p>
            </K.Card>
            <HistoryCard rows={d.geriye?.satirlar} />
            <TargetCard dagilim={d.dagilim} hedef={d.hedef} />
            <div className="kp-grid kp-split-l">
              <K.Card title="Dağılım">
                {totalTl != null ? (
                  <K.Donut center={{ label: "Toplam", value: `${U.fmtPrice(totalTl / 1000, "TRY", 1)} bin` }}
                    items={markets.map((m) => ({ label: m.label, value: tl(m), color: m.color,
                      sub: U.fmtPrice(tl(m), "TRY", 0) + (m.cur === "USD" ? ` · ${U.fmtPrice(m.value, "USD", 0)}` : "") }))} />
                ) : <p className="kp-note">Dolar kuru gelince ₺ karşılıklı dağılım gösterilir.</p>}
              </K.Card>
              <div className="kp-col">
                <h2 className="kp-card__title">Kıyas · aynı tarihlerde, ₺ bazında</h2>
                {kiyas.length ? (
                  <div className="kp-grid kp-g-2">
                    {kiyas.map((b) => <K.CompareCard key={b.ad} label={b.ad} value={b.yuzde ?? 0} mine={d.kiyas.portfoy_yuzde ?? 0} note={b.not || undefined} />)}
                  </div>
                ) : <p className="kp-note">Kıyas için alış tarihi girilmiş pozisyon gerekli. Telegram: /duzelt ID tarih=2025-03-01</p>}
                {kiyas.length > 0 && <p className="kp-note">Senin getirin ₺ bazında {d.kiyas.portfoy_yuzde >= 0 ? "+" : "−"}%{U.fmtNum(Math.abs(d.kiyas.portfoy_yuzde), 1)}; her pozisyon kendi alış tarihinden kıyaslanır.</p>}
              </div>
            </div>
          </div>
        );
      }}
    </DataView>
  );
}
