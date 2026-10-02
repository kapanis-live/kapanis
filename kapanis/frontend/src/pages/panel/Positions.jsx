import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { K, U } from "@/ds";
import { sendAction } from "@/lib/actions";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { AssetLogo, chartHref } from "@/components/AssetLogo";
import { Segmented, KButton, ChangeBadge, Tile } from "@/components/kp";
import { formatNumber, formatTime } from "@/lib/format";
import { px, qty, MARKET_LABEL } from "@/lib/portfolio";
import { TEXTS } from "@/lib/texts";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const code = (s) => String(s).replace(/\.(IS|US)$/i, "").split("/")[0];
const sym = (p) => (p.currency === "TL" ? "₺" : "$");
const money = (v, p) => `${sym(p)}${formatNumber(Math.abs(v), { decimals: 2 })}`;
const signedMoney = (v, p) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${money(v, p)}`;

// Tasarım sistemindeki PositionCard: başlık (tıklayınca grafik açılır), büyük kâr/zarar, üç kutucuk, "Sil".
// "Sil" yalnız botun kaydını kaldırır; borsada işlem yapmaz, satış saymaz.
function PositionCard({ p, queued, onQueued }) {
  const navigate = useNavigate();
  // Tek tıkla kaydı kaldırır: satış sayılmaz, fiyat sorulmaz, K/Z'ye girmez
  const remove = async () => {
    if (await sendAction("holding.delete", { id: Number(String(p.id).replace("pos_", "")) }, `${code(p.symbol)} silindi.`)) onQueued(p.id);
  };
  const invested = p.entry * p.size;
  const value = (p.current ?? p.entry) * p.size;
  const open = p.status === "open";
  const go = () => navigate(chartHref(p.symbol, p.market));
  if (queued) return null; // silindi: bot uygulayana kadar da görünmesin

  return (
    <div className="flex flex-col gap-5 rounded-xl border border-hairline bg-surface p-6" data-testid={`position-${p.id}`}>
      <div className="flex items-center justify-between gap-4">
        <button onClick={go} className="flex min-w-0 items-center gap-3 text-left" title="Grafiği aç">
          <AssetLogo code={code(p.symbol)} market={p.market} size={48} />
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="text-[1.375rem] font-bold tracking-[0.01em] text-t-1">{code(p.symbol)}</span>
            <span className="truncate text-[0.9375rem] text-t-3">{MARKET_LABEL[p.market] || p.market}</span>
          </span>
        </button>
        <span className="text-base font-medium text-t-2">{qty(p.size)} adet</span>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className={cn("num text-[2.125rem] font-bold leading-[1.1] tracking-[-0.01em]", p.pnl > 0 ? "text-up" : p.pnl < 0 ? "text-down" : "text-t-1")}>
          {signedMoney(p.pnl, p)}
        </span>
        <ChangeBadge value={p.pnl_pct} size="lg" />
      </div>

      <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))" }}>
        <Tile label="Yatırdığın">{money(invested, p)}</Tile>
        <Tile label="Şimdiki değeri">{money(value, p)}</Tile>
        <Tile label="Alış → şimdi">{px(p.entry)} <span className="font-medium text-t-3">→</span> {px(p.current)}</Tile>
      </div>

      {!open ? (
        <p className="m-0 text-[0.9375rem] text-t-3">Kapandı · açılış {formatTime(p.opened_at)}</p>
      ) : (
        <div className="flex flex-wrap items-center justify-end gap-3">
          <KButton className="min-w-[8.5rem]" onClick={remove} data-testid={`position-delete-${p.id}`}>Sil</KButton>
        </div>
      )}
    </div>
  );
}

// Sanal işlemler: gerçek para yok, gerçek portföyde sayılmaz; bot canlı fiyatla takip eder
function PaperSection() {
  const q = useData("extras", "/extras", LIVE);
  const [form, setForm] = useState({ kod: "", piyasa: "BIST", fiyat: "", tutar: "" });
  const rows = q.data?.sanal || [];
  const open = async () => {
    const fiyat = U.parseTr(form.fiyat); // tr-TR: "84.500,50", "500.000", "0.5" hepsi doğru okunur
    const tutar = U.parseTr(form.tutar);
    if (!form.kod || !(fiyat > 0) || !(tutar > 0)) {
      toast.error("Kod, fiyat ve tutar gir.");
      return;
    }
    if (await sendAction("paper.open", { kod: form.kod.toUpperCase(), piyasa: form.piyasa, fiyat, tutar }, `${form.kod.toUpperCase()} sanal alım iletildi.`)) {
      setForm({ ...form, kod: "", fiyat: "", tutar: "" });
    }
  };
  const unit = form.piyasa === "BIST" ? "₺" : "$";
  return (
    <div className="space-y-4">
      <K.Card title="Yeni sanal alım" actions={<span className="kp-alarm__status is-flat">Gerçek para yok</span>}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <K.Field label="Piyasa">
            <K.Select value={form.piyasa} onChange={(e) => setForm({ ...form, piyasa: e.target.value })}
              options={[{ value: "BIST", label: "BIST" }, { value: "KRIPTO", label: "Kripto" }, { value: "ABD", label: "ABD" }]} />
          </K.Field>
          <K.Field label="Kod"><K.TextInput value={form.kod} placeholder="THYAO, BTC, NVDA" onChange={(e) => setForm({ ...form, kod: e.target.value })} /></K.Field>
          <K.Field label="Alış fiyatı"><K.TextInput prefix={unit} inputMode="decimal" value={form.fiyat} placeholder="0,00" onChange={(e) => setForm({ ...form, fiyat: e.target.value })} /></K.Field>
          <K.Field label="Tutar"><K.TextInput prefix={unit} inputMode="decimal" value={form.tutar} placeholder="5.000" onChange={(e) => setForm({ ...form, tutar: e.target.value })} /></K.Field>
          <div className="flex items-end"><K.Button variant="primary" onClick={open}>Sanal al</K.Button></div>
        </div>
        <p className="kp-note">Yeni bir stratejiyi önce böyle dene. Sanal işlemler bakiyede, disiplin sınırında ve raporlarda sayılmaz. Telegram: /sanal</p>
      </K.Card>
      {!rows.length ? <EmptyState text="Sanal işlem yok." /> : (
        <K.Card title={`Sanal işlemler (${rows.length})`}>
          <K.DataTable rows={[...rows].reverse()} mobileEnd={(r) => r.kz == null ? "—" : <span className={r.kz >= 0 ? "kp-num-up" : "kp-num-down"}>{U.fmtSignedMoney(r.kz, r.para === "TL" ? "TRY" : "USD")}</span>}
            columns={[
              { key: "kod", label: "Kod", render: (r) => <K.Ticker symbol={r.kod} name={`#${r.id} · ${r.piyasa === "KRIPTO" ? "Kripto" : r.piyasa}`} logo={{ code: r.kod, market: r.piyasa }} /> },
              { key: "adet", label: "Adet", num: true, render: (r) => qty(r.adet) },
              { key: "giris", label: "Alış", num: true, render: (r) => px(r.giris) },
              { key: "fiyat", label: "Şimdi", num: true, strong: true, render: (r) => (r.durum === "acik" ? px(r.fiyat) : `${px(r.cikis)} (satıldı)`) },
              { key: "kz", label: "K/Z", num: true, mobile: false, render: (r) => r.kz == null ? "—" : <span className={r.kz >= 0 ? "kp-num-up" : "kp-num-down"}>{U.fmtSignedMoney(r.kz, r.para === "TL" ? "TRY" : "USD")} ({ChangeText(r.kz_yuzde)})</span> },
              { key: "x", label: "", render: (r) => r.durum === "acik" && <K.Button variant="ghost" onClick={() => sendAction("paper.close", { id: r.id }, `#${r.id} sanal satış iletildi (şu anki fiyattan).`)}>Sattım</K.Button> },
            ]} />
        </K.Card>
      )}
    </div>
  );
}

