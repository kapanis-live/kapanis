import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { K } from "@/ds";
import { useAuth } from "@/context/AuthContext";

// Tasarım sistemindeki giriş ekranı: logo, "Sadece kapanış konuşur.", e-posta + şifre (Göster/Gizle)
export default function Giris() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    const res = await login(email.trim(), password);
    setLoading(false);
    if (res.ok) navigate("/app");
    else setError(res.error);
  };

  return (
    <div className="kp-login">
      <div className="kp-login__box">
        <div className="kp-login__brand">
          <K.BrandMark size="lg" />
          <p className="kp-login__tag">Sadece kapanış konuşur.</p>
        </div>
        <form className="kp-card kp-login__form" onSubmit={submit} data-testid="login-form">
          <K.Field label="E-posta">
            <K.TextInput type="email" name="email" autoComplete="email" required placeholder="ornek@eposta.com"
              value={email} onChange={(e) => setEmail(e.target.value)} data-testid="login-email-input" />
          </K.Field>
          <K.Field label="Şifre" error={error || undefined}>
            <K.TextInput type={show ? "text" : "password"} name="password" autoComplete="current-password" required placeholder="••••••••"
              value={password} onChange={(e) => setPassword(e.target.value)} data-testid="login-password-input"
              suffix={<K.Button variant="ghost" aria-label={show ? "Şifreyi gizle" : "Şifreyi göster"} onClick={() => setShow(!show)}>{show ? "Gizle" : "Göster"}</K.Button>} />
          </K.Field>
          <K.Button variant="primary" type="submit" disabled={loading} data-testid="login-submit-btn">{loading ? "Giriş yapılıyor..." : "Giriş yap"}</K.Button>
        </form>
        <p className="kp-login__foot">Kişisel panel · tek kullanıcı</p>
        <K.Disclaimer />
      </div>
    </div>
  );
}
