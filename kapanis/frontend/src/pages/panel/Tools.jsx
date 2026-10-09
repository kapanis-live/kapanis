import { useState } from "react";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { sendAction } from "@/lib/actions";
import { logo, relDay, priceFmt } from "@/lib/dsmap";
import { useLang } from "@/lib/i18n";

const MARKET_OPTS = [{ value: "BIST", label: "BIST" }, { value: "KRIPTO", label: "Kripto" }, { value: "ABD", label: "ABD" }];
const RULE_ICON = { gecti: "✓", kaldi: "✕", uyari: "!" };
const RULE_CLS = { gecti: "kp-num-up", kaldi: "kp-num-down", uyari: "text-wait" };
const curOf = (m) => (m === "BIST" ? "TRY" : "USD");
const num = (v) => (String(v ?? "").trim() === "" ? null : U.parseTr(String(v)));

// Sonucu bekleme: istek zamanından yeni bir sonuç gelene kadar "hazırlanıyor"
function useResult(tur) {
  const q = useData(["sonuclar", tur], `/sonuclar/${tur}`, LIVE);
  const [asked, setAsked] = useState(null);
  const d = q.data || {};
  const waiting = asked && (!d.zaman || new Date(d.zaman).getTime() < asked - 2000);
  return { d, waiting, markAsked: () => setAsked(Date.now()) };
}

