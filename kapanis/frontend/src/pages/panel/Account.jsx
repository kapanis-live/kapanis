import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useClerk } from "@clerk/react";
import { K } from "@/ds";
import { useAuth } from "@/context/AuthContext";
import { useData } from "@/lib/useData";
import api, { formatApiErrorDetail } from "@/lib/api";

// Clerk hesabında e-posta, şifre ve Google bağlantısı Clerk'in kendi penceresinden yönetilir.
function ClerkProfileButton() {
  const clerk = useClerk();
  return <K.Button variant="ghost" onClick={() => clerk.openUserProfile()}>Hesap ayarları</K.Button>;
}

function TelegramCard() {
  const qc = useQueryClient();
  const st = useData("tg-status", "/telegram/status", { refetchInterval: 5000 });
  const cfg = useData("auth-config", "/auth/config");
  const [code, setCode] = useState(null);
  const bot = cfg.data?.telegram_bot;
  const linked = st.data?.bagli;

  const newCode = async () => {
    try {
      const { data } = await api.post("/telegram/link-code");
      setCode(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Kod alınamadı.");
    }
  };
  const unlink = async () => {
    await api.delete("/telegram/link");
    setCode(null);
    qc.invalidateQueries({ queryKey: ["tg-status"] });
    toast.success("Telegram bağlantısı kaldırıldı.");
  };

  return (
    <K.Card title="Telegram" actions={<span className={`kp-alarm__status ${linked ? "is-up" : "is-flat"}`}>{linked ? "Bağlı" : "Bağlı değil"}</span>}>
      {linked ? (
        <>
          <p className="text-[0.9375rem] text-t-1">Siteden istediğin analizler Telegram'a da gelir{st.data?.kullanici_adi ? ` (@${st.data.kullanici_adi})` : ""}.</p>
          <div className="mt-3"><K.Button variant="ghost" onClick={unlink}>Bağlantıyı kaldır</K.Button></div>
        </>
      ) : code ? (
        <div className="flex flex-col gap-3">
          <p className="text-[0.9375rem] text-t-1">
            {bot ? <>Telegram'da <a className="font-semibold text-info underline" href={`https://t.me/${bot}`} target="_blank" rel="noreferrer">@{bot}</a> botunu aç ve şunu yaz:</> : "Kapanış botuna şunu yaz:"}
          </p>
          <code className="num w-fit rounded-lg border border-strong bg-ink px-4 py-2 text-lg font-bold text-t-1">/bagla {code.kod}</code>
          <p className="kp-note">Kod {code.dakika} dakika geçerli ve tek kullanımlık. Bağlanınca bu kart kendiliğinden yenilenir.</p>
        </div>
      ) : (
        <>
          <p className="text-[0.9375rem] text-t-2">Bağlamazsan analizler yalnız sitede görünür. Bağlarsan aynı analiz Telegram'dan da gelir.</p>
          <div className="mt-3"><K.Button variant="primary" onClick={newCode}>Telegram'ı bağla</K.Button></div>
        </>
      )}
    </K.Card>
  );
}


const KEY_HELP = {
  deepseek: { url: "https://platform.deepseek.com/api_keys", note: "Ücretli; kullandığın kadar DeepSeek hesabından düşer." },
  nvidia: { url: "https://build.nvidia.com", note: "Kimi K3 ve GLM 5.3; NVIDIA'nın verdiği ücretsiz kredilerle çalışır." },
};

// Kullanıcının kendi yapay zekâ anahtarları: sunucuda şifreli saklanır, buraya yalnız son 4 hanesi gelir.
function AiKeysCard() {
  const qc = useQueryClient();
  const q = useData("ai-keys", "/ai-keys");
  const { refresh } = useAuth();
  const [draft, setDraft] = useState({ deepseek: "", nvidia: "" });
  const [busy, setBusy] = useState("");
  const d = q.data;
  const after = () => {
    qc.invalidateQueries({ queryKey: ["ai-keys"] });
    refresh?.();
  };
  const save = async (prov) => {
    setBusy(prov);
    try {
      await api.put("/ai-keys", { saglayici: prov, anahtar: draft[prov].trim() });
      toast.success(`${d.etiketler[prov]} anahtarın doğrulandı ve şifreli kaydedildi.`);
      setDraft({ ...draft, [prov]: "" });
      after();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Kaydedilemedi.");
    } finally {
      setBusy("");
    }
  };
  const remove = async (prov) => {
    await api.delete(`/ai-keys/${prov}`);
    toast.success("Anahtar silindi.");
    after();
  };
  if (!d) return null;
  return (
    <K.Card title="Yapay zekâ anahtarların" actions={<span className="kp-alarm__status is-flat">İsteğe bağlı</span>}>
      <p className="text-[0.9375rem] text-t-2">
        Kendi anahtarını girersen analizlerin senin hesabından çalışır ve günlük hakkın artar. Girmezsen sitenin ortak,
        sınırlı hakkını kullanırsın. Anahtar sunucuda şifreli saklanır, yalnız analiz sırasında kullanılır ve ekranda bir daha tam gösterilmez.
      </p>
      {!d.sifreleme && <K.Callout tone="warn" title="Şu an kaydedilemiyor">Sunucuda anahtar şifreleme ayarlı değil.</K.Callout>}
      <div className="mt-4 flex flex-col gap-4">
        {Object.keys(d.etiketler).map((prov) => {
          const saved = d.anahtarlar[prov];
          return (
            <div key={prov} className="rounded-xl border border-hairline p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <b className="text-t-1">{d.etiketler[prov]}</b>
                {saved ? <span className="num text-[0.9375rem] text-t-2">kayıtlı {saved.maske}</span> : <span className="text-[0.9375rem] text-t-3">yok</span>}
              </div>
              <p className="kp-note m-0 mt-1">{KEY_HELP[prov].note} Anahtarı <a className="text-info underline" href={KEY_HELP[prov].url} target="_blank" rel="noreferrer">buradan</a> alırsın.</p>
              <div className="mt-3 flex flex-wrap items-end gap-2">
                <div className="min-w-[16rem] flex-1">
                  <K.TextInput type="password" autoComplete="off" value={draft[prov]} placeholder={saved ? "yenisini yapıştır" : "anahtarı yapıştır"}
                    onChange={(e) => setDraft({ ...draft, [prov]: e.target.value })} />
                </div>
                <K.Button variant="primary" disabled={!draft[prov].trim() || busy === prov || !d.sifreleme} onClick={() => save(prov)}>
                  {busy === prov ? "Doğrulanıyor…" : "Kaydet"}
                </K.Button>
                {saved && <K.Button variant="ghost" onClick={() => remove(prov)}>Sil</K.Button>}
              </div>
            </div>
          );
        })}
      </div>
    </K.Card>
  );
}

// KVKK / GDPR: verileri indirme ve hesabı silme
function DataCard({ owner, logout }) {
  const [confirm, setConfirm] = useState("");
  const download = async () => {
    try {
      const { data } = await api.get("/account/export");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: "kapanis-verilerim.json" });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "İndirilemedi.");
    }
  };
  const remove = async () => {
    try {
      await api.delete("/account");
      toast.success("Hesabın ve verilerin silindi.");
      await logout();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail) || "Silinemedi.");
    }
  };
  return (
    <K.Card title="Verilerin">
      <p className="text-[0.9375rem] text-t-2">Kapanış'ın senin hakkında tuttuğu her şeyi indirebilir ya da hesabını tamamen silebilirsin. Ayrıntı: <a className="text-info underline" href="/gizlilik">Gizlilik</a>.</p>
      <div className="mt-3"><K.Button variant="ghost" onClick={download}>Verilerimi indir</K.Button></div>
      {!owner && (
        <div className="mt-5 rounded-xl border border-down/40 p-4">
          <b className="text-down">Hesabımı sil</b>
          <p className="kp-note m-0 mt-1">Portföyün, analizlerin, Telegram bağlantın, API anahtarların ve giriş hesabın silinir. Geri alınamaz. Onaylamak için SİL yaz.</p>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <K.TextInput value={confirm} placeholder="SİL" onChange={(e) => setConfirm(e.target.value)} />
            <K.Button variant="ghost" disabled={confirm.trim().toLocaleUpperCase("tr-TR") !== "SİL"} onClick={remove}>Hesabımı kalıcı olarak sil</K.Button>
          </div>
        </div>
      )}
    </K.Card>
  );
}

