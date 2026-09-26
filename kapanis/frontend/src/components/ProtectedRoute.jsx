import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { LoadingState } from "@/components/states";

export function ProtectedRoute({ children }) {
  const { user } = useAuth();
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
  return children;
}
