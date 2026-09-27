import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LoadingState } from "@/components/states";

// owner: yalnız sistem sahibinin sayfası (botun portföyü, sinyalleri...); diğer kullanıcılar kendi portföyüne gider
export function ProtectedRoute({ children, owner = false }) {
  const { user, owner: isOwner } = useAuth();
  if (user === null) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-ink">
        <LoadingState text="Oturum kontrol ediliyor…" testid="auth-checking" />
      </div>
    );
  }
  if (user === false) {
    return <Navigate to="/giris" replace />;
  }
  if (owner && !isOwner) {
    return <Navigate to="/app/portfoyum" replace />;
  }
  return children;
}
