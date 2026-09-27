import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useClerk } from "@clerk/react";
import { K } from "@/ds";
import { useAuth } from "@/context/AuthContext";
import { useData } from "@/lib/useData";
import api, { formatApiErrorDetail } from "@/lib/api";
import { relDay } from "@/lib/dsmap";

// Hesap & Telegram (Claude Design "Kullanıcı paneli · Hesap"). Görünüm tasarım sisteminin sınıflarıyla,
// davranış gerçek API ile: Telegram kodu, API anahtarları, veri indirme, hesap silme.
const err = (e, fallback) => toast.error(formatApiErrorDetail(e.response?.data?.detail) || fallback);

function ClerkProfileButton() {
  const clerk = useClerk();
  return <K.Button variant="ghost" onClick={() => clerk.openUserProfile()}>Giriş ayarları</K.Button>;
}

// TelegramLink'in görünümü; kod sunucudan, bağlantı durumu 5 sn'de bir sunucudan
function TelegramCard() {
  const qc = useQueryClient();
  const st = useData("tg-status", "/telegram/status", { refetchInterval: 5000 });
  const cfg = useData("auth-config", "/auth/config");
  const [code, setCode] = useState(null);
  const [copied, setCopied] = useState(false);
  const bot = cfg.data?.telegram_bot;
  const linked = st.data?.bagli;
  const newCode = async () => {
    try {
      const { data } = await api.post("/telegram/link-code");
      setCode({ ...data, at: Date.now() });
      setCopied(false);
    } catch (e) {
      err(e, "Kod alınamadı.");
    }
  };
  const unlink = async () => {
    await api.delete("/telegram/link");
    setCode(null);
    qc.invalidateQueries({ queryKey: ["tg-status"] });
    toast.success("Telegram bağlantısı kaldırıldı.");
  };
  let body;
  if (linked) {
    body = (
      <div className="kp-tg">
        <div className="kp-tg__status"><span className="kp-live__dot is-up" aria-hidden />
          <div><div className="kp-tg__title">Telegram bağlı</div><div className="kp-tg__sub">{st.data?.kullanici_adi ? `@${st.data.kullanici_adi}` : "Sohbet bağlı"}</div></div></div>
        <p className="kp-tg__text">Panelden istediğin analizlerin sonucu bu sohbete de gelir.</p>
        <div><K.Button variant="ghost" onClick={unlink}>Bağlantıyı kaldır</K.Button></div>
      </div>
    );
  } else if (code) {
    const cmd = `/bagla ${code.kod}`;
    body = (
      <div className="kp-tg">
        <ol className="kp-tg__steps">
          <li>Telegram’da {bot ? <a className="kp-link" href={`https://t.me/${bot}`} target="_blank" rel="noreferrer"><b>@{bot}</b></a> : <b>Kapanış botu</b>} sohbetini aç.</li>
          <li>Aşağıdaki komutu olduğu gibi gönder.</li>
        </ol>
        <div className="kp-tg__code">
          <span className="kp-tg__cmd">{cmd}</span>
          <K.Button variant="secondary" icon={<K.Icon name={copied ? "check" : "copy"} size={18} />}
            onClick={() => { navigator.clipboard?.writeText(cmd).catch(() => {}); setCopied(true); }}>{copied ? "Kopyalandı" : "Kopyala"}</K.Button>
        </div>
        <div className="kp-tg__meta">Tek kullanımlık kod · <b>{code.dakika} dk</b> geçerli
          <button type="button" className="kp-linkbtn" onClick={newCode}>Yeni kod al</button></div>
      </div>
    );
  } else {
    body = (
      <div className="kp-tg">
        <div className="kp-tg__status"><span className="kp-live__dot" aria-hidden />
          <div><div className="kp-tg__title">Telegram bağlı değil</div><div className="kp-tg__sub">Bağlarsan analiz sonucun telefonuna da gelir. Bağlamazsan yalnız sitede görünür.</div></div></div>
        <div><K.Button variant="secondary" icon={<K.Icon name="send" size={18} />} onClick={newCode}>Telegram’ı bağla</K.Button></div>
      </div>
    );
  }
  return <K.Card title="Telegram">{body}</K.Card>;
}

