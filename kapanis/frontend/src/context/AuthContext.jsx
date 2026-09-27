import { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { ClerkProvider, useAuth as useClerkAuth, useClerk } from "@clerk/react";
import { trTR } from "@clerk/localizations";
import api, { API, formatApiErrorDetail } from "@/lib/api";
import { LoadingState } from "@/components/states";
import { setLiveTokenGetter } from "@/lib/live";

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
// legacy: AUTH_MODE=both, the local admin password also works (its session is an HttpOnly cookie)
function ClerkBridge({ children, legacy }) {
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
    setLiveTokenGetter(() => tokenRef.current?.());
    return () => {
      api.interceptors.request.eject(id);
      setLiveTokenGetter(null);
    };
  }, []);

  const refresh = useCallback(async () => {
    if (!isLoaded) return;
    if (!isSignedIn) {
      if (legacy) {
        try {
          const { data } = await api.get("/auth/me"); // the local admin cookie, if any
          setUser(data);
          return;
        } catch {
          /* no local session either */
        }
      }
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
  }, [isLoaded, isSignedIn, legacy]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const logout = async () => {
    if (isSignedIn) await clerk.signOut();
    if (legacy) await api.post("/auth/logout").catch(() => {});
    setUser(false);
  };

  const login = legacy ? async (email, password) => {
    try {
      const { data } = await api.post("/auth/login", { email, password });
      setUser(data);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: formatApiErrorDetail(e.response?.data?.detail) || e.message };
    }
  } : undefined;

  return (
    <AuthContext.Provider value={{ mode: "clerk", legacy: !!legacy, user: isLoaded ? user : null, owner: isOwner(user), error, logout, login, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

function ClerkAuthProvider({ publishableKey, legacy, children }) {
  const navigate = useNavigate();
  return (
    <ClerkProvider publishableKey={publishableKey} localization={trTR}
      routerPush={(to) => navigate(to)} routerReplace={(to) => navigate(to, { replace: true })}
      signInUrl="/giris" signUpUrl="/kayit" signInFallbackRedirectUrl="/app" signUpFallbackRedirectUrl="/app" afterSignOutUrl="/">
      <ClerkBridge legacy={legacy}>{children}</ClerkBridge>
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
    return <ClerkAuthProvider publishableKey={cfg.clerk_publishable_key} legacy={cfg.legacy}>{children}</ClerkAuthProvider>;
  }
  return <LegacyAuthProvider>{children}</LegacyAuthProvider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
