import { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { ClerkProvider, useAuth as useClerkAuth, useClerk } from "@clerk/react";
import { trTR } from "@clerk/localizations";
import api, { API, formatApiErrorDetail } from "@/lib/api";
import { LoadingState } from "@/components/states";

// user: null = kontrol ediliyor, false = giriş yapılmamış, obje = giriş yapılmış ({id, email, role, ...})
// mode: "legacy" (bu bilgisayardaki tek yönetici şifresi) ya da "clerk" (Google / e-posta + kod)
const AuthContext = createContext(null);

export const isOwner = (user) => !!user && (user.role === "owner" || user.role === "admin");

function LegacyAuthProvider({ children }) {
  const [user, setUser] = useState(null);

  const checkSession = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      setUser(false);
    }
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  const login = async (email, password) => {
    try {
      const { data } = await api.post("/auth/login", { email, password });
      setUser(data);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* yoksay */
    }
    setUser(false);
  };

  return (
    <AuthContext.Provider value={{ mode: "legacy", user, owner: isOwner(user), login, logout, refresh: checkSession }}>
      {children}
    </AuthContext.Provider>
  );
}

// Clerk oturumu: her API isteğine Clerk'in kısa ömürlü oturum jetonu eklenir; backend imzayı ve doğrulanmış
// e-postayı kontrol edip kullanıcıyı ve rolünü döner. Şifreler Kapanış'ta değil, Clerk'te.
function ClerkBridge({ children }) {
  const { isLoaded, isSignedIn, getToken } = useClerkAuth();
  const clerk = useClerk();
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");
  const tokenRef = useRef(getToken);
  tokenRef.current = getToken;

  useEffect(() => {
    const id = api.interceptors.request.use(async (cfg) => {
      const t = await tokenRef.current?.();
      if (t) cfg.headers.Authorization = `Bearer ${t}`;
      return cfg;
    });
    return () => api.interceptors.request.eject(id);
  }, []);

  const refresh = useCallback(async () => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      setUser(false);
      return;
    }
    try {
      const { data } = await api.get("/auth/me");
      setError("");
      setUser(data);
    } catch (e) {
      setError(formatApiErrorDetail(e.response?.data?.detail) || "Oturum doğrulanamadı.");
      setUser(false);
    }
  }, [isLoaded, isSignedIn]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const logout = async () => {
    await clerk.signOut();
    setUser(false);
  };

  return (
    <AuthContext.Provider value={{ mode: "clerk", user: isLoaded ? user : null, owner: isOwner(user), error, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

function ClerkAuthProvider({ publishableKey, children }) {
  const navigate = useNavigate();
  return (
    <ClerkProvider publishableKey={publishableKey} localization={trTR}
      routerPush={(to) => navigate(to)} routerReplace={(to) => navigate(to, { replace: true })}
      signInUrl="/giris" signUpUrl="/kayit" signInFallbackRedirectUrl="/app" signUpFallbackRedirectUrl="/app" afterSignOutUrl="/">
      <ClerkBridge>{children}</ClerkBridge>
    </ClerkProvider>
  );
}

// Hangi giriş kullanılacağını sunucu söyler (/api/auth/config), böylece aynı derleme hem bu bilgisayarda hem bulutta çalışır.
export function AuthProvider({ children }) {
  const [cfg, setCfg] = useState(null);
  useEffect(() => {
    fetch(`${API}/auth/config`).then((r) => r.json()).then(setCfg).catch(() => setCfg({ clerk: false, legacy: true }));
  }, []);
  if (!cfg) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink">
        <LoadingState text="Yükleniyor…" />
      </div>
    );
  }
  if (cfg.clerk && cfg.clerk_publishable_key) {
    return <ClerkAuthProvider publishableKey={cfg.clerk_publishable_key}>{children}</ClerkAuthProvider>;
  }
  return <LegacyAuthProvider>{children}</LegacyAuthProvider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
