import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, Panel } from "@/components/DataView";
import { useAuth } from "@/context/AuthContext";
import { formatNumber } from "@/lib/format";
import { TEXTS } from "@/lib/texts";
import { Check, ShieldCheck } from "lucide-react";

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between border-b border-hairline py-2.5 last:border-0">
      <span className="text-sm text-t-2">{label}</span>
      <span className="num text-sm font-medium text-t-1">{value}</span>
    </div>
  );
}

export default function Settings() {
  const q = useData("settings", "/settings");
  const { user } = useAuth();
  return (
    <div>
      <PageHeader title="Ayarlar" subtitle="Risk parametreleri, hesap ve kuralların salt okunur özeti." testid="page-settings" />
      <DataView query={q} loadingText={TEXTS.loading.default}>
        {(d) => (
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Risk parametreleri" testid="settings-risk">
              <Row label="İşlem başına risk" value={`%${formatNumber(d.risk_per_trade_pct, { decimals: 1 })}`} />
              <Row label="Maks. açık pozisyon" value={formatNumber(d.max_open_positions, { decimals: 0 })} />
              <Row label="Minimum R/R" value={formatNumber(d.default_rr_min, { decimals: 1 })} />
              <Row label="Saat dilimi" value={d.timezone} />
            </Panel>

            <Panel title="Hesap" testid="settings-account">
              <Row label="E-posta" value={user?.email || "—"} />
              <Row label="Rol" value={user?.role || "—"} />
              <Row label="Telegram bildirimleri" value={d.notifications?.telegram ? "Açık" : "Kapalı"} />
              <Row label="E-posta bildirimleri" value={d.notifications?.email ? "Açık" : "Kapalı"} />
            </Panel>

            <Panel title="Kurallar (salt okunur)" testid="settings-rules" className="lg:col-span-2">
              <div className="mb-3 flex items-center gap-2 text-xs text-t-3">
                <ShieldCheck className="h-4 w-4" /> Bu kurallar karar motorunda sabittir; panelden değiştirilemez.
              </div>
              <ul className="space-y-2.5">
                {d.rules_readonly?.map((r, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-sm text-t-1" data-testid={`setting-rule-${i}`}>
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-up" />
                    {r}
                  </li>
                ))}
              </ul>
            </Panel>
          </div>
        )}
      </DataView>
    </div>
  );
}
