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
import { toast } from "sonner";
import { useLang } from "@/lib/i18n";

const TARGET_NAMES = { BIST: "BIST", KRIPTO: "Kripto", ABD: "ABD", NAKIT: "Nakit" };
const TARGET_COLORS = { BIST: "var(--cat-1)", KRIPTO: "var(--cat-2)", ABD: "var(--cat-3)", NAKIT: "var(--cat-5)" };

// Bugünkü varlıklar ve kıyaslar: aynı ilk güne göre yüzde değişim
function HistoryCard({ rows, real }) {
  const { t, monthName } = useLang();
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
  const months = Array.from({ length: 12 }, (_, i) => monthName(i).slice(0, 3));
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
    <K.Card title={t("Portföy geçmişi")} actions={<K.Segmented ariaLabel={t("Dönem")} value={period} onChange={setPeriod} options={[30, 90].map((n) => ({ value: `${n} gün`, label: t("{n} gün", { n }) }))} />}>
      <K.LineChart height={240} labels={labels} series={[
        { label: t("Portföyüm (₺)"), color: "var(--text)", values: mine },
        ...(bist ? [{ label: "BIST 100", color: "var(--cat-1)", values: bist, dashed: true }] : []),
        ...(altin ? [{ label: t("Gram altın"), color: "var(--cat-5)", values: altin, dashed: true }] : []),
      ]} />
      <p className="kp-note">
        {t("Bugünkü varlıklarının her gün ne ettiği (kripto ve ABD o günün kuruyla ₺). Alış tarihleri bilinmediği için bu bir “eldekiler” görünümüdür. Bugün ₺{a} · 1 $ = ₺{b}.", { a: U.fmtNum(last.toplam_tl, 0), b: U.fmtNum(last.usdtry, 2) })}
        {real?.length ? ` ${t("Gerçek günlük kayıt: {n} gün (ilki {d}); her gün portföyün o günkü değeri saklanıyor.", { n: real.length, d: relDayShort(real[0].tarih) })}` : ""}
      </p>
    </K.Card>
  );
}

const relDayShort = (iso) => `${+iso.slice(8, 10)}.${iso.slice(5, 7)}`;


// Temettü gelir planı: geçen 12 ayın ödemeleri x bugünkü adet (brüt tahmin), ay ay
// Birikim planları (DCA): aylık hatırlatma, "Aldım" ile kayıt. Telegram: /birikim
function DcaCard({ plans }) {
  const { t } = useLang();
  const [f, setF] = useState({ kod: "", tutar: "", gun: "1" });
  const add = async () => {
    const kod = f.kod.trim().toUpperCase();
    const tutar = U.parseTr(f.tutar);
    const gun = parseInt(f.gun, 10);
    if (!kod || !(tutar > 0) || !(gun >= 1 && gun <= 28)) {
      toast.error(t("Kod, aylık tutar ve 1–28 arası gün gir."));
      return;
    }
    if (await sendAction("dca.add", { kod, tutar, gun }, t("{k} birikim planı kuruluyor.", { k: kod }))) setF({ kod: "", tutar: "", gun: f.gun });
  };
  return (
    <K.Card title={`${t("Birikim planları")} (${plans?.length || 0})`}>
      {plans?.length > 0 && (
        <K.DataTable rows={plans} rowKey="id" columns={[
          { key: "varlik", label: t("Varlık"), render: (p) => <K.Ticker symbol={p.varlik} name={t(MARKET_UI[p.piyasa]?.label || p.piyasa)} logo={logo(p.varlik, p.piyasa)} /> },
          { key: "tutar", label: t("Aylık"), num: true, render: (p) => U.fmtPrice(p.tutar, curOf(p.para), 0) },
          { key: "gun", label: t("Gün"), num: true, mobile: false, render: (p) => t("her ayın {n}'i", { n: p.gun }) },
          { key: "alim", label: t("Alım"), num: true, render: (p) => String(p.alim || 0) },
          { key: "ortalama", label: t("Ort. maliyet"), num: true, strong: true, render: (p) => (p.ortalama ? priceFmt(p.ortalama, curOf(p.para)) : "—") },
          { key: "maliyet", label: t("Toplam"), num: true, mobile: false, render: (p) => U.fmtPrice(p.maliyet || 0, curOf(p.para), 0) },
          { key: "sil", label: "", render: (p) => <K.Button variant="ghost" onClick={() => sendAction("dca.delete", { id: p.id }, t("{k} planı siliniyor.", { k: p.varlik }))}>{t("Sil")}</K.Button> },
        ]} />
      )}
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <K.Field label={t("Kod")}><K.TextInput value={f.kod} placeholder="BTC, NVDA, THYAO" onChange={(e) => setF({ ...f, kod: e.target.value })} /></K.Field>
        <K.Field label={t("Aylık tutar")} hint={t("kripto/ABD: USD · BIST: TL")}><K.TextInput inputMode="decimal" value={f.tutar} placeholder="50" onChange={(e) => setF({ ...f, tutar: e.target.value })} /></K.Field>
        <K.Field label={t("Ayın günü (1–28)")}><K.TextInput inputMode="numeric" value={f.gun} onChange={(e) => setF({ ...f, gun: e.target.value })} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={add}>{t("Plan kur")}</K.Button></div>
      </div>
      <p className="kp-note">{t("Hatırlatma her ayın seçtiğin gününde gelir; fiyat ortalamanın belirgin altındaysa ekstra kademe önerilir. Plan silinince alınan pozisyonlar portföyde kalır.")}</p>
    </K.Card>
  );
}