// ApiKeyList'in görünümü; kaydetme sağlayıcıda doğrulanır, sunucuda şifreli saklanır
const KEY_INFO = {
  deepseek: { note: "V4.1 Flash · ücretli, kullandığın kadar", url: "https://platform.deepseek.com/api_keys" },
  nvidia: { note: "Kimi K3 ve GLM 5.3 · NVIDIA ücretsiz kredisi", url: "https://build.nvidia.com" },
};
function KeyRow({ prov, label, saved, enabled, onChanged }) {
  const [mode, setMode] = useState(saved ? "saved" : "empty");
  const [v, setV] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const state = saved && mode !== "edit" ? "saved" : mode === "edit" ? "edit" : "empty";
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.put("/ai-keys", { saglayici: prov, anahtar: v.trim() });
      toast.success(`${label} anahtarın doğrulandı ve şifreli kaydedildi.`);
      setV("");
      setMode("saved");
      onChanged();
    } catch (ex) {
      err(ex, "Kaydedilemedi.");
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    await api.delete(`/ai-keys/${prov}`);
    setConfirm(false);
    setMode("empty");
    toast.success("Anahtar silindi.");
    onChanged();
  };
  return (
    <li className="kp-keys__row">
      <div className="kp-keys__head">
        <div><div className="kp-keys__name">{label}</div>
          <div className="kp-keys__note">{KEY_INFO[prov].note} · <a className="kp-link" href={KEY_INFO[prov].url} target="_blank" rel="noreferrer">anahtar al</a></div></div>
        <span className={`kp-keys__state ${state === "saved" ? "is-on" : ""}`}>{state === "saved" ? "Kayıtlı" : "Eklenmedi"}</span>
      </div>
      {state === "saved" ? (
        <div className="kp-keys__saved">
          <span className="kp-keys__mask">{saved.maske}</span>
          {confirm ? (
            <div className="kp-confirm" role="group" aria-label="Silme onayı"><span className="kp-confirm__q">Silinsin mi?</span>
              <K.Button variant="ghost" onClick={() => setConfirm(false)}>Vazgeç</K.Button>
              <K.Button variant="danger" onClick={remove}>Sil</K.Button></div>
          ) : (
            <div className="kp-keys__actions">
              <K.Button variant="ghost" onClick={() => setMode("edit")}>Değiştir</K.Button>
              <K.Button variant="ghost" icon={<K.Icon name="trash" size={18} />} onClick={() => setConfirm(true)}>Sil</K.Button>
            </div>
          )}
        </div>
      ) : (
        <form className="kp-keys__form" onSubmit={save}>
          <K.TextInput type="password" autoComplete="off" placeholder="Anahtarı yapıştır" aria-label={`${label} API anahtarı`}
            value={v} onChange={(e) => setV(e.target.value.trim())} />
          <K.Button variant="secondary" type="submit" disabled={v.length < 20 || busy || !enabled}>{busy ? "Doğrulanıyor…" : "Kaydet"}</K.Button>
          {state === "edit" && <K.Button variant="ghost" onClick={() => setMode("saved")}>Vazgeç</K.Button>}
        </form>
      )}
    </li>
  );
}
function KeysCard({ quota }) {
  const qc = useQueryClient();
  const { refresh } = useAuth();
  const q = useData("ai-keys", "/ai-keys");
  const d = q.data;
  const changed = () => {
    qc.invalidateQueries({ queryKey: ["ai-keys"] });
    qc.invalidateQueries({ queryKey: ["quota"] });
    refresh?.();
  };
  if (!d) return null;
  return (
    <K.Card title="Yapay zekâ anahtarların">
      {!d.sifreleme && <K.Callout tone="warn" title="Şu an kaydedilemiyor">Sunucuda anahtar şifreleme ayarlı değil.</K.Callout>}
      <ul className="kp-keys">
        {Object.keys(d.etiketler).map((prov) => (
          <KeyRow key={prov + (d.anahtarlar[prov]?.maske || "")} prov={prov} label={d.etiketler[prov]} saved={d.anahtarlar[prov]} enabled={d.sifreleme} onChanged={changed} />
        ))}
      </ul>
      <p className="kp-note">Anahtarlar şifreli saklanır, yalnız senin analizin çalışırken kullanılır ve başka hesaba geçmez.
        {quota?.anahtarla_sinir ? ` Kendi anahtarınla günde ${quota.anahtarla_sinir} analiz.` : ""}</p>
    </K.Card>
  );
}

