import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { QueuedBadge } from "@/components/QueuedBadge";
import { AssetLogo, chartHref } from "@/components/AssetLogo";
import { Segmented, KButton, ChangeBadge, Tile } from "@/components/kp";
import api, { formatApiErrorDetail } from "@/lib/api";
import { formatNumber, formatTime } from "@/lib/format";
import { px, qty, MARKET_LABEL } from "@/lib/portfolio";
import { TEXTS } from "@/lib/texts";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const code = (s) => String(s).replace(/\.(IS|US)$/i, "").split("/")[0];
const sym = (p) => (p.currency === "TL" ? "₺" : "$");
const money = (v, p) => `${sym(p)}${formatNumber(Math.abs(v), { decimals: 2 })}`;
const signedMoney = (v, p) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${money(v, p)}`;

// Tasarım sistemindeki PositionCard: başlık, büyük kâr/zarar, üç kutucuk, "Grafiği aç" + "Sattım".
// "Sattım" yalnız botun kaydını günceller; borsada işlem yapmaz.
function PositionCard({ p, queued, onQueued }) {
  const navigate = useNavigate();
  const [selling, setSelling] = useState(false);
  const [price, setPrice] = useState(String(p.current ?? ""));
  const [busy, setBusy] = useState(false);
  const invested = p.entry * p.size;
  const value = (p.current ?? p.entry) * p.size;
  const open = p.status === "open";
  const go = () => navigate(chartHref(p.symbol, p.market));

  const save = async () => {
    const n = Number(String(price).replace(",", "."));
    if (!Number.isFinite(n) || n <= 0) {
      toast.error("Sattığın fiyatı yaz.");
      return;
    }
    setBusy(true);
    try {
      await api.post(`/positions/${p.id}/close`, { price: n });
      toast.success(`${code(p.symbol)} satışı bota iletildi.`, { description: "Telegram'a onay mesajı gelecek." });
      onQueued(p.id);
      setSelling(false);
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Kaydedilemedi.");
    } finally {
      setBusy(false);
    }
  };

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
      ) : queued ? (
        <QueuedBadge label="Satış kaydediliyor" />
      ) : selling ? (
        <div className="flex flex-wrap items-end justify-between gap-4 pt-1">
          <label className="flex flex-col gap-1.5 text-[0.9375rem] font-medium text-t-2">
            Kaçtan sattın?
            <span className="inline-flex h-11 items-center gap-1.5 rounded-[10px] border border-strong bg-ink px-3.5 focus-within:border-info">
              <span className="font-semibold text-t-3">{sym(p)}</span>
              <input type="text" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} autoFocus
                className="num w-36 border-0 bg-transparent text-lg font-bold text-t-1 outline-none" data-testid={`position-sold-price-${p.id}`} />
            </span>
          </label>
          <div className="flex gap-3">
            <KButton variant="ghost" onClick={() => setSelling(false)}>Vazgeç</KButton>
            <KButton variant="primary" disabled={busy} onClick={save} data-testid={`position-sold-save-${p.id}`}>Kaydet</KButton>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap justify-end gap-3">
          <KButton className="min-w-[8.5rem]" onClick={go}>Grafiği aç</KButton>
          <KButton className="min-w-[8.5rem]" onClick={() => setSelling(true)} data-testid={`position-sold-${p.id}`}>Sattım</KButton>
        </div>
      )}
    </div>
  );
}

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
                options={[{ value: "open", label: `Açık ${count("open")}` }, { value: "closed", label: `Kapananlar ${count("closed")}` }]} />
              {!list.length ? <EmptyState text={TEXTS.empty.positions} testid="positions-empty" /> : (
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
