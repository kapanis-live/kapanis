import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Logo } from "@/components/Logo";
import { Disclaimer } from "@/components/Disclaimer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, ArrowLeft } from "lucide-react";

export default function Giris() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
    <div className="flex min-h-screen flex-col bg-ink text-t-1">
      <header className="border-b border-hairline">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
          <Link to="/"><Logo /></Link>
          <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-t-2 transition-colors duration-150 hover:text-t-1" data-testid="back-home-link">
            <ArrowLeft className="h-4 w-4" /> Siteye dön
          </Link>
        </div>
      </header>

      <div className="flex flex-1 items-center justify-center px-5 py-12">
        <div className="w-full max-w-sm animate-fade-up">
          <h1 className="text-2xl font-bold tracking-tight">Panele giriş</h1>
          <p className="mt-1 text-sm text-t-2">Kurala bağlı karar akışına eriş.</p>

          <form onSubmit={submit} className="mt-8 space-y-4" data-testid="login-form">
            <div className="space-y-1.5">
              <Label htmlFor="email" className="text-t-2">E-posta</Label>
              <Input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@kapanis.io"
                data-testid="login-email-input"
                className="bg-surface border-hairline text-t-1 placeholder:text-t-3"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="text-t-2">Şifre</Label>
              <Input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                data-testid="login-password-input"
                className="bg-surface border-hairline text-t-1 placeholder:text-t-3"
              />
            </div>

            {error && (
              <div data-testid="login-error" className="rounded-md border border-down/40 bg-down/10 px-3 py-2 text-sm text-down">
                {error}
              </div>
            )}

            <Button type="submit" disabled={loading} className="w-full" data-testid="login-submit-btn">
              {loading ? <><Loader2 className="h-4 w-4 animate-spin" /> Giriş yapılıyor…</> : "Giriş yap"}
            </Button>
          </form>

          <p className="mt-6 text-xs text-t-3">
            Kayıt ekranı yoktur; erişim tek yönetici hesabıyla sağlanır. 5 hatalı denemeden sonra hesap 15 dakika kilitlenir.
          </p>

          <div className="mt-10">
            <Disclaimer />
          </div>
        </div>
      </div>
    </div>
  );
}
