import { useState, useMemo } from "react";
import { PageHeader } from "@/components/PanelLayout";
import { useData, usePendingCommands, LIVE } from "@/lib/useData";
import { DataView, Panel } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { SideBadge, StatusBadge, RRPill, rrTone } from "@/components/bits";
import { QueuedBadge } from "@/components/QueuedBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useQueryClient } from "@tanstack/react-query";
import api, { formatApiErrorDetail } from "@/lib/api";
import { formatPrice, formatTime, relativeTime } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { toast } from "sonner";
import { Trash2, Plus, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

function computeRR(side, entry, stop, target) {
  const e = parseFloat(entry), s = parseFloat(stop), t = parseFloat(target);
  if ([e, s, t].some((v) => isNaN(v))) return null;
  const risk = Math.abs(e - s);
  const reward = Math.abs(t - e);
  if (risk === 0) return null;
  // yön geçerliliği
  if (side === "long" && !(s < e && t > e)) return null;
  if (side === "short" && !(s > e && t < e)) return null;
  return reward / risk;
}

const RR_HINT = { up: "R/R yeterli (≥ 1.5)", wait: "Sınırda (1.0 – 1.5) — RİSK-OFF rejimde pas", down: "R/R 1'in altında — kural gereği pas", muted: "Geçerli tetik/iptal/hedef gir" };
const TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"];

export default function Alerts() {
  const q = useData("alerts", "/alerts", LIVE);
  const qc = useQueryClient();
  const pend = usePendingCommands();
  const [form, setForm] = useState({ symbol: "", side: "long", entry: "", stop: "", target: "", note: "", timeframe: "15m" });
  const [submitting, setSubmitting] = useState(false);
  const [queuedIds, setQueuedIds] = useState([]);

  const rr = useMemo(() => computeRR(form.side, form.entry, form.stop, form.target), [form]);
  const tone = rrTone(rr);
  const canSubmit = form.symbol.trim() && rr !== null && !submitting;

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await api.post("/alerts", {
        symbol: form.symbol.trim().toUpperCase(),
        side: form.side,
        entry: parseFloat(form.entry),
        stop: parseFloat(form.stop),
        target: parseFloat(form.target),
        note: form.note,
        timeframe: form.timeframe,
      });
      toast.success("Alarm bota iletildi. Bot işleyince listede güncellenecek.");
      setForm({ symbol: "", side: "long", entry: "", stop: "", target: "", note: "", timeframe: "15m" });
      qc.invalidateQueries({ queryKey: ["commands"] });
    } catch (err) {
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Alarm oluşturulamadı.");
    } finally {
      setSubmitting(false);
    }
  };

  const [confirmId, setConfirmId] = useState(null);

  const remove = async (id) => {
    setConfirmId(null);
    setQueuedIds((s) => [...s, id]);
    try {
      await api.delete(`/alerts/${id}`);
      toast.success("Silme isteği bota iletildi.");
    } catch (err) {
      setQueuedIds((s) => s.filter((x) => x !== id));
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Silinemedi.");
    }
  };

  return (
    <div>
      <PageHeader eyebrow="Sinyaller / Alarmlar" title="Alarmlar" subtitle="Kurulu alarmlar ve canlı R/R ile yeni alarm." testid="page-alerts" />

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Yeni alarm formu */}
        <Panel title="Yeni alarm" testid="alert-form-panel" className="lg:col-span-1">
          <form onSubmit={submit} className="space-y-3.5" data-testid="alert-form">
            <div className="space-y-1.5">
              <Label className="text-t-2">Sembol</Label>
              <Input value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} placeholder="BTC/USDT" className="bg-ink border-hairline text-t-1 uppercase" data-testid="alert-symbol" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-t-2">Yön</Label>
              <Select value={form.side} onValueChange={(v) => setForm({ ...form, side: v })}>
                <SelectTrigger className="bg-ink border-hairline text-t-1" data-testid="alert-side"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="long">Long</SelectItem>
                  <SelectItem value="short">Short</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-t-2">Zaman dilimi</Label>
              <Select value={form.timeframe} onValueChange={(v) => setForm({ ...form, timeframe: v })}>
                <SelectTrigger className="bg-ink border-hairline text-t-1" data-testid="alert-timeframe"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {TIMEFRAMES.map((tf) => <SelectItem key={tf} value={tf}>{tf}</SelectItem>)}
                </SelectContent>
              </Select>
              <p className="text-xs text-t-3">Mod: KAPANIŞ (sabit). Sadece mum kapanışı tetikler; iğne asla.</p>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div className="space-y-1.5">
                <Label className="text-t-2 text-xs">Tetik</Label>
                <Input type="number" step="any" value={form.entry} onChange={(e) => setForm({ ...form, entry: e.target.value })} className="num bg-ink border-hairline text-t-1" data-testid="alert-entry" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-t-2 text-xs">İptal</Label>
                <Input type="number" step="any" value={form.stop} onChange={(e) => setForm({ ...form, stop: e.target.value })} className="num bg-ink border-hairline text-t-1" data-testid="alert-stop" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-t-2 text-xs">Hedef</Label>
                <Input type="number" step="any" value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} className="num bg-ink border-hairline text-t-1" data-testid="alert-target" />
              </div>
            </div>

            {/* Canlı R/R */}
            <div className={cn("rounded-lg border p-3 transition-colors duration-200",
              tone === "up" ? "border-up/40 bg-up/5" : tone === "wait" ? "border-wait/40 bg-wait/5" : tone === "down" ? "border-down/40 bg-down/5" : "border-hairline bg-ink")}
              data-testid="alert-live-rr">
              <div className="flex items-center justify-between">
                <span className="text-xs text-t-2">Canlı R/R</span>
                <RRPill rr={rr} testid="alert-rr-pill" />
              </div>
              <p className={cn("mt-1.5 text-xs",
                tone === "up" ? "text-up" : tone === "wait" ? "text-wait" : tone === "down" ? "text-down" : "text-t-3")}>
                {RR_HINT[tone]}
              </p>
            </div>

            <Button type="submit" disabled={!canSubmit} className="w-full" data-testid="alert-submit">
              {submitting ? <><Loader2 className="h-4 w-4 animate-spin" /> İletiliyor…</> : <><Plus className="h-4 w-4" /> Alarm kur</>}
            </Button>
            <p className="text-xs text-t-3">İşlem doğrudan uygulanmaz; bota iletilir ve beklemede görünür.</p>
          </form>
        </Panel>

        {/* Liste */}
        <div className="lg:col-span-2">
          <Panel title="Kurulu alarmlar" testid="alerts-list-panel">
            <DataView query={q} loadingText={TEXTS.loading.alerts}>
              {(alerts) =>
                !alerts || alerts.length === 0 ? (
                  <EmptyState text={TEXTS.empty.alerts} testid="alerts-empty" />
                ) : (
                  <div className="space-y-2.5">
                    {alerts.map((a) => (
                      <div key={a.id} className="rounded-lg border border-hairline bg-ink p-4" data-testid={`alert-row-${a.id}`}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex items-center gap-2.5">
                            <span className="font-semibold text-t-1">{a.symbol}</span>
                            <SideBadge side={a.side} />
                            <StatusBadge status={a.status} />
                          </div>
                          <div className="flex items-center gap-2">
                            <RRPill rr={a.rr} />
                            {queuedIds.includes(a.id) ? (
                              <QueuedBadge label="Siliniyor" />
                            ) : confirmId === a.id ? (
                              <span className="flex items-center gap-1.5 text-xs">
                                <span className="text-t-2">Silinsin mi?</span>
                                <button onClick={() => remove(a.id)} className="rounded-md bg-down/15 px-2 py-1 font-semibold text-down hover:bg-down/25" data-testid={`alert-delete-confirm-${a.id}`}>Sil</button>
                                <button onClick={() => setConfirmId(null)} className="rounded-md px-2 py-1 text-t-2 hover:bg-raised hover:text-t-1">Vazgeç</button>
                              </span>
                            ) : (
                              <button onClick={() => setConfirmId(a.id)} className="rounded-md p-1.5 text-t-3 transition-colors duration-150 hover:bg-down/10 hover:text-down" data-testid={`alert-delete-${a.id}`} aria-label="Sil">
                                <Trash2 className="h-4 w-4" />
                              </button>
                            )}
                          </div>
                        </div>
                        <div className="num mt-2.5 grid grid-cols-3 gap-2 text-sm">
                          <div><span className="text-t-3 text-xs block">Giriş</span><span className="text-t-1">{formatPrice(a.entry)}</span></div>
                          <div><span className="text-t-3 text-xs block">Stop</span><span className="text-down">{formatPrice(a.stop)}</span></div>
                          <div><span className="text-t-3 text-xs block">Hedef</span><span className="text-up">{formatPrice(a.target)}</span></div>
                        </div>
                        {a.note && <p className="mt-2 text-xs text-t-2">{a.note}</p>}
                        <p className="mt-1.5 text-xs text-t-3">{formatTime(a.created_at)} · {relativeTime(a.created_at)}</p>
                      </div>
                    ))}
                  </div>
                )
              }
            </DataView>
          </Panel>
        </div>
      </div>
    </div>
  );
}