export function Quota({ q }) {
  if (!q || q.sahip) return null;
  const limit = q.kendi_anahtari ? q.anahtarla_sinir : q.sinir;
  return <K.QuotaMeter used={q.kullanilan} limit={Math.max(1, limit)} ownLimit={q.anahtarla_sinir} ownKey={q.kendi_anahtari}
    reset="Haklar son 24 saate göre sayılır." />;
}

export default function Account() {
  const { user, mode, owner, logout } = useAuth();
  const quota = useData("quota", "/quota", { refetchInterval: 30_000 });
  const download = async () => {
    try {
      const { data } = await api.get("/account/export");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      Object.assign(document.createElement("a"), { href: url, download: "kapanis-verilerim.json" }).click();
      URL.revokeObjectURL(url);
    } catch (e) {
      err(e, "İndirilemedi.");
    }
  };
  const remove = async () => {
    try {
      await api.delete("/account");
      toast.success("Hesabın ve verilerin silindi.");
      await logout();
    } catch (e) {
      err(e, "Silinemedi.");
    }
  };
  return (
    <div className="kp-page">
      <K.PageHeader controls={false} title="Hesap & Telegram" />
      <div className="kp-grid kp-split">
        <div className="kp-col">
          <K.Card title="Hesap" actions={mode === "clerk" && user?.clerk_id ? <ClerkProfileButton /> : null}>
            <dl className="kp-kv">
              <dt>E-posta</dt><dd style={{ overflowWrap: "anywhere" }}>{user?.email || "—"}</dd>
              <dt>Giriş türü</dt><dd>{user?.clerk_id ? "Google ya da e-posta + kod" : "Bu bilgisayar (yönetici şifresi)"}</dd>
              <dt>Rol</dt><dd>{owner ? "Sistem sahibi" : "Kullanıcı"}</dd>
              {user?.created_at && <><dt>Üyelik</dt><dd>{relDay(user.created_at)}</dd></>}
              {!owner && <><dt>Günlük analiz</dt><dd><Quota q={quota.data} /></dd></>}
            </dl>
          </K.Card>
          <TelegramCard />
          {!owner && <KeysCard quota={quota.data} />}
        </div>
        <div className="kp-col">
          <K.Card title="Verilerimi indir">
            <p style={{ margin: "0 0 1rem", color: "var(--text-2)" }}>Portföyün, işlemlerin, analizlerin ve isteklerin tek bir JSON dosyasında. Anahtarların dosyaya girmez.</p>
            <K.Button variant="secondary" icon={<K.Icon name="download" size={18} />} onClick={download}>Verilerimi indir</K.Button>
            <p className="kp-note"><a href="/gizlilik" className="kp-link">Gizlilik ve KVKK</a></p>
          </K.Card>
          {owner ? (
            <K.Card title="Hesap silme"><p className="kp-note" style={{ margin: 0 }}>Sistem sahibinin hesabı panelden silinmez; bot bu hesaba bağlı.</p></K.Card>
          ) : <K.DangerZone onDelete={remove} />}
          <K.Button variant="ghost" icon={<K.Icon name="logout" size={18} />} onClick={logout}>Çıkış yap</K.Button>
        </div>
      </div>
    </div>
  );
}
