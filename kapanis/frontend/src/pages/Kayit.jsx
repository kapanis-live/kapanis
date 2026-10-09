import { SignIn, SignUp } from "@clerk/react";
import { K } from "@/ds";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useLang } from "@/lib/i18n";

// Clerk giriş ve kayıt kutuları: Google ile giriş, e-posta + şifre, e-postaya gelen doğrulama kodu.
// Şifre ve kod Clerk'te işlenir; Kapanış yalnız doğrulanmış e-postayı görür.
// Claude Design AuthFrame: logo, slogan, ortada Clerk kutusu, altta "Bot işlem yapmaz · Gizlilik ve KVKK"
function Frame({ children, tag }) {
  const { t } = useLang();
  return <K.AuthFrame tagline={t(tag)}><div className="flex justify-center">{children}</div></K.AuthFrame>;
}

export function ClerkSignIn() {
  return (
    <Frame tag="Sadece kapanış konuşur.">
      <SignIn routing="path" path="/giris" signUpUrl="/kayit" fallbackRedirectUrl="/app" />
    </Frame>
  );
}

export default function Kayit() {
  const { mode } = useAuth();
  // Kayıt yalnız Clerk ile (sitede). Bu bilgisayardaki yerel modda tek yönetici hesabı var.
  if (mode !== "clerk") return <Navigate to="/giris" replace />;
  return (
    <Frame tag="Dokunma değil, kapanış. Google ile ya da e-posta ve doğrulama koduyla hesap aç.">
      <SignUp routing="path" path="/kayit" signInUrl="/giris" fallbackRedirectUrl="/app" />
    </Frame>
  );
}
