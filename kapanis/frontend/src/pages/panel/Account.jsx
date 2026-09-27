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
      <p className="kp-note">Kapanış broker ya da borsa şifresi istemez, işlem yapmaz.{mode === "clerk" ? " Şifren Kapanış'ta değil, giriş servisinde (Clerk) saklanır." : ""}</p>
    </div>
  );
}
