import { useState } from "react";
import { K, U } from "@/ds";
import { sendAction } from "@/lib/actions";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import { DataView, Panel } from "@/components/DataView";
import { useAuth } from "@/context/AuthContext";
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

const OPTION_LABEL = { sira: "Sırayla (15 dk)", deepseek: "DeepSeek", kimi: "Kimi K3", glm: "GLM 5.3", kod: "kod", qwen: "qwen3 (yerel)" };

// Bot parametreleri: sağ üstte Düzenle → alanlar açılır → Kaydet bota iletilir (saat dilimi hariç)
function ParamsPanel({ d }) {
  const fields = d.duzenlenebilir || [];
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({});
  const start = () => { setF(Object.fromEntries(fields.map((x) => [x.key, x.value == null ? "" : String(x.value)]))); setEdit(true); };
  const save = async () => {
    const changed = Object.fromEntries(fields.filter((x) => String(x.value ?? "") !== f[x.key]).map((x) => [x.key, f[x.key]]));
    if (!Object.keys(changed).length) return setEdit(false);
    if (await sendAction("settings.set", { degerler: changed }, "Ayarlar bota iletildi; sonuç Telegram'a gelir.")) setEdit(false);
  };
  const action = !fields.length ? null : edit
    ? <div className="flex gap-2"><K.Button variant="ghost" onClick={() => setEdit(false)}>Vazgeç</K.Button><K.Button variant="primary" onClick={save}>Kaydet</K.Button></div>
    : <K.Button variant="secondary" onClick={start} data-testid="settings-edit">Düzenle</K.Button>;
  return (
    <Panel title="Bot parametreleri" testid="settings-risk" action={action}>
      {edit ? (
        <div className="flex flex-col gap-3">
          {fields.map((x) => (
            <K.Field key={x.key} label={x.label}>
              {x.options ? (
                <K.Select value={f[x.key]} onChange={(e) => setF({ ...f, [x.key]: e.target.value })}
                  options={x.options.map((o) => ({ value: o, label: OPTION_LABEL[o] || o }))} />
              ) : (
                <K.TextInput value={f[x.key]} inputMode={x.key === "sessizlik" || x.key === "brif" ? "text" : "decimal"}
                  onChange={(e) => setF({ ...f, [x.key]: e.target.value })} />
              )}
            </K.Field>
          ))}
          <Row label="Saat dilimi" value={`${d.timezone} (değiştirilemez)`} />
        </div>
      ) : (
        <>
          {(d.params || []).map((p) => <Row key={p.label} label={p.label} value={p.value} />)}
          <Row label="Saat dilimi" value={d.timezone} />
        </>
      )}
      <p className="mt-3 text-xs text-t-3">{edit ? "Değer aralığı dışındaysa bot reddeder ve Telegram'a nedenini yazar. Sessizlik örneği: hafta içi 12.00-14.30; her gün 23:00-07:30"
        : "Bu değerler bottan okunur. Değiştirmek için Düzenle."}</p>
    </Panel>
  );
}

// Piyasa bazlı otomatik bildirimler: Telegram'daki /kripto, /bist, /abd ac|kapat ile aynı kayıt
function NotificationsPanel({ d }) {
  const rows = d.bildirimler || [];
  const [busy, setBusy] = useState(null);
  const [local, setLocal] = useState({});
  if (!rows.length) return null;
  const flip = async (r, on) => {
    setBusy(r.piyasa);
    if (await sendAction("settings.set", { bildirim: { piyasa: r.piyasa, acik: on } }, `${r.etiket} bildirimleri ${on ? "açılıyor" : "kapatılıyor"}.`)) {
      setLocal((x) => ({ ...x, [r.piyasa]: on }));
    }
    setBusy(null);
  };
  return (
    <Panel title="Bildirimler" testid="settings-notifications">
      <div className="flex flex-col gap-3">
        {rows.map((r) => {
          const on = local[r.piyasa] ?? r.acik;
          return (
            <div key={r.piyasa} className="flex items-center justify-between gap-3">
              <span className="text-sm text-t-1">{r.etiket} bildirimleri</span>
              <button type="button" role="switch" aria-checked={on} aria-label={`${r.etiket} bildirimleri`} disabled={busy === r.piyasa}
                onClick={() => flip(r, !on)} data-testid={`notify-${r.piyasa}`}
                className={`inline-flex h-7 w-[3.25rem] shrink-0 items-center rounded-full border px-0.5 transition-colors duration-150 disabled:opacity-50 ${on ? "justify-end border-up/50 bg-up/20" : "justify-start border-hairline bg-raised"}`}>
                <span className={`grid h-[1.375rem] w-[1.375rem] place-items-center rounded-full text-[9px] font-bold ${on ? "bg-up text-ink" : "bg-t-3 text-ink"}`}>{on ? "AÇ" : "KP"}</span>
              </button>
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-t-3">Kapalı piyasadan otomatik mesaj gelmez (alarm, sinyal, seviye özeti, çıkış uyarısı). Yazdığın komutlar
        yine cevaplanır, kayıtlı alarmlar silinmez; kapalıyken oluşan bildirimler sonradan gönderilmez. Telegram: /bildirimler</p>
    </Panel>
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
            <ParamsPanel d={d} />

            <NotificationsPanel d={d} />

            <Panel title="Hesap" testid="settings-account">
              <Row label="E-posta" value={user?.email || "—"} />
              <Row label="Rol" value={user?.role || "—"} />
              <Row label="Telegram bildirimleri" value={d.notifications?.telegram ? "Açık" : "Kapalı"} />
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
