import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { PublicLayout } from "@/components/PublicLayout";
import { PanelLayout } from "@/components/PanelLayout";
import { Toaster } from "@/components/ui/sonner";

import Home from "@/pages/public/Home";
import Ozellikler from "@/pages/public/Ozellikler";
import NasilCalisir from "@/pages/public/NasilCalisir";
import Kurallar from "@/pages/public/Kurallar";
import SSS from "@/pages/public/SSS";
import Iletisim from "@/pages/public/Iletisim";
import Giris from "@/pages/Giris";

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

const pub = (el) => <PublicLayout>{el}</PublicLayout>;
const panel = (el) => (
  <ProtectedRoute>
    <PanelLayout>{el}</PanelLayout>
  </ProtectedRoute>
);

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={pub(<Home />)} />
          <Route path="/ozellikler" element={pub(<Ozellikler />)} />
          <Route path="/nasil-calisir" element={pub(<NasilCalisir />)} />
          <Route path="/kurallar" element={pub(<Kurallar />)} />
          <Route path="/sss" element={pub(<SSS />)} />
          <Route path="/iletisim" element={pub(<Iletisim />)} />
          <Route path="/giris" element={<Giris />} />

          <Route path="/app" element={panel(<Overview />)} />
          <Route path="/app/alarmlar" element={panel(<Alerts />)} />
          <Route path="/app/sinyaller" element={panel(<Signals />)} />
          <Route path="/app/pozisyonlar" element={panel(<Positions />)} />
          <Route path="/app/rapor" element={panel(<Report />)} />
          <Route path="/app/makro" element={panel(<Macro />)} />
          <Route path="/app/maliyet" element={panel(<Cost />)} />
          <Route path="/app/vadeli" element={panel(<Derivatives />)} />
          <Route path="/app/backtest" element={panel(<Backtest />)} />
          <Route path="/app/ayarlar" element={panel(<Settings />)} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" theme="dark" />
    </AuthProvider>
  );
}

export default App;
