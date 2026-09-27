# Kapanış

Kişisel, Türkçe karar destek sistemi: kripto (yalnız spot), BIST (orta/uzun vade) ve ABD hisseleri.
**Hiç işlem yapmaz.** Sayıları kod hesaplar, yapay zekâ yalnız açıklar; sinyaller yalnız mum kapanışıyla sayılır.

```
kapanis/                 (bu depo, masaüstündeki düzenin aynısı)
├── kriptografikbotu/    Telegram botu (Python): kurallar, alarmlar, zamanlanmış işler, yapay zekâ
├── kapanis/             Web paneli: backend (FastAPI + MongoDB, port 8001) + frontend (React)
├── KAPANIS-BASLAT.bat   hepsini başlatır (MongoDB, panel API, bot)
└── KAPANIS-DURDUR.bat   hepsini durdurur
```

Ayrıntılı yapı: `kriptografikbotu/PROJE_YAPISI.md` · modüller: `kriptografikbotu/PROJE.md`.

## Kurulum (yeni bilgisayar)

1. Klasörü masaüstüne koy (başlatma dosyaları `Desktop\kriptografikbotu` ve `Desktop\kapanis` yollarını kullanır).
2. Anahtarlar depoda **yok**. `.env` dosyalarını elle oluştur:
   - `kriptografikbotu/.env` → `kriptografikbotu/.env.example`'a bak (Telegram, DeepSeek, NVIDIA, Tiingo, FRED...).
   - `kapanis/backend/.env` → `MONGO_URL, DB_NAME, JWT_SECRET, BOT_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, CORS_ORIGINS`.
   - `BOT_API_KEY` iki dosyada aynı olmalı.
3. Python 3.11, Node 24, MongoDB. Bot: `pip install -r kriptografikbotu/requirements.txt`; panel: `kapanis/backend/requirements.txt`,
   `kapanis/frontend` içinde `npm install --legacy-peer-deps` ve `npx craco build`.
4. `KAPANIS-BASLAT.bat`.

Telefon: Tailscale + `kriptografikbotu/mobil-panel.ps1` (panel yalnız kendi Tailscale ağında HTTPS ile açılır).

**Bulut (bilgisayar kapalıyken çalışsın, herkes hesap açabilsin):** `BULUT_KURULUM.md` — Clerk girişi (Google, e-posta + kod), MongoDB Atlas (Frankfurt), Render ya da Linux VPS (Docker).

Yatırım tavsiyesi değildir.