const ChangeText = (v) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}%${U.fmtNum(Math.abs(v), 2)}`);

export default function Positions() {
  const q = useData("positions", "/positions");
  const [queued, setQueued] = useState({});
  const [tab, setTab] = useState("open");
  return (
    <div>
      <PageHeader title="Pozisyonlar" testid="page-positions"
        subtitle="Elindekiler ve ne durumda oldukları. Bir koda tıkla, grafiği açılsın." />
      <DataView query={q} loadingText={TEXTS.loading.positions}>
        {(positions) => {
          const all = positions || [];
          const count = (k) => all.filter((p) => (k === "open" ? p.status === "open" : p.status !== "open")).length;
          const list = all.filter((p) => (tab === "open" ? p.status === "open" : p.status !== "open"));
          return (
            <div className="space-y-4">
              <Segmented ariaLabel="Pozisyonlar" value={tab} onChange={setTab}
                options={[{ value: "open", label: `Açık ${count("open")}` }, { value: "closed", label: `Kapananlar ${count("closed")}` }, { value: "sanal", label: "Sanal" }]} />
              {tab === "sanal" ? <PaperSection /> : !list.length ? <EmptyState text={TEXTS.empty.positions} testid="positions-empty" /> : (
                <div className="grid gap-4 lg:grid-cols-2">
                  {list.map((p) => (
                    <PositionCard key={p.id} p={p} queued={!!queued[p.id]} onQueued={(id) => setQueued((s) => ({ ...s, [id]: true }))} />
                  ))}
                </div>
              )}
            </div>
          );
        }}
      </DataView>
    </div>
  );
}
