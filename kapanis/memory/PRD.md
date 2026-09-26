# Kapanış — PRD

## Orijinal problem
Türkçe, siyah temalı bir işlem sinyali platformu. İki bölüm:
1. Halka açık tanıtım sitesi: `/`, `/ozellikler`, `/nasil-calisir`, `/kurallar`, `/sss`, `/iletisim`
2. Giriş gerektiren panel: `/app/...` (10 sayfa)
Slogan: "Dokunma değil, kapanış." Hero'da gerçekçi Telegram mockup'ı (grafik → KARAR → Aldım/Pas).

## Kullanıcı tercihleri (bu oturumda alınan)
- Auth: JWT e-posta/şifre, kayıt yok, tek admin seed (.env), access 1s, refresh 30g httpOnly cookie, 5 hatalı denemede 15dk kilit.
- Backend: FastAPI + MongoDB, tüm uç noktalar mock veriyle. Bot için X-Bot-Key ile ingest + commands kuyruğu. Goalpost kuralı backend'de 409.
- Panel sayfaları: Genel Bakış, Alarmlar, Sinyaller & Analiz, Pozisyonlar, Rapor, Makro (takvim dahil), Maliyet, Vadeli, Backtest, Ayarlar.
- Tasarım: #000 arka plan, #0A0A0A kart, #1F1F1F kenarlık, metin #EDEDED/#8A8A8A/#555555, up #26A69A, down #EF5350, wait #F5C518, info #2196F3, SMA20/50/200. Inter + JetBrains Mono (tabular-nums). Sayı biçimi 84 350.25. Neon/gradient/glassmorphism yok.

## Mimari
- Frontend: React (CRA + craco), react-router, react-query, framer-motion, recharts, shadcn/ui. `@` alias = src.
- Backend: FastAPI, motor (MongoDB), PyJWT, bcrypt. Tüm rotalar `/api` prefixli.
- Auth cookie tabanlı (Bearer fallback). Brute force IP'si X-Forwarded-For'dan alınır.
- Panel işlemleri veriyi değiştirmez; `commands` koleksiyonuna `pending` yazılır, UI'da "Bota iletildi" rozeti. Bot `/api/ingest/{collection}` ile günceller, `/api/commands/{id}/done` ile kapatır.

## Uygulanan (2026-06-12)
- 6 halka açık sayfa + `/giris` + 10 panel sayfası, tümü çalışıyor.
- JWT auth (seed admin, brute force 429, refresh, logout) — test edildi.
- Tüm panel veri uç noktaları + candles + commands + bot ingest (X-Bot-Key) — test edildi.
- Goalpost 409, canlı R/R renkleri, stop düşürünce buton pasif, Aldım/Pas kuyruğu, makro -5…+5 skala + "klasik DXY değil" + bayat veri rozeti, 24s tarife şeridi.
- Logo: iki çizgi arasından geçen ok (SVG). Boş/yükleniyor/hata Türkçe metinleri. Her sayfada yasal uyarı.
- TypeScript tipleri `src/types/index.ts` (bot JSON'larıyla alan alan aynı) + REST uç nokta listesi.
- Test: backend 43/43, frontend tüm akışlar geçti.

## Backlog / kalan (P1/P2)
- P1: Sinyal detayına derin link (`/app/sinyaller/:id`).
- P1: Bota gerçek bağlanınca react-query invalidation ile rozetlerin otomatik kalkması (polling).
- P2: Ayarlar'da düzenlenebilir risk parametreleri (şu an salt okunur).
- P2: Rapor sayfasına tarih filtresi ve dışa aktarma.

## Test kimlikleri
- admin@kapanis.io / Kapanis2026
- X-Bot-Key: dev-bot-key-2026-secret-change-me
