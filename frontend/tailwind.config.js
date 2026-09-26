/** @type {import('tailwindcss').Config} */
module.exports = {
  blocklist: ["overline"],
  darkMode: ["class"],
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./public/index.html"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        // Kapanış tasarım sistemi (CSS değişkenleri: koyu varsayılan, .light açık tema)
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        side: "rgb(var(--c-side) / <alpha-value>)",
        surface: "rgb(var(--c-surface) / <alpha-value>)",
        raised: "rgb(var(--c-raised) / <alpha-value>)",
        hairline: "rgb(var(--c-hairline) / <alpha-value>)",
        strong: "rgb(var(--c-strong) / <alpha-value>)",
        grid: "rgb(var(--c-grid) / <alpha-value>)",
        "on-brand": "rgb(var(--c-on-brand) / <alpha-value>)",
        rsi: "rgb(var(--c-rsi) / <alpha-value>)",
        "t-1": "rgb(var(--c-t1) / <alpha-value>)",
        "t-2": "rgb(var(--c-t2) / <alpha-value>)",
        "t-3": "rgb(var(--c-t3) / <alpha-value>)",
        up: "rgb(var(--c-up) / <alpha-value>)",
        down: "rgb(var(--c-down) / <alpha-value>)",
        wait: "rgb(var(--c-wait) / <alpha-value>)",
        info: "rgb(var(--c-info) / <alpha-value>)",
        brand: "rgb(var(--c-brand) / <alpha-value>)",
        violet: "rgb(var(--c-violet) / <alpha-value>)",
        sma20: "#F5C518",
        sma50: "#2196F3",
        sma200: "#E040FB",
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
        "fade-up": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "msg-in": { from: { opacity: "0", transform: "translateY(10px) scale(0.98)" }, to: { opacity: "1", transform: "translateY(0) scale(1)" } },
        blink: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.25" } },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-up": "fade-up 0.24s ease-out both",
        "fade-in": "fade-in 0.18s ease-out both",
        "msg-in": "msg-in 0.24s ease-out both",
        blink: "blink 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
