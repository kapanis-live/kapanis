import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { PublicLayout } from "@/components/PublicLayout";
import { PanelLayout } from "@/components/PanelLayout";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider, useTheme } from "@/lib/theme";

import Home from "@/pages/public/Home";
import Ozellikler from "@/pages/public/Ozellikler";
import NasilCalisir from "@/pages/public/NasilCalisir";
import Kurallar from "@/pages/public/Kurallar";
import SSS from "@/pages/public/SSS";
import Iletisim from "@/pages/public/Iletisim";
import Giris from "@/pages/Giris";
import Kayit from "@/pages/Kayit";
import MyPortfolio from "@/pages/panel/MyPortfolio";
import Account from "@/pages/panel/Account";
import { useAuth } from "@/context/AuthContext";

import Overview from "@/pages/panel/Overview";
import Alerts from "@/pages/panel/Alerts";
import Signals from "@/pages/panel/Signals";
import Positions from "@/pages/panel/Positions";
import Report from "@/pages/panel/Report";
import Macro from "@/pages/panel/Macro";
import Cost from "@/pages/panel/Cost";
import Derivatives from "@/pages/panel/Derivatives";
import Backtest from "@/pages/panel/Backtest";
import Settings from "@/pages/panel/Settings";
import Portfolio from "@/pages/panel/Portfolio";
import Watchlist from "@/pages/panel/Watchlist";
import Discipline from "@/pages/panel/Discipline";
import ChartPage from "@/pages/panel/Chart";
import Plans from "@/pages/panel/Plans";
import Tools from "@/pages/panel/Tools";

const pub = (el) => <PublicLayout>{el}</PublicLayout>;
// panel(): her giriş yapan; own(): yalnız sistem sahibi (botun kendi verisi)
const panel = (el) => (
  <ProtectedRoute>
    <PanelLayout>{el}</PanelLayout>
  </ProtectedRoute>
);
const own = (el) => (
  <ProtectedRoute owner>
    <PanelLayout>{el}</PanelLayout>
  </ProtectedRoute>
);

function Home0() {
  const { owner } = useAuth();
  return owner ? <Overview /> : <Navigate to="/app/portfoyum" replace />;
}

function ThemedToaster() {
  const { theme } = useTheme();
  return <Toaster position="bottom-right" theme={theme} />;
}

function App() {
  return (
    <ThemeProvider>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={pub(<Home />)} />
          <Route path="/ozellikler" element={pub(<Ozellikler />)} />
          <Route path="/nasil-calisir" element={pub(<NasilCalisir />)} />
          <Route path="/kurallar" element={pub(<Kurallar />)} />
          <Route path="/sss" element={pub(<SSS />)} />
          <Route path="/iletisim" element={pub(<Iletisim />)} />
          <Route path="/giris/*" element={<Giris />} />
          <Route path="/kayit/*" element={<Kayit />} />

          <Route path="/app" element={panel(<Home0 />)} />
          <Route path="/app/portfoyum" element={panel(<MyPortfolio />)} />
          <Route path="/app/hesap" element={panel(<Account />)} />
          <Route path="/app/grafik" element={panel(<ChartPage />)} />
          <Route path="/app/makro" element={panel(<Macro />)} />
          <Route path="/app/vadeli" element={panel(<Derivatives />)} />
          <Route path="/app/alarmlar" element={own(<Alerts />)} />
          <Route path="/app/sinyaller" element={own(<Signals />)} />
          <Route path="/app/pozisyonlar" element={own(<Positions />)} />
          <Route path="/app/portfoy" element={own(<Portfolio />)} />
          <Route path="/app/takip" element={own(<Watchlist />)} />
          <Route path="/app/disiplin" element={own(<Discipline />)} />
          <Route path="/app/planlar" element={own(<Plans />)} />
          <Route path="/app/kontrol" element={own(<Tools />)} />
          <Route path="/app/rapor" element={own(<Report />)} />
          <Route path="/app/maliyet" element={own(<Cost />)} />
          <Route path="/app/backtest" element={own(<Backtest />)} />
          <Route path="/app/ayarlar" element={own(<Settings />)} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
      <ThemedToaster />
    </BrowserRouter>
    </ThemeProvider>
  );
}

export default App;