function CheckCard() {
  const { t } = useLang();
  const [form, setForm] = useState({ piyasa: "BIST", kod: "", giris: "", stop: "", hedef: "" });
  const { d, waiting, markAsked } = useResult("kontrol");
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const run = async () => {
    const kod = form.kod.trim().toUpperCase();
    const vals = { giris: num(form.giris), stop: num(form.stop), hedef: num(form.hedef) };
    if (!kod) return toast.error(t("Kod yaz."));
    if (Object.values(vals).some((v) => v !== null && !(v > 0))) return toast.error(t("Fiyatlar sıfırdan büyük sayı olmalı."));
    if (await sendAction("check.request", { kod, piyasa: form.piyasa, ...vals }, t("{k} kod kapısına gönderildi.", { k: kod }))) markAsked();
  };
  const unit = form.piyasa === "BIST" ? "₺" : "$";
  const cur = curOf(d.piyasa);
  return (
    <K.Card title={t("Alım öncesi kontrol")} actions={<span className="kp-alarm__status is-flat">{t("Bot işlem yapmaz")}</span>}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <K.Field label={t("Piyasa")}><K.Select value={form.piyasa} onChange={set("piyasa")} options={MARKET_OPTS.map((o) => ({ ...o, label: t(o.label) }))} /></K.Field>
        <K.Field label={t("Kod")}><K.TextInput value={form.kod} placeholder="THYAO, BTC, NVDA" onChange={set("kod")} /></K.Field>
        <K.Field label={t("Giriş")} hint={t("boş = şu anki fiyat")}><K.TextInput prefix={unit} inputMode="decimal" value={form.giris} onChange={set("giris")} /></K.Field>
        <K.Field label="Stop" hint={t("boş = destekten önerilir")}><K.TextInput prefix={unit} inputMode="decimal" value={form.stop} onChange={set("stop")} /></K.Field>
        <K.Field label={t("Hedef")} hint={t("boş = dirençten önerilir")}><K.TextInput prefix={unit} inputMode="decimal" value={form.hedef} onChange={set("hedef")} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={run} disabled={!!waiting}>{waiting ? t("Kontrol ediliyor…") : t("Kapıdan geçir")}</K.Button></div>
      </div>
      <p className="kp-note">{t("Botun kendi sinyallerine uyguladığı kod kapısının aynısı. GEÇTİ ise kurallara göre adet ve risk yazılır; KALDI ise o fiyattan alım yok. Telegram: /kontrol THYAO 290 280 320")}</p>
      {waiting && <p className="kp-note">{t("Bot kuralları kontrol ediyor (10–30 sn).")}</p>}
      {!waiting && d.hata && <K.Callout tone="warn" title={t("Kontrol yapılamadı")}>{d.hata}</K.Callout>}
      {!waiting && d.kurallar && (
        <div className="mt-5 flex flex-col gap-4">
          <K.Callout tone={d.ok ? "info" : "warn"} title={`${d.kod} (${t(d.piyasa === "KRIPTO" ? "Kripto" : d.piyasa)}) · ${t("KAPI")}: ${t(d.ok ? "GEÇTİ" : "KALDI")}`}>
            {d.ok ? t("Kurallara uygun. Emir fiyatını aracı kurumdan kontrol et.") : t("Kalan kurallar: {r}. Bu fiyattan alım yok.", { r: d.kalan.map((k) => t(`${k}§kural`)).join(", ") })}
            {" · "}{relDay(d.zaman)}
          </K.Callout>
          <div className="kp-grid kp-g-4">
            <K.StatCard label={t("Giriş → stop / hedef")} value={priceFmt(d.giris, cur)} sub={`stop ${priceFmt(d.stop, cur)} (${U.fmtNum(d.stop_yuzde, 2)}%) · ${t("hedef")} ${priceFmt(d.hedef, cur)} (+${U.fmtNum(d.hedef_yuzde, 2)}%)`} />
            <K.StatCard label={t("Risk / ödül (R/R)")} value={d.rr != null ? U.fmtNum(d.rr, 2) : "—"} tone={d.rr >= 2 ? "up" : d.rr != null && d.rr < 1.5 ? "down" : undefined} sub={t("hedef kazancı ÷ stop kaybı")} />
            <K.StatCard label={t("Kurallara göre kademe")} value={d.ok ? priceFmt(d.tutar, cur) : "—"} sub={d.ok ? t("≈ {n} adet", { n: U.fmtNum(d.adet, d.piyasa === "BIST" ? 0 : 4) }) : t("kapı kaldı")} />
            <K.StatCard label={t("Stopta kayıp / hedefte kazanç")} value={d.ok ? `−${priceFmt(d.risk, cur)}` : "—"} tone={d.ok ? "down" : undefined} sub={d.ok ? t("hedefte +{p}", { p: priceFmt(d.kazanc, cur) }) : ""} />
          </div>
          {d.notlar?.length > 0 && <p className="kp-note">{d.notlar.join(" · ")}</p>}
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {d.kurallar.map((c, i) => (
              <li key={i} className="flex gap-3 text-[0.9375rem] leading-snug">
                <b className={`w-4 shrink-0 text-center ${RULE_CLS[c.durum] || ""}`}>{RULE_ICON[c.durum] || "•"}</b>
                <span><b className="text-t-1">{t(`${c.kural}§kural`)}</b> <span className="text-t-2">{c.detay}</span></span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </K.Card>
  );
}

const ROWS = [
  ["skor", "Temel skor /100", 0, ""], ["buyume", "Büyüme (ciro; bankada kredi, USD)", 1, "%"], ["faaliyet_marj", "Faaliyet marjı", 1, "%"],
  ["net_marj", "Net marj", 1, "%"], ["roe", "ROE", 1, "%"], ["borc", "Net borç / FAVÖK", 2, ""], ["fk", "F/K", 1, ""],
  ["pd_dd", "PD/DD", 2, ""], ["fd_favok", "FD/FAVÖK", 1, ""], ["fcf_verim", "Serbest nakit verimi", 1, "%"],
  ["zirveye", "52 hafta zirveye uzaklık", 1, "%"], ["rsi", "RSI (günlük)", 0, ""], ["stage", "Stage (1 taban · 2 yükseliş · 3 tepe · 4 düşüş)", 0, ""],
  ["trend", "Trend (SMA50/200)", null, ""],
];

function CompareCard() {
  const { t, td } = useLang();
  const [piyasa, setPiyasa] = useState("BIST");
  const [codes, setCodes] = useState("");
  const { d, waiting, markAsked } = useResult("karsilastirma");
  const run = async () => {
    const kodlar = [...new Set(codes.toUpperCase().split(/[\s,;]+/).filter(Boolean))];
    if (kodlar.length < 2 || kodlar.length > 4) return toast.error(t("2–4 hisse yaz (virgül ya da boşlukla)."));
    if (await sendAction("compare.request", { piyasa, kodlar }, t("{k} karşılaştırılıyor.", { k: kodlar.join(", ") }))) markAsked();
  };
  const rows = d.satirlar || [];
  const best = d.en_iyi || {};
  const cell = (r, key, dec, suf) => {
    const v = r[key];
    if (v == null) return "—";
    return typeof v === "number" ? `${U.fmtNum(v, dec)}${suf}` : td(String(v));
  };
  return (
    <K.Card title={t("Hisse karşılaştırma")}>
      <div className="grid gap-3 sm:grid-cols-[10rem_1fr_auto]">
        <K.Field label={t("Piyasa")}><K.Select value={piyasa} onChange={(e) => setPiyasa(e.target.value)} options={[{ value: "BIST", label: "BIST" }, { value: "ABD", label: t("ABD") }]} /></K.Field>
        <K.Field label={t("Hisseler (2–4)")}><K.TextInput value={codes} placeholder={piyasa === "BIST" ? "THYAO, PGSUS, EREGL" : "NVDA, AMD"} onChange={(e) => setCodes(e.target.value)} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={run} disabled={!!waiting}>{waiting ? t("Hazırlanıyor…") : t("Karşılaştır")}</K.Button></div>
      </div>
      {waiting && <p className="kp-note">{t("Bilançolar indiriliyor (20–60 sn).")}</p>}
      {!waiting && d.hata && <K.Callout tone="warn" title={t("Karşılaştırılamadı")}>{d.hata}</K.Callout>}
      {!waiting && rows.length > 0 && (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full border-collapse text-[0.9375rem]">
            <thead>
              <tr>
                <th className="h-12 border-b border-hairline pr-3 text-left text-sm font-semibold text-t-3">{relDay(d.zaman)}</th>
                {rows.map((r) => (
                  <th key={r.kod} className="h-12 min-w-[8rem] border-b border-hairline px-3 text-right">
                    <span className="inline-flex justify-end"><K.Ticker symbol={r.kod} logo={logo(r.kod, d.piyasa)} /></span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([key, label, dec, suf]) => (
                <tr key={key} className="border-b border-hairline last:border-0">
                  <td className="py-2.5 pr-3 text-t-2">{t(label)}</td>
                  {rows.map((r) => (
                    <td key={r.kod} className={`num px-3 text-right ${best[key] === r.kod ? "font-bold text-up" : "text-t-1"}`}>
                      {cell(r, key, dec, suf)}{best[key] === r.kod ? " ★" : ""}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td className="py-2.5 pr-3 text-t-2">{t("Durum")}</td>
                {rows.map((r) => <td key={r.kod} className="px-3 text-right text-[0.875rem] font-semibold text-t-1">{r.etiket}</td>)}
              </tr>
            </tbody>
          </table>
          {rows.filter((r) => r.uyarilar?.length).map((r) => (
            <p key={r.kod} className="kp-note"><b>{r.kod}:</b> {r.uyarilar.map(td).join("; ")}</p>
          ))}
          {d.hatalar?.map((e) => <p key={e} className="kp-note">{e}</p>)}
        </div>
      )}
      <p className="kp-note">{t("★ o ölçüde en iyi. Skor kalite ölçüsüdür, yükselme olasılığı değil; öneri değildir. Telegram: /karsilastir THYAO PGSUS")}</p>
    </K.Card>
  );
}

function FundamentalsCard() {
  const { t, td } = useLang();
  const [kod, setKod] = useState("");
  const { d, waiting, markAsked } = useResult("temel");
  const run = async () => {
    const k = kod.trim().toUpperCase();
    if (!k) return toast.error(t("Hisse kodu yaz."));
    if (await sendAction("fundamentals.request", { kod: k }, t("{k} temel analizi istendi.", { k }))) markAsked();
  };
  return (
    <K.Card title={t("Temel analiz (tek hisse)")}>
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <K.Field label={t("Hisse (BIST ya da ABD)")}><K.TextInput value={kod} placeholder="THYAO, AAPL" onChange={(e) => setKod(e.target.value)} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={run} disabled={!!waiting}>{waiting ? t("Hazırlanıyor…") : t("Getir")}</K.Button></div>
      </div>
      {waiting && <p className="kp-note">{t("Bilançolar indiriliyor (10–40 sn). Yapay zekâ kullanılmaz.")}</p>}
      {!waiting && d.hata && <K.Callout tone="warn" title={t("Getirilemedi")}>{d.hata}</K.Callout>}
      {!waiting && d.kod && (
        <div className="mt-5 flex flex-col gap-4">
          <div className="kp-grid kp-g-3">
            <K.StatCard label={`${d.kod} · ${d.piyasa}`} value={`${U.fmtNum(d.skor, 0)}/100`} tone={d.skor >= 70 ? "up" : d.skor < 45 ? "down" : undefined} sub={d.etiket} />
            {Object.entries(d.parcalar || {}).slice(0, 2).map(([k, v]) => <K.StatCard key={k} label={k} value={v} />)}
          </div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(d.parcalar || {}).map(([k, v]) => (
              <span key={k} className="rounded-lg border border-hairline px-3 py-1 text-[0.9375rem] text-t-2">{k}: <b className="num text-t-1">{v}</b></span>
            ))}
          </div>
          {d.olumlular?.length > 0 && <K.Callout tone="info" title={t("Olumlu")}>{d.olumlular.map(td).join("; ")}</K.Callout>}
          {d.uyarilar?.length > 0 && <K.Callout tone="warn" title={t("Uyarılar")}>{d.uyarilar.map(td).join("; ")}</K.Callout>}
          <details>
            <summary className="cursor-pointer text-[0.9375rem] font-semibold text-t-1">{t("Tüm rakamlar")}</summary>
            <pre className="mt-3 whitespace-pre-wrap text-[0.875rem] leading-relaxed text-t-2" style={{ fontFamily: "inherit" }}>
              {String(d.metin || "").replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, "").trim()}
            </pre>
          </details>
          <p className="kp-note">{d.not} · {relDay(d.zaman)} · {d.kaynak}</p>
        </div>
      )}
    </K.Card>
  );
}

export default function Tools() {
  const { t } = useLang();
  return (
    <div className="kp-page">
      <K.PageHeader controls={false} title={t("Kontrol ve karşılaştırma")}
        subtitle={t("Sayıları kod hesaplar. Almadan önce kapıdan geçir, hisseleri yan yana koy.")} />
      <CheckCard />
      <FundamentalsCard />
      <CompareCard />
    </div>
  );
}
