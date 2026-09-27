import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { useData, LIVE } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { chartHref } from "@/components/AssetLogo";
import api, { formatApiErrorDetail } from "@/lib/api";
import { logo, priceFmt, relDay } from "@/lib/dsmap";

// Kullanıcının kendi gerçek portföyü: yalnız onun hesabında tutulur, başka kimse göremez.
// Kapanış işlem yapmaz ve aracı kuruma bağlanmaz: alış/satışı sen yazarsın, sayıları kod hesaplar.
const MARKETS = [{ value: "BIST", label: "BIST" }, { value: "KRIPTO", label: "Kripto" }, { value: "ABD", label: "ABD" }];
const CUR = { TL: "TRY", USD: "USD" };
const num = (v) => (String(v ?? "").trim() === "" ? null : U.parseTr(String(v)));
const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 2)}`);

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

function AddPosition({ onDone }) {
  const [f, setF] = useState({ piyasa: "BIST", kod: "", adet: "", maliyet: "", stop: "", hedef: "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const unit = f.piyasa === "BIST" ? "₺" : "$";
  const save = async () => {
    const body = { piyasa: f.piyasa, kod: f.kod.trim().toUpperCase(), adet: num(f.adet), maliyet: num(f.maliyet),
      stop: num(f.stop), hedef: num(f.hedef) };
    if (!body.kod || !(body.adet > 0) || !(body.maliyet > 0)) return toast.error("Kod, adet ve alış fiyatı gerekli.");
    if (await call(() => api.post("/portfolio/positions", body), `${body.kod} portföyüne eklendi.`)) {
      setF({ ...f, kod: "", adet: "", maliyet: "", stop: "", hedef: "" });
      onDone();
    }
  };
  return (
    <K.Card title="Alım ekle" actions={<span className="kp-alarm__status is-flat">Bot işlem yapmaz</span>}>
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-7">
        <K.Field label="Piyasa"><K.Select value={f.piyasa} onChange={set("piyasa")} options={MARKETS} /></K.Field>
        <K.Field label="Kod"><K.TextInput value={f.kod} placeholder="THYAO, BTC, NVDA" onChange={set("kod")} /></K.Field>
        <K.Field label="Adet"><K.TextInput inputMode="decimal" value={f.adet} onChange={set("adet")} /></K.Field>
        <K.Field label="Alış fiyatı"><K.TextInput prefix={unit} inputMode="decimal" value={f.maliyet} onChange={set("maliyet")} /></K.Field>
        <K.Field label="Stop" hint="isteğe bağlı"><K.TextInput prefix={unit} inputMode="decimal" value={f.stop} onChange={set("stop")} /></K.Field>
        <K.Field label="Hedef" hint="isteğe bağlı"><K.TextInput prefix={unit} inputMode="decimal" value={f.hedef} onChange={set("hedef")} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={save}>Ekle</K.Button></div>
      </div>
      <p className="kp-note">Gerçekte yaptığın alımı yaz. BIST'te adet tam sayı; stop alışın altında, hedef üstünde olmalı (yalnız spot).</p>
    </K.Card>
  );
}

function Cash({ cash, onDone }) {
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({ TL: String(cash?.TL ?? 0), USD: String(cash?.USD ?? 0) });
  const save = async () => {
    for (const para of ["TL", "USD"]) {
      const v = num(f[para]);
      if (v == null || v < 0) return toast.error("Nakit sıfır ya da pozitif olmalı.");
      if (v !== cash?.[para] && !(await call(() => api.put("/portfolio/cash", { para, tutar: v })))) return;
    }
    toast.success("Nakit güncellendi.");
    setEdit(false);
    onDone();
  };
  return (
    <K.Card title="Nakit" actions={<K.Button variant="ghost" onClick={() => setEdit(!edit)}>{edit ? "Vazgeç" : "Değiştir"}</K.Button>}>
      {edit ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <K.Field label="TL"><K.TextInput prefix="₺" inputMode="decimal" value={f.TL} onChange={(e) => setF({ ...f, TL: e.target.value })} /></K.Field>
          <K.Field label="USD"><K.TextInput prefix="$" inputMode="decimal" value={f.USD} onChange={(e) => setF({ ...f, USD: e.target.value })} /></K.Field>
          <div className="flex items-end"><K.Button variant="primary" onClick={save}>Kaydet</K.Button></div>
        </div>
      ) : (
        <div className="kp-grid kp-g-2">
          <K.StatCard label="TL nakit" value={U.fmtPrice(cash?.TL || 0, "TRY", 2)} />
          <K.StatCard label="USD nakit" value={U.fmtPrice(cash?.USD || 0, "USD", 2)} />
        </div>
      )}
    </K.Card>
  );
}

function PositionRow({ p, price, onDone }) {
  const navigate = useNavigate();
  const [mode, setMode] = useState(null);
  const [v, setV] = useState({ fiyat: "", adet: "", stop: "" });
  const cur = CUR[p.para];
  const value = price != null ? price * p.adet : null;
  const pnl = price != null ? (price - p.maliyet) * p.adet : null;
  const sell = async () => {
    const body = { fiyat: num(v.fiyat), adet: num(v.adet) };
    if (!(body.fiyat > 0)) return toast.error("Kaçtan sattığını yaz.");
    const r = await call(() => api.post(`/portfolio/positions/${p.id}/sell`, body));
    if (r) {
      toast.success(`${p.kod} satışı kaydedildi: ${r.kar >= 0 ? "+" : "−"}${priceFmt(Math.abs(r.kar), cur)}`);
      setMode(null);
      onDone();
    }
  };
  const stop = async () => {
    const s = num(v.stop);
    if (!(s > 0)) return toast.error("Yeni stop fiyatını yaz.");
    if (await call(() => api.patch(`/portfolio/positions/${p.id}/stop`, { stop: s }), "Stop güncellendi.")) {
      setMode(null);
      onDone();
    }
  };
  return (
    <div className="flex flex-col gap-3 border-b border-hairline py-4 last:border-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button className="text-left" onClick={() => navigate(chartHref(p.kod, p.piyasa))} title="Grafiği aç">
          <K.Ticker symbol={p.kod} name={`${p.piyasa === "KRIPTO" ? "Kripto" : p.piyasa} · ${U.fmtNum(p.adet, p.piyasa === "BIST" ? 0 : 6)} adet`} logo={logo(p.kod, p.piyasa)} />
        </button>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[0.9375rem]">
          <span className="text-t-2">Alış <b className="num text-t-1">{priceFmt(p.maliyet, cur)}</b></span>
          <span className="text-t-2">Son kapanış <b className="num text-t-1">{price != null ? priceFmt(price, cur) : "—"}</b></span>
          <span className="text-t-2">Değer <b className="num text-t-1">{value != null ? priceFmt(value, cur) : "—"}</b></span>
          <b className={`num ${pnl == null ? "" : pnl >= 0 ? "kp-num-up" : "kp-num-down"}`}>
            {pnl == null ? "—" : `${pnl >= 0 ? "+" : "−"}${priceFmt(Math.abs(pnl), cur)} (${pct((price / p.maliyet - 1) * 100)})`}
          </b>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 text-[0.9375rem] text-t-2">
        <span>Stop {p.stop != null ? <b className="num text-t-1">{priceFmt(p.stop, cur)}</b> : "yok"} · Hedef {p.hedef != null ? <b className="num text-t-1">{priceFmt(p.hedef, cur)}</b> : "yok"} · {relDay(p.acilis)}</span>
        {!mode && (
          <span className="flex gap-2">
            <K.Button variant="ghost" onClick={() => setMode("stop")}>Stopu yükselt</K.Button>
            <K.Button variant="ghost" onClick={() => setMode("sell")}>Sattım</K.Button>
          </span>
        )}
      </div>
      {mode === "sell" && (
        <div className="grid gap-3 sm:grid-cols-4">
          <K.Field label="Satış fiyatı"><K.TextInput inputMode="decimal" value={v.fiyat} onChange={(e) => setV({ ...v, fiyat: e.target.value })} /></K.Field>
          <K.Field label="Adet" hint={`boş = hepsi (${U.fmtNum(p.adet, p.piyasa === "BIST" ? 0 : 6)})`}><K.TextInput inputMode="decimal" value={v.adet} onChange={(e) => setV({ ...v, adet: e.target.value })} /></K.Field>
          <div className="flex items-end gap-2"><K.Button variant="primary" onClick={sell}>Kaydet</K.Button><K.Button variant="ghost" onClick={() => setMode(null)}>Vazgeç</K.Button></div>
        </div>
      )}
      {mode === "stop" && (
        <div className="grid gap-3 sm:grid-cols-4">
          <K.Field label="Yeni stop" hint="yalnız yukarı (goalpost kuralı)"><K.TextInput inputMode="decimal" value={v.stop} onChange={(e) => setV({ ...v, stop: e.target.value })} /></K.Field>
          <div className="flex items-end gap-2"><K.Button variant="primary" onClick={stop}>Kaydet</K.Button><K.Button variant="ghost" onClick={() => setMode(null)}>Vazgeç</K.Button></div>
        </div>
      )}
    </div>
  );
}

export default function MyPortfolio() {
  const qc = useQueryClient();
  const q = useData("my-portfolio", "/portfolio", LIVE);
  const quotes = useData("my-quotes", "/portfolio/quotes", { refetchInterval: 60_000 });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["my-portfolio"] });
    qc.invalidateQueries({ queryKey: ["my-quotes"] });
  };
  return (
    <DataView query={q} loadingText="Portföy yükleniyor...">
      {(d) => {
        const open = d.positions.filter((p) => p.durum === "acik");
        const closed = d.positions.filter((p) => p.durum !== "acik").slice(-10).reverse();
        const px = (p) => quotes.data?.[`${p.piyasa}:${p.kod}`] ?? null;
        const totals = { TL: { deger: 0, maliyet: 0 }, USD: { deger: 0, maliyet: 0 } };
        open.forEach((p) => {
          const price = px(p);
          totals[p.para].maliyet += p.maliyet * p.adet;
          totals[p.para].deger += (price ?? p.maliyet) * p.adet;
        });
        return (
          <div className="kp-page">
            <K.PageHeader controls={false} title="Portföyüm" subtitle="Yalnız senin hesabında tutulur. Fiyat: son kapanmış günlük mum." />
            <div className="kp-grid kp-g-4">
              {["TL", "USD"].map((c) => {
                const t = totals[c];
                const pnl = t.deger - t.maliyet;
                return [
                  <K.StatCard key={`${c}v`} label={`${c === "TL" ? "BIST" : "Kripto + ABD"} değeri`} value={U.fmtPrice(t.deger + (d.cash_balance?.[c] || 0), CUR[c], 2)}
                    sub={`hisse/coin ${U.fmtPrice(t.deger, CUR[c], 2)} · nakit ${U.fmtPrice(d.cash_balance?.[c] || 0, CUR[c], 2)}`} />,
                  <K.StatCard key={`${c}p`} label={`Açık K/Z (${c})`} value={`${pnl >= 0 ? "+" : "−"}${U.fmtPrice(Math.abs(pnl), CUR[c], 2)}`}
                    tone={pnl > 0 ? "up" : pnl < 0 ? "down" : undefined} sub={t.maliyet ? pct((t.deger / t.maliyet - 1) * 100) : "açık pozisyon yok"} />,
                ];
              })}
            </div>
            <AddPosition onDone={refresh} />
            <K.Card title={`Açık pozisyonlar (${open.length})`}>
              {open.length ? open.map((p) => <PositionRow key={p.id} p={p} price={px(p)} onDone={refresh} />)
                : <EmptyState text="Açık pozisyon yok. Yukarıdan gerçekte yaptığın alımı ekle." />}
            </K.Card>
            <Cash key={JSON.stringify(d.cash_balance)} cash={d.cash_balance} onDone={refresh} />
            {closed.length > 0 && (
              <K.Card title="Son kapananlar">
                <K.DataTable rows={closed} columns={[
                  { key: "kod", label: "Kod", render: (r) => <K.Ticker symbol={r.kod} logo={logo(r.kod, r.piyasa)} /> },
                  { key: "maliyet", label: "Alış", num: true, render: (r) => priceFmt(r.maliyet, CUR[r.para]) },
                  { key: "kapanis_fiyat", label: "Satış", num: true, strong: true, render: (r) => priceFmt(r.kapanis_fiyat, CUR[r.para]) },
                  { key: "k", label: "Sonuç", num: true, render: (r) => <span className={r.kapanis_fiyat >= r.maliyet ? "kp-num-up" : "kp-num-down"}>{pct((r.kapanis_fiyat / r.maliyet - 1) * 100)}</span> },
                ]} />
              </K.Card>
            )}
            <p className="kp-note">Stop yalnız yukarı taşınır (goalpost kuralı). Sayılar kodla hesaplanır; yatırım tavsiyesi değildir.</p>
          </div>
        );
      }}
    </DataView>
  );
}
