import { createContext, createElement, useContext, useEffect, useState } from "react";

// Koyu tema varsayılan; açık tema <html class="light"> ile. Seçim tarayıcıda hatırlanır.
const KEY = "kapanis-theme";

// Grafik kütüphaneleri CSS değişkeni okuyamadığı için renkler burada da tutulur (index.css ile aynı).
const CHART = {
  dark: {
    grid: "#1c222c", axis: "#7c8797", text: "#aab4c3", line: "#f5f7fa", sep: "#252c38", tooltipBg: "#0f1217", tooltipBorder: "#252c38",
    up: "#1fd67a", down: "#ff4d5e", wait: "#ffb020", info: "#4da3ff", brand: "#2dd4bf", violet: "#c084fc", onSignal: "#050608",
    sma20: "#ffb020", sma50: "#4da3ff", sma200: "#c084fc", vwap: "#2dd4bf", rsi: "#ff9f43",
  },
  light: {
    grid: "#eceef2", axis: "#636b7a", text: "#4a5261", line: "#0b0d12", sep: "#e2e5ea", tooltipBg: "#ffffff", tooltipBorder: "#e2e5ea",
    up: "#0f9d58", down: "#e5383b", wait: "#9a5b00", info: "#1d6fd1", brand: "#0b7c70", violet: "#8b3fd9", onSignal: "#ffffff",
    sma20: "#d48a00", sma50: "#1d6fd1", sma200: "#8b3fd9", vwap: "#0b7c70", rsi: "#c96a10",
  },
};

function readTheme() {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

// Yazı boyutu: bütün ölçüler rem olduğu için kök yazı boyutu tüm paneli büyütür/küçültür.
const SIZE_KEY = "kapanis-font-v2";
export const FONT_SIZES = [15, 16, 17, 18, 20];
const DEFAULT_SIZE = 1;

const ThemeContext = createContext({ theme: "dark", toggle: () => {}, colors: CHART.dark, size: DEFAULT_SIZE, setSize: () => {} });

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(readTheme);
  const [size, setSize] = useState(DEFAULT_SIZE);   // A−/A+ kaldırıldı: tarayıcı yakınlaştırması aynı işi görür
  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
    document.documentElement.setAttribute("data-theme", theme); // tasarım sistemi değişkenleri
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* depolama kapalıysa tema yalnız bu oturumda geçerli */
    }
  }, [theme]);
  useEffect(() => {
    document.documentElement.style.fontSize = `${FONT_SIZES[size]}px`;
    try {
      localStorage.setItem(SIZE_KEY, String(size));
    } catch {
      /* yalnız bu oturumda */
    }
  }, [size]);
  const value = {
    theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")), colors: CHART[theme],
    size, setSize: (i) => setSize(Math.max(0, Math.min(FONT_SIZES.length - 1, i))),
  };
  return createElement(ThemeContext.Provider, { value }, children);
}

export const useTheme = () => useContext(ThemeContext);
