import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { PanelLayout } from "@/components/PanelLayout";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider, useTheme } from "@/lib/theme";
import { LangProvider } from "@/lib/i18n";

import Iletisim from "@/pages/public/Iletisim";
import Gizlilik from "@/pages/public/Gizlilik";
import { Home, Features, How, Rules, Faq, SitePage, Terms, NotFound } from "@/pages/public/site";
import Users from "@/pages/panel/Users";
import Giris from "@/pages/Giris";
import Kayit from "@/pages/Kayit";
import MyPortfolio from "@/pages/panel/MyPortfolio";
import MyAnalyses from "@/pages/panel/MyAnalyses";
import Strategies from "@/pages/panel/Strategies";
import MyAlerts from "@/pages/panel/MyAlerts";
import MyReport from "@/pages/panel/MyReport";
import PortfolioHealth from "@/pages/panel/PortfolioHealth";
import Crisis from "@/pages/panel/Crisis";
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
import UsCard from "@/pages/panel/UsCard";
import CompanyCalendar from "@/pages/panel/CompanyCalendar";
import Screener from "@/pages/panel/Screener";
import Portfolio from "@/pages/panel/Portfolio";
import Watchlist from "@/pages/panel/Watchlist";
import Discipline from "@/pages/panel/Discipline";
import ChartPage from "@/pages/panel/Chart";
import Plans from "@/pages/panel/Plans";
import Tools from "@/pages/panel/Tools";
import Advisor from "@/pages/panel/Advisor";
import AdminAdvisor from "@/pages/panel/AdminAdvisor";

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
      <LangProvider>
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/ozellikler" element={<Features />} />
          <Route path="/nasil-calisir" element={<How />} />
          <Route path="/kurallar" element={<Rules />} />
          <Route path="/sss" element={<Faq />} />
          <Route path="/iletisim" element={<SitePage><Iletisim /></SitePage>} />
          <Route path="/gizlilik" element={<SitePage><Gizlilik /></SitePage>} />
          <Route path="/kvkk" element={<Navigate to="/gizlilik" replace />} />
          <Route path="/kosullar" element={<Terms />} />
          <Route path="/giris/*" element={<Giris />} />
          <Route path="/kayit/*" element={<Kayit />} />

          <Route path="/app" element={panel(<Home0 />)} />
          <Route path="/app/portfoyum" element={panel(<MyPortfolio />)} />
          <Route path="/app/analizlerim" element={panel(<MyAnalyses />)} />
          <Route path="/app/stratejiler" element={panel(<Strategies />)} />
          <Route path="/app/alarmlarim" element={panel(<MyAlerts />)} />
          <Route path="/app/karnem" element={panel(<MyReport />)} />
          <Route path="/app/saglik" element={panel(<PortfolioHealth />)} />
          <Route path="/app/kriz" element={panel(<Crisis />)} />
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
          <Route path="/app/danisman" element={own(<Advisor />)} />
          {/* yalnız yönetici: asıl yetki sunucuda (/api/admin/advisor/*) denetlenir */}
          <Route path="/admin/advisor" element={own(<AdminAdvisor />)} />
          <Route path="/app/rapor" element={own(<Report />)} />
          <Route path="/app/maliyet" element={own(<Cost />)} />
          <Route path="/app/backtest" element={own(<Backtest />)} />
          <Route path="/app/ayarlar" element={own(<Settings />)} />
          <Route path="/app/abd" element={panel(<UsCard />)} />
          <Route path="/app/hisse" element={panel(<UsCard />)} />
          <Route path="/app/tarama" element={own(<Screener />)} />
          <Route path="/app/takvim" element={own(<CompanyCalendar />)} />
          <Route path="/app/kullanicilar" element={own(<Users />)} />

          <Route path="*" element={<NotFound />} />
        </Routes>
      </AuthProvider>
      <ThemedToaster />
    </BrowserRouter>
      </LangProvider>
    </ThemeProvider>
  );
}

export default App;