function DividendCard({ plan }) {
  const { t, monthName } = useLang();
  if (!plan?.satirlar?.length) return null;
  const tl = plan.toplam?.TL || {};
  const usd = plan.toplam?.USD || {};
  const cal = plan.takvim || [];
  const max = Math.max(1, ...cal.map((c) => c.TL));
  const payers = plan.satirlar.filter((r) => !r.hata && r.son12 > 0).sort((a, b) => b.son12 - a.son12);
  const none = plan.satirlar.filter((r) => !r.hata && !r.son12).map((r) => r.kod);
  return (
    <K.Card title={t("Temettü gelir planı")} actions={<K.Button variant="ghost" onClick={() => sendAction("dividend.refresh", {}, t("Temettü planı yenileniyor."))}>{t("Yenile")}</K.Button>}>
      <div className="kp-grid kp-g-3">
        <K.StatCard label={t("Yıllık tahmini (₺, brüt)")} value={U.fmtPrice(tl.son12 || 0, "TRY", 2)}
          sub={tl.degisim != null ? t("önceki 12 aya göre {x}", { x: `${tl.degisim >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(tl.degisim), 1)}` }) : t("önceki yıl verisi yok")} />
        <K.StatCard label={t("Temettü verimi (BIST)")} value={tl.verim != null ? `%${U.fmtNum(tl.verim, 2)}` : "—"} sub={`${t("hisselerin değeri")} ${U.fmtPrice(tl.deger || 0, "TRY", 0)}`} />
        <K.StatCard label={t("ABD (USD, brüt)")} value={usd.son12 ? U.fmtPrice(usd.son12, "USD", 2) : "—"} sub={usd.verim != null ? `${t("verim")} %${U.fmtNum(usd.verim, 2)}` : t("ABD hissesi ya da temettü yok")} />
      </div>
      <div className="mt-5 flex h-32 items-end gap-1.5" aria-label={t("Ay ay tahmini temettü")}>
        {cal.map((c) => {
          const v = c.TL;
          const [y, m] = c.ay.split("-");
          return (
            <div key={c.ay} className="flex flex-1 flex-col items-center gap-1" title={`${monthName(+m - 1).slice(0, 3)} ${y}: ${c.TL ? U.fmtPrice(c.TL, "TRY", 2) : ""}${c.USD ? ` ${U.fmtPrice(c.USD, "USD", 2)}` : ""}`}>
              <span className="num text-[0.6875rem] text-t-3">{c.TL ? U.fmtNum(c.TL, 0) : ""}</span>
              <span className="w-full rounded-t bg-up/70" style={{ height: `${Math.max(v ? 4 : 1, (v / max) * 88)}px`, opacity: v ? 1 : 0.25 }} />
              <span className="text-[0.6875rem] text-t-3">{monthName(+m - 1).slice(0, 3)}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {payers.map((r) => (
          <span key={r.kod} className="rounded-lg border border-hairline px-3 py-1 text-[0.9375rem] text-t-2">
            <b className="text-t-1">{r.kod}</b> {U.fmtPrice(r.son12, r.para === "TL" ? "TRY" : "USD", 2)}/{t("yıl")}{r.verim != null ? ` · %${U.fmtNum(r.verim, 2)}` : ""}
          </span>
        ))}
      </div>
      <p className="kp-note">
        {t(plan.not)}{none.length ? ` ${t("Son 12 ayda temettü yok: {k}.", { k: none.join(", ") })}` : ""} Telegram: /temettu gelir
      </p>
    </K.Card>
  );
}

function TargetCard({ dagilim, hedef }) {
  const { t } = useLang();
  const [edit, setEdit] = useState(false);
  const [form, setForm] = useState(() => ({ BIST: 50, KRIPTO: 20, ABD: 20, NAKIT: 10, tolerans: 5, ...(hedef || {}) }));
  if (!dagilim) return null;
  const save = async () => {
    const payload = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, U.parseTr(String(v)) || 0]));
    if (await sendAction("target.set", payload, t("Hedef dağılım kaydediliyor."))) setEdit(false);
  };
  return (
    <K.Card title={t("Hedef dağılım")} actions={<K.Button variant="ghost" onClick={() => setEdit(!edit)}>{edit ? t("Vazgeç") : dagilim.hedef_var ? t("Değiştir") : t("Hedef koy")}</K.Button>}>
      <div className="kp-col">
        {dagilim.satirlar.map((r) => {
          const over = r.sapma != null && Math.abs(r.sapma) > dagilim.tolerans;
          return (
            <div key={r.piyasa}>
              <div className="flex items-center justify-between gap-3 text-[0.9375rem]">
                <span className="flex items-center gap-2 font-semibold text-t-1"><i style={{ width: 10, height: 10, borderRadius: 3, background: TARGET_COLORS[r.piyasa] }} />{t(TARGET_NAMES[r.piyasa])}</span>
                <span className="num text-t-2">
                  <b className="text-t-1">%{U.fmtNum(r.gercek, 1)}</b>
                  {r.hedef != null && <> · {t("hedef")} %{U.fmtNum(r.hedef, 0)} · <b className={cn(over ? "text-wait" : "text-t-2")}>{r.sapma > 0 ? "+" : r.sapma < 0 ? "\u2212" : ""}{U.fmtNum(Math.abs(r.sapma), 1)}{t(" puan")}</b></>}
                </span>
              </div>
              <div className="relative mt-1.5 h-2 rounded-full bg-hairline">
                <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.min(100, r.gercek)}%`, background: TARGET_COLORS[r.piyasa] }} />
                {r.hedef != null && <span className="absolute -top-1 h-4 w-0.5 bg-t-1" style={{ left: `${Math.min(100, r.hedef)}%` }} title={t("hedef")} />}
              </div>
            </div>
          );
        })}
      </div>
      {edit ? (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-5">
          {[...Object.keys(TARGET_NAMES), "tolerans"].map((k) => (
            <K.Field key={k} label={k === "tolerans" ? t("Tolerans (puan)") : `${t(TARGET_NAMES[k])} %`}>
              <K.TextInput inputMode="decimal" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
            </K.Field>
          ))}
          <div className="col-span-2 flex items-end sm:col-span-5"><K.Button variant="primary" onClick={save}>{t("Kaydet")}</K.Button></div>
        </div>
      ) : (
        <p className="kp-note">
          {dagilim.hedef_var
            ? dagilim.asanlar.length ? t("Tolerans (±{n} puan) dışında: {m}. Her akşam 19:15'te Telegram'dan hatırlatırım.", { n: U.fmtNum(dagilim.tolerans, 0), m: dagilim.asanlar.map((r) => t(TARGET_NAMES[r.piyasa])).join(", ") }) : t("Hepsi tolerans (±{n} puan) içinde.", { n: U.fmtNum(dagilim.tolerans, 0) })
            : t("Hedef koyarsan sapma olduğunda haber veririm.")}
          {" "}{t("Nakit: bu sayfadaki “Nakit” kartına girilen tutarlar. Bu bir öneri değil, yalnız sapma hatırlatması.")}
        </p>
      )}
    </K.Card>
  );
}

const QTY = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 8 });
// Form alanı için: binlik ayırıcı yok, ondalık virgül (parseTr "1.234"ü 1234 okur)
const PLAIN = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 10, useGrouping: false });
const MARKET_OPTIONS = [
  { value: "", label: "Otomatik bul" }, { value: "KRIPTO", label: "Kripto (USDT)" },
  { value: "ABD", label: "ABD (USD)" }, { value: "BIST", label: "BIST (TL)" },
];

// Telegram'daki /portfoy ekle ile aynı kayıt: bot kodu doğrular, stop/hedefi bölgelerden önerir
function AddCard() {
  const { t } = useLang();
  const [f, setF] = useState({ piyasa: "", kod: "", adet: "", maliyet: "" });
  const unit = f.piyasa === "BIST" ? "₺" : f.piyasa ? "$" : undefined;
  const add = async () => {
    const kod = f.kod.trim().toUpperCase();
    const adet = U.parseTr(f.adet);
    const maliyet = U.parseTr(f.maliyet);
    if (!kod || !(adet > 0) || !(maliyet > 0)) {
      toast.error(t("Kod, adet ve alış fiyatı gir."));
      return;
    }
    if (await sendAction("holding.add", { kod, piyasa: f.piyasa, adet, maliyet }, t("{k} portföye ekleniyor.", { k: kod }))) {
      setF({ ...f, kod: "", adet: "", maliyet: "" });
    }
  };
  return (
    <K.Card title={t("Varlık ekle")}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <K.Field label={t("Piyasa")}>
          <K.Select value={f.piyasa} onChange={(e) => setF({ ...f, piyasa: e.target.value })} options={MARKET_OPTIONS.map((o) => ({ ...o, label: t(o.label) }))} />
        </K.Field>
        <K.Field label={t("Kod")}><K.TextInput value={f.kod} placeholder="BTC, NVDA, THYAO" onChange={(e) => setF({ ...f, kod: e.target.value })} /></K.Field>
        <K.Field label={t("Adet")}><K.TextInput inputMode="decimal" value={f.adet} placeholder="0,05" onChange={(e) => setF({ ...f, adet: e.target.value })} /></K.Field>
        <K.Field label={t("Alış fiyatı (birim)")}><K.TextInput prefix={unit} inputMode="decimal" value={f.maliyet} placeholder="0,00" onChange={(e) => setF({ ...f, maliyet: e.target.value })} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={add}>{t("Ekle")}</K.Button></div>
      </div>
      <p className="kp-note">{t("Bot kodu doğrular ve birkaç saniye içinde ekler; sonuç Telegram'a da gelir. Altın/döviz için piyasayı “Otomatik bul”da bırak.")}</p>
    </K.Card>
  );
}

// Portföyü siteden baştan kur: her satır "KOD ADET MALİYET"; istenirse önce mevcut açık kayıtlar silinir
function BulkCard({ count }) {
  const { t } = useLang();
  const [text, setText] = useState("");
  const [piyasa, setPiyasa] = useState("");
  const [wipe, setWipe] = useState(false);
  const [sure, setSure] = useState(false);
  const parse = () => {
    const rows = [];
    for (const [i, line] of text.split("\n").map((s) => s.trim()).entries()) {
      if (!line) continue;
      const [kod, a, m, ...rest] = line.split(/[\s;]+/);
      const adet = U.parseTr(a);
      const maliyet = U.parseTr(m);
      if (rest.length || !kod || !(adet > 0) || !(maliyet > 0)) {
        toast.error(t("{n}. satır okunamadı: “{l}”. Biçim: KOD ADET MALİYET", { n: i + 1, l: line }));
        return null;
      }
      rows.push({ kod: kod.toUpperCase(), piyasa, adet, maliyet });
    }
    return rows;
  };
  const send = async () => {
    const rows = parse();
    if (!rows) return;
    if (!rows.length) {
      toast.error(t("En az bir satır yaz."));
      return;
    }
    if (wipe && !sure) {
      setSure(true);
      return;
    }
    const ok = await sendAction("holding.bulk", { satirlar: rows, temizle: wipe },
      wipe ? t("Portföy siliniyor, {n} varlık giriliyor.", { n: rows.length }) : t("{n} varlık ekleniyor.", { n: rows.length }));
    if (ok) {
      setText("");
      setSure(false);
      setWipe(false);
    }
  };
  const clear = async () => {
    if (!sure) {
      setSure(true);
      return;
    }
    if (await sendAction("holding.bulk", { satirlar: [], temizle: true }, t("Portföy siliniyor."))) setSure(false);
  };
  return (
    <K.Card title={t("Portföyü baştan gir")}>
      <div className="kp-col">
        <K.Field label={t("Her satıra bir varlık: KOD ADET MALİYET")} hint={t("Ondalık virgül ya da nokta: 0,05 · 84000 · 1.234,50")}>
          <textarea rows={6} value={text} onChange={(e) => { setText(e.target.value); setSure(false); }}
            placeholder={"BTC 0,05 84000\nNVDA 3 120\nTHYAO 10 300"}
            className="num w-full rounded-[10px] border border-strong bg-ink px-3.5 py-2.5 text-t-1 outline-none focus:border-info" />
        </K.Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <K.Field label={t("Piyasa (bütün satırlar için)")}>
            <K.Select value={piyasa} onChange={(e) => setPiyasa(e.target.value)} options={MARKET_OPTIONS.map((o) => ({ ...o, label: t(o.label) }))} />
          </K.Field>
          <label className="flex items-center gap-2 self-end text-[0.9375rem] text-t-2">
            <input type="checkbox" checked={wipe} onChange={(e) => { setWipe(e.target.checked); setSure(false); }} />
            {t("Önce mevcut portföyü sil ({n} varlık)", { n: count })}
          </label>
        </div>
        <div className="flex flex-wrap gap-3">
          <K.Button variant={wipe ? "danger" : "primary"} onClick={send}>
            {wipe ? (sure ? t("Emin misin? Sil ve gir") : t("Sil ve yenisini gir")) : t("Hepsini ekle")}
          </K.Button>
          {count > 0 && !text.trim() && <K.Button variant="danger" onClick={clear}>{sure ? t("Emin misin? Hepsini sil") : t("Portföyü tamamen sil")}</K.Button>}
          {sure && <K.Button variant="ghost" onClick={() => setSure(false)}>{t("Vazgeç")}</K.Button>}
        </div>
      </div>
      <p className="kp-note">{t("Silmek satış sayılmaz: açık kayıtlar kaldırılır, kapanan işlemler ve raporlar durur. Bot silmeden önce yedek alır. Karışık piyasada “Otomatik bul” kodu kendi tanır.")}</p>
    </K.Card>
  );
}

// Bir varlığın alım kayıtları: adet, maliyet, alış tarihi, stop/hedef düzeltilir ya da kayıt silinir
function LotRow({ lot, code, cur, onDelete }) {
  const { t } = useLang();
  const init = { adet: PLAIN.format(lot.adet), giris: PLAIN.format(lot.giris), tarih: lot.tarih_yok ? "" : String(lot.acilis || "").slice(0, 10),
    stop: lot.stop == null ? "" : PLAIN.format(lot.stop), hedef: lot.hedef == null ? "" : PLAIN.format(lot.hedef) };
  const [f, setF] = useState(init);
  const unit = cur === "TRY" ? "₺" : "$";
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const save = () => {
    const a = U.parseTr(f.adet);
    const m = U.parseTr(f.giris);
    if (!(a > 0) || !(m > 0)) {
      toast.error(t("Adet ve maliyet pozitif olmalı."));
      return;
    }
    const payload = { id: lot.id, adet: a, maliyet: m };
    for (const k of ["stop", "hedef"]) {
      if (f[k] === init[k] || !f[k].trim()) continue; // yalnız değişen seviye gönderilir
      const v = U.parseTr(f[k]);
      if (!(v > 0)) {
        toast.error(t("Stop ve hedef pozitif sayı olmalı."));
        return;
      }
      payload[k] = v;
    }
    if (f.tarih && f.tarih !== init.tarih) payload.tarih = f.tarih;
    sendAction("holding.edit", payload, t("{k} #{n} düzeltmesi iletildi.", { k: code, n: lot.id }));
  };
  return (
    <div className="kp-col border-b border-hairline pb-4 last:border-0 last:pb-0">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <K.Field label={`#${lot.id} · ${t("adet")}`}><K.TextInput inputMode="decimal" value={f.adet} onChange={set("adet")} /></K.Field>
        <K.Field label={t("Ort. maliyet")}><K.TextInput prefix={unit} inputMode="decimal" value={f.giris} onChange={set("giris")} /></K.Field>
        <K.Field label={t("Alış tarihi")} hint={lot.tarih_yok ? t("bilinmiyor: girersen kıyas hesaplanır") : undefined}>
          <K.TextInput type="date" value={f.tarih} max={new Date().toISOString().slice(0, 10)} onChange={set("tarih")} />
        </K.Field>
        <K.Field label="Stop" hint={t("yalnız yukarı çekilir")}><K.TextInput prefix={unit} inputMode="decimal" value={f.stop} placeholder="—" onChange={set("stop")} /></K.Field>
        <K.Field label={t("Hedef")}><K.TextInput prefix={unit} inputMode="decimal" value={f.hedef} placeholder="—" onChange={set("hedef")} /></K.Field>
      </div>
      <div className="flex flex-wrap gap-3">
        <K.Button variant="primary" onClick={save}>{t("Kaydet")}</K.Button>
        <K.Button variant="danger" onClick={() => onDelete([lot])}>{t("Sil")}</K.Button>
      </div>
    </div>
  );
}

// Piyasa başına nakit: bakiye, dağılım ve portföy alarmları bunu kullanır (alım satımda kendiliğinden değişmez)
const CASH = [["BIST", "BIST nakdi", "₺"], ["KRIPTO", "Kripto nakdi", "$"], ["ABD", "ABD nakdi", "$"]];
function CashCard({ cash }) {
  const { t } = useLang();
  const [f, setF] = useState(() => Object.fromEntries(CASH.map(([m]) => [m, PLAIN.format(cash?.[m] || 0)])));
  const save = async () => {
    for (const [m, label] of CASH) {
      const v = U.parseTr(f[m]);
      if (!(v >= 0)) {
        toast.error(`${t(label)}: ${t("sıfır ya da pozitif bir sayı yaz.")}`);
        return;
      }
      if (v !== (cash?.[m] || 0)) await sendAction("cash.set", { piyasa: m, tutar: v }, t("{k} kaydediliyor.", { k: t(label) }));
    }
  };
  return (
    <K.Card title={t("Nakit")}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {CASH.map(([m, label, unit]) => (
          <K.Field key={m} label={t(label)}><K.TextInput prefix={unit} inputMode="decimal" value={f[m]} onChange={(e) => setF({ ...f, [m]: e.target.value })} /></K.Field>
        ))}
        <div className="flex items-end"><K.Button variant="primary" onClick={save}>{t("Kaydet")}</K.Button></div>
      </div>
      <p className="kp-note">{t("Bot aracı kurum hesabını görmez: nakdi sen girersin, alım satımda kendiliğinden değişmez. Kripto nakdi USDT sayılır.")}</p>
    </K.Card>
  );
}

// Portföy alarmı: bir piyasanın bakiyesi (varlık + nakit) şimdiye göre % değişirse ya da bir seviyeyi geçerse, bir kez
function PfAlarmCard({ alarms }) {
  const { t } = useLang();
  const [f, setF] = useState({ piyasa: "KRIPTO", tur: "yuzde", deger: "" });
  const add = async () => {
    const deger = U.parseTr(f.deger);
    if (!Number.isFinite(deger) || !deger || (f.tur === "seviye" && deger < 0)) {
      toast.error(f.tur === "yuzde" ? t("Yüzde yaz: -10 düşüş, 15 artış.") : t("Bakiye seviyesi yaz."));
      return;
    }
    if (await sendAction("palarm.add", { ...f, deger }, t("Portföy alarmı kuruluyor."))) setF({ ...f, deger: "" });
  };
  return (
    <K.Card title={`${t("Portföy alarmları")} (${alarms?.length || 0})`}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <K.Field label={t("Piyasa")}>
          <K.Select value={f.piyasa} onChange={(e) => setF({ ...f, piyasa: e.target.value })}
            options={[{ value: "KRIPTO", label: t("Kripto") }, { value: "ABD", label: t("ABD") }, { value: "BIST", label: "BIST" }, { value: "DIGER", label: t("Altın/Döviz") }]} />
        </K.Field>
        <K.Field label={t("Tür")}>
          <K.Select value={f.tur} onChange={(e) => setF({ ...f, tur: e.target.value })}
            options={[{ value: "yuzde", label: t("Şimdiye göre %") }, { value: "seviye", label: t("Bakiye seviyesi") }]} />
        </K.Field>
        <K.Field label={f.tur === "yuzde" ? t("Yüzde (düşüş için eksi)") : t("Seviye")}>
          <K.TextInput inputMode="text" value={f.deger} placeholder={f.tur === "yuzde" ? "-10" : "20.000"} onChange={(e) => setF({ ...f, deger: e.target.value })} />
        </K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={add}>{t("Alarm kur")}</K.Button></div>
      </div>
      {(alarms || []).map((a) => (
        <div key={a.id} className="mt-3 flex flex-wrap items-center justify-between gap-3 text-[0.9375rem] text-t-2">
          <span>{String(a.etiket || "").replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, "").trim()}</span>
          <K.Button variant="ghost" onClick={() => sendAction("palarm.delete", { id: a.id }, t("#{n} siliniyor.", { n: a.id }))}>{t("Sil")}</K.Button>
        </div>
      ))}
      <p className="kp-note">{t("Bakiye = varlık + nakit. 15 dakikada bir kontrol edilir, bir kez haber verir (Telegram).")}</p>
    </K.Card>
  );
}

export default function Portfolio() {
  const { t } = useLang();
  const navigate = useNavigate();
  const q = useData("extras", "/extras", LIVE);
  const [tab, setTab] = useState("Tümü");
  const [editing, setEditing] = useState(null);
  const [gone, setGone] = useState([]); // silinen kayıtlar bot uygulayana kadar da görünmesin
  // Tek tıkla siler: satış sayılmaz, fiyat sorulmaz
  const removeLots = async (code, lots) => {
    setGone((g) => [...g, ...lots.map((l) => l.id)]);
    for (const l of lots) {
      if (!(await sendAction("holding.delete", { id: l.id }, t("{k} silindi.", { k: code })))) setGone((g) => g.filter((id) => id !== l.id));
    }
  };
  return (
    <DataView query={q} loadingText={t("Portföy verisi yükleniyor...")}>
      {(d) => {
        if (!d.guncelleme) return <EmptyState text={t("Bot henüz portföy verisini göndermedi (15 dakikada bir gönderir).")} />;
        const all = (d.portfoy || []).map((g) => {
          const cur = curOf(g.para);
          const code = baseCode(g.ad);
          return {
            id: g.piyasa + code, code, market: g.piyasa, marketLabel: MARKET_UI[g.piyasa]?.label || g.piyasa, cur,
            qty: g.adet, cost: g.adet ? g.maliyet / g.adet : 0, price: g.fiyat, value: g.deger, costv: g.maliyet,
            day: g.gun_yuzde, total: g.toplam_yuzde, pl: g.deger - g.maliyet,
            lots: (g.pozlar || []).filter((l) => !gone.includes(l.id)), old: !g.pozlar,
          };
        }).filter((r) => r.old || r.lots.length);
        if (!all.length) {
          return (
            <div className="kp-page">
              <EmptyState text={t("Portföy boş. Aşağıdan ekle ya da Telegram'da: /portfoy, düz yazıyla “astordan 4 tane 260 TL'den aldım”.")} />
              <AddCard />
              <BulkCard count={0} />
              <CashCard key={JSON.stringify(d.nakit || {})} cash={d.nakit} />
              <DcaCard plans={d.birikim} />
            </div>
          );
        }
        const edited = all.find((r) => r.id === editing);
        const markets = marketRows(d.portfoy);
        const usd = d.usdtry;
        const tl = (m) => (m.cur === "TRY" ? m.value : usd ? m.value * usd : null);
        const totalTl = usd ? markets.reduce((a, m) => a + tl(m), 0) : null;
        const filters = [{ value: "Tümü", label: t("Tümü") }, ...markets.map((m) => ({ value: m.label, label: t(m.label) }))];
        const rows = all.filter((r) => tab === "Tümü" || r.marketLabel === tab);
        const cols = [
          { key: "code", label: t("Kod"), render: (r) => <K.Ticker symbol={r.code} name={t(r.marketLabel)} logo={logo(r.code, r.market)} /> },
          { key: "qty", label: t("Adet"), num: true, render: (r) => QTY.format(r.qty) },
          { key: "cost", label: t("Ort. maliyet"), num: true, render: (r) => priceFmt(r.cost, r.cur) },
          { key: "price", label: t("Fiyat"), num: true, strong: true, render: (r) => priceFmt(r.price, r.cur) },
          { key: "value", label: t("Değer"), num: true, strong: true, mobile: false, render: (r) => U.fmtPrice(r.value, r.cur, 2) },
          { key: "day", label: t("Gün"), num: true, render: (r) => (r.day == null ? "—" : <K.ChangeBadge value={r.day} />) },
          { key: "total", label: t("Toplam"), num: true, render: (r) => <K.ChangeBadge value={r.total} /> },
          { key: "pl", label: t("K/Z"), num: true, render: (r) => <span className={r.pl >= 0 ? "kp-num-up" : "kp-num-down"}>{U.fmtSignedMoney(r.pl, r.cur)}</span> },
          { key: "edit", label: "", render: (r) => r.lots.length > 0 && (
            <K.Button variant="ghost" onClick={(e) => { e.stopPropagation(); setEditing(editing === r.id ? null : r.id); }}>{editing === r.id ? t("Kapat") : t("Düzenle")}</K.Button>) },
          { key: "del", label: "", render: (r) => r.lots.length > 0 && (
            <K.Button variant="ghost" onClick={(e) => { e.stopPropagation(); removeLots(r.code, r.lots); }}>{t("Sil")}</K.Button>) },
        ];
        const warnings = d.yogunlasma?.uyarilar || [];
        const kiyas = d.kiyas?.kiyas || [];
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title={t("Portföy")}
              subtitle={totalTl != null ? t("Toplam {a} · 1 $ = ₺{b} · güncelleme {c}", { a: U.fmtPrice(totalTl, "TRY", 2), b: U.fmtNum(usd, 2), c: formatTime(d.guncelleme) }) : `${t("Güncelleme")} ${formatTime(d.guncelleme)}`} />
            <div className="kp-grid kp-g-3">{markets.map((m) => <K.MarketCard key={m.key} {...m} />)}</div>
            {warnings.length > 0 && <K.Callout tone="warn" title={t("Yoğunlaşma uyarısı")}>{warnings.join(" ")}</K.Callout>}
            <K.Card title={t("Varlıklar")} actions={<K.Segmented ariaLabel={t("Piyasa")} value={tab} onChange={setTab} options={filters} />}>
              <K.DataTable columns={cols} rows={rows} onRowClick={(r) => navigate(chartHref(r.code, r.market))}
                mobileEnd={(r) => U.fmtPrice(r.value, r.cur, 2)} />
              <p className="kp-note">{t("Satıra dokun: o kodun grafiği açılır. Toplam % alış maliyetine göre; rakamları bot kodla hesaplar.")}</p>
            </K.Card>
            {edited && (
              <K.Card title={`${edited.code} · ${t("düzenle")}`} actions={<K.Button variant="ghost" onClick={() => setEditing(null)}>{t("Kapat")}</K.Button>}>
                <div className="kp-col">
                  {edited.lots.map((lot) => <LotRow key={`${lot.id}-${lot.adet}-${lot.giris}-${lot.stop}-${lot.hedef}-${lot.acilis}`} lot={lot} code={edited.code} cur={edited.cur}
                    onDelete={(lots) => removeLots(edited.code, lots)} />)}
                </div>
                <p className="kp-note">{t("“Sil” kaydı tek tıkla kaldırır: satış sayılmaz, K/Z'ye ve günlüğe girmez.")}</p>
              </K.Card>
            )}
            <AddCard />
            <BulkCard count={all.length} />
            <CashCard key={JSON.stringify(d.nakit || {})} cash={d.nakit} />
            <PfAlarmCard alarms={d.portfoy_alarmlari} />
            <HistoryCard rows={d.geriye?.satirlar} real={(d.gecmis || []).filter((x) => x.toplam_tl)} />
            <TargetCard dagilim={d.dagilim} hedef={d.hedef} />
            <DividendCard plan={d.temettu_plani} />
            <DcaCard plans={d.birikim} />
            <div className="kp-grid kp-split-l">
              <K.Card title={t("Dağılım")}>
                {totalTl != null ? (
                  <K.Donut center={{ label: t("Toplam"), value: `${U.fmtPrice(totalTl / 1000, "TRY", 1)} ${t("bin")}` }}
                    items={markets.map((m) => ({ label: t(m.label), value: tl(m), color: m.color,
                      sub: U.fmtPrice(tl(m), "TRY", 0) + (m.cur === "USD" ? ` · ${U.fmtPrice(m.value, "USD", 0)}` : "") }))} />
                ) : <p className="kp-note">{t("Dolar kuru gelince ₺ karşılıklı dağılım gösterilir.")}</p>}
              </K.Card>
              <div className="kp-col">
                <h2 className="kp-card__title">{t("Kıyas · aynı tarihlerde, ₺ bazında")}</h2>
                {kiyas.length ? (
                  <div className="kp-grid kp-g-2">
                    {kiyas.map((b) => <K.CompareCard key={b.ad} label={t(b.ad)} value={b.yuzde ?? 0} mine={d.kiyas.portfoy_yuzde ?? 0} note={b.not || undefined} />)}
                  </div>
                ) : <p className="kp-note">{t("Kıyas için alış tarihi girilmiş pozisyon gerekli: tabloda “Düzenle” ile alış tarihini gir.")}</p>}
                {kiyas.length > 0 && <p className="kp-note">{t("Senin getirin ₺ bazında {x}; her pozisyon kendi alış tarihinden kıyaslanır.", { x: `${d.kiyas.portfoy_yuzde >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(d.kiyas.portfoy_yuzde), 1)}` })}</p>}
              </div>
            </div>
          </div>
        );
      }}
    </DataView>
  );
}
