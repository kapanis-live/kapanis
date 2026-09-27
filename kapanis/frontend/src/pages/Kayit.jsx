import { SignIn, SignUp } from "@clerk/react";
import { K } from "@/ds";

// Clerk giriş ve kayıt kutuları: Google ile giriş, e-posta + şifre, e-postaya gelen doğrulama kodu.
// Şifre ve kod Clerk'te işlenir; Kapanış yalnız doğrulanmış e-postayı görür.
function Frame({ children, tag }) {
  return (
    <div className="kp-login">
      <div className="kp-login__box">
        <div className="kp-login__brand">
          <K.BrandMark size="lg" />
          <p className="kp-login__tag">{tag}</p>
        </div>
        <div className="flex justify-center">{children}</div>
        <p className="kp-login__foot">Bot işlem yapmaz · broker ya da borsa şifresi istenmez</p>
        <K.Disclaimer />
      </div>
    </div>
  );
}

export function ClerkSignIn() {
  return (
    <Frame tag="Sadece kapanış konuşur.">
      <SignIn routing="path" path="/giris" signUpUrl="/kayit" fallbackRedirectUrl="/app" />
    </Frame>
  );
}

export default function Kayit() {
  return (
    <Frame tag="Hesap aç: Google ile ya da e-posta ve doğrulama koduyla.">
      <SignUp routing="path" path="/kayit" signInUrl="/giris" fallbackRedirectUrl="/app" />
    </Frame>
  );
}