export default function Account() {
  const { user, mode, owner, logout } = useAuth();
  return (
    <div className="kp-page">
      <K.PageHeader controls={false} title="Hesap" subtitle="Giriş bilgilerin ve Telegram bağlantın." />
      <K.Card title="Oturum" actions={mode === "clerk" ? <ClerkProfileButton /> : null}>
        <div className="kp-grid kp-g-3">
          <div className="rounded-xl border border-hairline p-5">
            <p className="kp-field__label m-0">E-posta</p>
            <p className="m-0 mt-2 break-all text-lg font-bold text-t-1">{user?.email || "—"}</p>
          </div>
          <K.StatCard label="Rol" value={owner ? "Sistem sahibi" : "Kullanıcı"} sub={owner ? "botun portföyü ve sinyalleri sende" : "kendi portföyün ve analizlerin"} />
          <K.StatCard label="Giriş" value={mode === "clerk" ? "Clerk" : "Bu bilgisayar"} sub={mode === "clerk" ? "Google ya da e-posta + kod" : "yönetici şifresi"} />
        </div>
        <div className="mt-4"><K.Button variant="ghost" onClick={logout}>Çıkış yap</K.Button></div>
      </K.Card>
      <TelegramCard />
      {!owner && <AiKeysCard />}
      <DataCard owner={owner} logout={logout} />
      <p className="kp-note">Kapanış broker ya da borsa şifresi istemez, işlem yapmaz.{mode === "clerk" ? " Şifren Kapanış'ta değil, giriş servisinde (Clerk) saklanır." : ""}</p>
    </div>
  );
}
