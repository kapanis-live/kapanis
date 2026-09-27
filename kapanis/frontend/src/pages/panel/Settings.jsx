import { useState } from "react";
import { K, U } from "@/ds";
import { sendAction } from "@/lib/actions";
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

// Panelden değiştirilebilen ayarlar; kurallar kodda sabit kalır.
function EditCard() {
  const [f, setF] = useState({ ai_mod: "sira", bist_butce: "", abd_butce: "" });
  const save = () => {
    const body = { ai_mod: f.ai_mod };
    if (f.bist_butce.trim()) body.bist_butce = U.parseTr(f.bist_butce);
    if (f.abd_butce.trim()) body.abd_butce = U.parseTr(f.abd_butce);
    sendAction("settings.set", body, "Ayarlar bota iletildi.");
  };
  return (
    <K.Card title="Değiştir">
      <div className="grid gap-3 sm:grid-cols-4">
        <K.Field label="Yapay zekâ modeli" hint="sıra = 15 dakikada bir değişir">
          <K.Select value={f.ai_mod} onChange={(e) => setF({ ...f, ai_mod: e.target.value })}
            options={[{ value: "sira", label: "Sırayla" }, { value: "deepseek", label: "DeepSeek" }, { value: "kimi", label: "Kimi K3" }, { value: "glm", label: "GLM 5.3" }]} />
        </K.Field>
        <K.Field label="BIST bütçesi" hint="boş = değişmez"><K.TextInput prefix="₺" inputMode="decimal" value={f.bist_butce} onChange={(e) => setF({ ...f, bist_butce: e.target.value })} /></K.Field>
        <K.Field label="ABD bütçesi" hint="boş = değişmez"><K.TextInput prefix="$" inputMode="decimal" value={f.abd_butce} onChange={(e) => setF({ ...f, abd_butce: e.target.value })} /></K.Field>
        <div className="flex items-end"><K.Button variant="primary" onClick={save}>Kaydet</K.Button></div>
      </div>
      <p className="kp-note">Sessiz saatler Telegram'dan: /set_config quiet_hours=09:00-16:00. Kademe ve risk kuralları kodda sabittir.</p>
    </K.Card>
  );
}

export default function Settings() {
  const q = useData("settings", "/settings");
  const { user } = useAuth();
  return (
    <div>
      <PageHeader eyebrow="Sistem / Ayarlar" title="Ayarlar" subtitle="Risk parametreleri, hesap ve kuralların salt okunur özeti." testid="page-settings" />
      <DataView query={q} loadingText={TEXTS.loading.default}>
        {(d) => (
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Bot parametreleri" testid="settings-risk">
              {d.params ? (
                d.params.map((p) => <Row key={p.label} label={p.label} value={p.value} />)
              ) : (
                <>
                  <Row label="İşlem başına risk" value={`%${formatNumber(d.risk_per_trade_pct, { decimals: 1 })}`} />
                  <Row label="Maks. açık pozisyon" value={formatNumber(d.max_open_positions, { decimals: 0 })} />
                  <Row label="Minimum R/R" value={formatNumber(d.default_rr_min, { decimals: 1 })} />
                </>
              )}
              <Row label="Saat dilimi" value={d.timezone} />
              <p className="mt-3 text-xs text-t-3">Bu değerler bottan okunur. Model ve bütçeler aşağıdan değiştirilebilir.</p>
            </Panel>

            <Panel title="Hesap" testid="settings-account">
              <Row label="E-posta" value={user?.email || "—"} />
              <Row label="Rol" value={user?.role || "—"} />
              <Row label="Telegram bildirimleri" value={d.notifications?.telegram ? "Açık" : "Kapalı"} />
            </Panel>

            <div className="lg:col-span-2"><EditCard /></div>

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
