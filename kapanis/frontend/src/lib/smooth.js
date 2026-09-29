import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

// Menüde üstüne gelince / dokununca sayfanın ana verisi önceden yüklenir: tıklayınca beklemeden açılır.
const ROUTE_DATA = {
  "/app": [["overview", "/overview"]],
  "/app/portfoyum": [["my-portfolio", "/portfolio"], ["my-quotes", "/portfolio/quotes"]],
  "/app/analizlerim": [["my-analyses", "/analyses"]],
  "/app/stratejiler": [["trend-board", "/strategies/trend"], ["strategy-lab", "/strategies/lab"]],
  "/app/alarmlarim": [["my-alarms", "/alarms"]],
  "/app/karnem": [["karne", "/karne"]],
  "/app/saglik": [["health", "/portfolio/health"], ["market-regime", "/market/regime"]],
  "/app/kriz": [["my-portfolio", "/portfolio"], ["risk-proposal", "/risk/proposals/latest"]],
  "/app/makro": [["macro", "/macro"]],
  "/app/vadeli": [["derivatives", "/derivatives"]],
  "/app/alarmlar": [["alerts", "/alerts"]],
  "/app/sinyaller": [["signals", "/signals"], ["decisions", "/decisions"]],
  "/app/pozisyonlar": [["positions", "/positions"]],
  "/app/portfoy": [["extras", "/extras"]],
  "/app/takip": [["extras", "/extras"]],
  "/app/planlar": [["firsat", "/firsat"]],
  "/app/rapor": [["report", "/report"]],
  "/app/disiplin": [["report", "/report"]],
  "/app/maliyet": [["usage", "/usage"]],
  "/app/backtest": [["backtest", "/backtest"]],
  "/app/ayarlar": [["settings", "/settings"]],
  "/app/kullanicilar": [["admin-users", "/admin/users"]],
};

export function usePrefetch() {
  const qc = useQueryClient();
  return (to) => {
    for (const [key, path] of ROUTE_DATA[to] || []) {
      qc.prefetchQuery({ queryKey: [key], queryFn: async () => (await api.get(path)).data, staleTime: 20_000 });
    }
  };
}

// Dokunmatik geri bildirim (destekleyen telefonlarda kısa titreşim)
export const haptic = () => { try { navigator.vibrate?.(8); } catch { /* yok */ } };

// Sayfanın en üstündeyken aşağı çekince tüm veriler yenilenir (telefon)
export function usePullToRefresh(ref) {
  const qc = useQueryClient();
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    let startY = null;
    let pulled = 0;
    const hint = document.createElement("div");
    hint.className = "kp-ptr";
    hint.textContent = "↓ Yenilemek için bırak";
    el.prepend(hint);
    const onStart = (e) => { startY = window.scrollY <= 0 ? e.touches[0].clientY : null; };
    const onMove = (e) => {
      if (startY == null) return;
      pulled = Math.max(0, e.touches[0].clientY - startY);
      hint.style.height = `${Math.min(pulled, 90) * 0.6}px`;
      hint.style.opacity = String(Math.min(pulled / 80, 1));
    };
    const onEnd = () => {
      if (startY != null && pulled > 80) { haptic(); qc.invalidateQueries(); }
      startY = null; pulled = 0;
      hint.style.height = "0px"; hint.style.opacity = "0";
    };
    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: true });
    el.addEventListener("touchend", onEnd);
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      hint.remove();
    };
  }, [ref, qc]);
}

// Değişen sayı kısa bir renk parlamasıyla güncellenir ve eski değerden yeniye akar
export function useFlash(value) {
  const prev = useRef(value);
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    const a = Number(prev.current), b = Number(value);
    prev.current = value;
    if (!el || !Number.isFinite(a) || !Number.isFinite(b) || a === b) return;
    el.classList.remove("kp-flash-up", "kp-flash-down");
    void el.offsetWidth; // animasyonu yeniden başlat
    el.classList.add(b > a ? "kp-flash-up" : "kp-flash-down");
  }, [value]);
  return ref;
}
