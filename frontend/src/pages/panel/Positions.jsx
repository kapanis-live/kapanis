import { useState } from "react";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, Panel } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { SideBadge, StatusBadge, RRPill, DeltaText } from "@/components/bits";
import { QueuedBadge } from "@/components/QueuedBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import api, { formatApiErrorDetail } from "@/lib/api";
import { formatPrice, formatCurrency } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { toast } from "sonner";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

function StopEditor({ pos, onQueued }) {
  const [val, setVal] = useState(String(pos.stop));
  const [busy, setBusy] = useState(false);
  const num = parseFloat(val);

  // Goalpost: long'da stop aşağı, short'ta stop yukarı çekilemez -> buton pasif
  const lowersRisk =
    pos.side === "long" ? num >= pos.stop : num <= pos.stop;
  const invalid = isNaN(num) || num === pos.stop;
  const disabled = busy || invalid || !lowersRisk;

  const save = async () => {
    setBusy(true);
    try {
      await api.patch(`/positions/${pos.id}/stop`, { stop: num });
      toast.success("Stop güncelleme isteği bota iletildi.");
      onQueued(pos.id, "stop");
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Stop güncellenemedi.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 rounded-lg border border-hairline bg-surface p-3" data-testid={`stop-editor-${pos.id}`}>
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label className="text-xs text-t-3">Yeni stop</label>
          <Input type="number" step="any" value={val} onChange={(e) => setVal(e.target.value)} className="num mt-1 bg-black border-hairline text-t-1 h-8" data-testid={`stop-input-${pos.id}`} />
        </div>
        <Button size="sm" disabled={disabled} onClick={save} data-testid={`stop-save-${pos.id}`}>
          Güncelle
        </Button>
      </div>
      {!invalid && !lowersRisk && (
        <p className="mt-2 text-xs text-down" data-testid={`goalpost-warning-${pos.id}`}>
          Goalpost kuralı: {pos.side === "long" ? "long pozisyonda stop aşağı çekilemez" : "short pozisyonda stop yukarı çekilemez"}. Buton pasif.
        </p>
      )}
    </div>
  );
}

export default function Positions() {
  const q = useData("positions", "/positions");
  const [queued, setQueued] = useState({}); // id -> "stop" | "close"

  const markQueued = (id, kind) => setQueued((s) => ({ ...s, [id]: kind }));

  const close = async (id) => {
    markQueued(id, "close");
    try {
      await api.post(`/positions/${id}/close`);
      toast.success("Kapatma isteği bota iletildi.");
    } catch (err) {
      setQueued((s) => { const n = { ...s }; delete n[id]; return n; });
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Kapatılamadı.");
    }
  };

  return (
    <div>
      <PageHeader title="Pozisyonlar" subtitle="Açık pozisyonlar, goalpost korumalı stop yönetimi." testid="page-positions" />
      <Panel testid="positions-panel">
        <DataView query={q} loadingText={TEXTS.loading.positions}>
          {(positions) =>
            !positions || positions.length === 0 ? (
              <EmptyState text={TEXTS.empty.positions} testid="positions-empty" />
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {positions.map((p) => (
                  <div key={p.id} className="rounded-lg border border-hairline bg-black p-4" data-testid={`position-${p.id}`}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <span className="font-semibold text-t-1">{p.symbol}</span>
                        <SideBadge side={p.side} />
                        <StatusBadge status={p.status} />
                      </div>
                      <RRPill rr={p.rr} />
                    </div>

                    <div className="mt-3 flex items-end justify-between">
                      <div>
                        <div className="text-xs text-t-3">Anlık P/L</div>
                        <div className="num text-lg font-bold">
                          <DeltaText value={p.pnl} suffix="" className="text-lg" /> <span className="text-xs text-t-3">USDT</span>
                        </div>
                      </div>
                      <DeltaText value={p.pnl_pct} />
                    </div>

                    <div className="num mt-3 grid grid-cols-4 gap-2 text-sm">
                      <div><span className="text-t-3 text-xs block">Giriş</span><span className="text-t-1">{formatPrice(p.entry)}</span></div>
                      <div><span className="text-t-3 text-xs block">Anlık</span><span className="text-t-1">{formatPrice(p.current)}</span></div>
                      <div><span className="text-t-3 text-xs block">Stop</span><span className="text-down">{formatPrice(p.stop)}</span></div>
                      <div><span className="text-t-3 text-xs block">Hedef</span><span className="text-up">{formatPrice(p.target)}</span></div>
                    </div>

                    {queued[p.id] === "stop" && (
                      <div className="mt-3"><QueuedBadge label="Stop güncelleniyor" /></div>
                    )}
                    {queued[p.id] === "close" ? (
                      <div className="mt-3"><QueuedBadge label="Kapatılıyor" /></div>
                    ) : (
                      <>
                        {p.status === "open" && queued[p.id] !== "stop" && <StopEditor pos={p} onQueued={markQueued} />}
                        {p.status === "open" && (
                          <Button variant="outline" size="sm" onClick={() => close(p.id)} className={cn("mt-3 w-full border-down/40 text-down hover:bg-down/10")} data-testid={`position-close-${p.id}`}>
                            <X className="h-4 w-4" /> Pozisyonu kapat
                          </Button>
                        )}
                      </>
                    )}
                  </div>
                ))}
              </div>
            )
          }
        </DataView>
      </Panel>
    </div>
  );
}
