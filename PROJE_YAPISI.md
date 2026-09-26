# Kapanış — Proje Yapısı (plan için)

Son güncelleme: 26 Eylül 2026. Bu dosya projenin bütün parçalarını tek yerde gösterir. Modüllerin ayrıntılı anlatımı: `PROJE.md`.

---

## 1. Ne yapıyor?

Kişisel, Türkçe bir **karar destek sistemi**: kripto (yalnız spot), BIST (orta/uzun vade) ve ABD hisselerini izler, kurallarla değerlendirir, açıklar. **Hiç işlem yapmaz.**

Temel kurallar:
- **Sayıları kod hesaplar, yapay zekâ yalnız açıklar.** Karar kod kapısından (`gate.py`) çıkar.
- **Kapanış kuralı:** alarm ve sinyaller yalnız mum kapanışıyla tetiklenir, iğne (fitil) sayılmaz.
- **Goalpost yasağı:** açık pozisyonda stop aşağı çekilemez.
- Veri kaynakları ücretsiz; tek ücretli servis DeepSeek. Kimi K3 ve GLM 5.3, NVIDIA'nın ücretsiz kredisiyle çalışır.

---

## 2. İki klasör, üç çalışan parça

```
Desktop\
├── kriptografikbotu\        ← Telegram botu (Python)       GitHub: valenciaennerman-cmd/kapanis-bot (private)
├── kapanis\                 ← Web paneli                    GitHub: valenciaennerman-cmd/kapanis-panel (private)
│   ├── backend\             ← FastAPI + MongoDB (port 8001), paneli de bu sunar
│   └── frontend\            ← React arayüz (derlenmiş hali frontend\build)
├── HİSSEPNGYARATICI\        ← indirilen logo PNG'leri (kaynak; panel kopyasını kullanır)
├── KAPANIS-BASLAT.bat       ← hepsini başlatır
└── KAPANIS-DURDUR.bat       ← hepsini durdurur
```

Çalışırken bilgisayarda üç şey açık olur:

| Parça | Ne yapar | Nerede |
|---|---|---|
| **Bot** (`main.py`) | Telegram komutları, alarmlar, zamanlanmış işler, yapay zekâ | `kriptografikbotu` |
| **Panel API** (`server.py`, uvicorn) | Web paneli ve verisi, `http://localhost:8001` | `kapanis\backend` |
| **MongoDB** (Windows servisi) | Panelin veritabanı | yerel |

### Veri akışı

```
 Binance / Yahoo / Tiingo / SEC / İş Yatırım / FRED / RSS
                 │  (ücretsiz veri)
                 ▼
        ┌──────────────────┐   yapay zekâ (Kimi K3 → DeepSeek → GLM 5.3, 15 dk'da bir sıra)
        │   BOT (main.py)  │◄──────────────────────────────────────────────
        │ kod kapısı, plan │
        └──┬────────────┬──┘
   Telegram│            │ her 1 dk: tüm veri, her 15 dk: "extras" (portföy, takip, disiplin...)
   mesajları│           ▼            POST /api/ingest/...
           │   ┌──────────────────┐
           │   │ PANEL API + Mongo│◄── tarayıcı: http://localhost:8001/app
           │   └────────┬─────────┘
           │            │ panelde basılan düğme → komut kuyruğu (/api/commands)
           │            ▼
           └──── bot 15 sn'de bir kuyruğu okur, uygular, Telegram'a bildirir
```

Panel bota doğrudan bağlanmaz: bot veriyi panele **iter**, panel komutları **kuyruğa** yazar, bot kuyruğu **çeker**. Her istekte `X-Bot-Key` (iki `.env`'de aynı `BOT_API_KEY`).

---

## 3. Bot (`kriptografikbotu`)

### 3.1 Modüller (gruplu)

**Çekirdek**
| Dosya | Satır | Görev |
|---|---|---|
| `main.py` | 5074 | Telegram komutları, düğmeler, zamanlanmış işler, düz yazı anlama, panel komutları |
| `config.py` | 174 | Bütün ayarlar ve eşikler (`.env`'den okunur) |
| `gate.py` | 310 | **Tek karar kapısı**: kural kural geçti/kaldı/uyarı, R/R, kademe |
| `llm.py` | 346 | Yapay zekâ çağrıları: sıra, yedek model, konsey oyu, ekran görüntüsü okuma |
| `system_prompt.py` | 278 | Yapay zekânın kural kitabı (kripto, BIST, ABD motorları) |
| `conversation_store.py` | 107 | Sohbet geçmişi ve plan durumu |
| `alerts_store.py` | 132 | Alarmlar ve ayarlar (sessiz saat, okul modu...) |
| `positions.py` | 217 | Pozisyonlar ve karar fişleri |

**Kripto**
| `market.py` (291) Binance mum + göstergeler · `alert_engine.py` (172) websocket kapanış alarmları · `watcher.py` (196) 15 dk plan takibi · `structure.py` (346) yapı motoru (HH/HL, BOS/CHoCH, likidite, konfluens) · `derivatives.py` (85) funding/OI · `sentiment.py` (90) korku-açgözlülük · `scanner.py` (123) otomatik tarama · `backtest.py` (131) kapanış bazlı test |

**BIST**
| `bist.py` (279) Yahoo verisi, endeks kapısı · `bist_signals.py` (498) günlük kurulum + 1 saat teyit · `fundamentals.py` (303) İş Yatırım bilançoları, skor · `strength.py` (133) haftalık güç sıralaması · `corporate.py` (284) temettü/bölünme · `eod.py` (89) gün sonu raporu |

**ABD**
| `us.py` (354) Tiingo/Yahoo fiyat, NYSE takvimi, rejim · `us_fund.py` (552) SEC EDGAR + analist tahminleri, skor · `us_signals.py` (240) ABD planı ve kapısı |

**Portföy ve disiplin**
| `balance.py` (118) bakiye/K-Z · `risk.py` (188) yoğunlaşma, korelasyon · `discipline.py` (155) tilt koruması · `journal.py` (106) işlem günlüğü · `shadow.py` (113) gölge portföy · `benchmark.py` (225) kıyas · `dca.py` (106) birikim planı · `pf_alarm.py` (94) portföy alarmı · `assets.py` (70) altın/döviz · `exits.py` (206) çıkış/tepe analizi · `model_score.py` (55) model karnesi |

**Diğer**
| `features.py` panel dönemi özellikleri: plan listesi, 90 günlük portföy geçmişi, hedef dağılım, şirket takvimi (bilanço/temettü), KAP bildirimleri, takip kuralları, haftalık ders, sanal işlemler · `watchlist.py` (187) takip listesi · `opportunities.py` (335) "şu an ne alınır" taraması · `macro.py` (477) FRED/BLS/CFTC, rejim, takvim · `news.py` (239) RSS haberler · `risk_news.py` (152) riskli başlık uyarısı · `freshness.py` (158) veri güncelliği · `universe.py` (91) seçim listeleri · `costs.py` (61) harcama kaydı · `charts.py` (105) PNG grafik · `web_sync.py` (677) panel köprüsü |

**Testler:** `test_features.py`, `test_bist.py`, `test_startup.py` (68 test). Çalıştırma: `.venv\Scripts\python -m unittest test_features test_bist test_startup`

### 3.2 Veri dosyaları (`data\`)

| Dosya | İçerik |
|---|---|
| `positions.json` | açık/kapalı pozisyonlar (portföy) |
| `decisions.json` | her alarm/sinyal için karar fişi (kapı kuralları, sonuç) |
| `alerts.json` | kapanış alarmları |
| `settings.json` | ayarlar, **takip listesi**, bütçeler, plan listesi, sessiz saat |
| `state.json` | yapay zekânın kaydettiği planlar (tetik/iptal/hedef) |
| `history.json` | sohbet geçmişi (100 tur) |
| `usage.jsonl` | yapay zekâ harcaması (çağrı başına satır) |
| `macro_cache.json`, `universe.json`, `takip_durum.json` | önbellekler |
| `bot.log*` | loglar (**GitHub'a gitmez**: Telegram token'ı içeren adresler olabilir) |
| `positions_yedek_20260926.json` | portföy temizlenmeden önceki yedek |
| `pf_history.json` | günlük portföy değeri + 90 günlük geriye dönük seri |
| `sirket_takvimi.json`, `kap_seen.json` | bilanço/temettü takvimi, görülen KAP bildirimleri |
| `sanal.json` | sanal (kağıt) işlemler; gerçek portföyde sayılmaz |

### 3.3 Zamanlanmış işler (bot açıkken otomatik)

| Ne zaman | İş |
|---|---|
| Sürekli (websocket) | Kripto kapanış alarmları |
| 15 dk | Plan takibi (kripto), BIST saatlik kontrol, portföy alarmı, panel "extras" |
| 15 dk | KAP: portföydeki BIST hisseleri için yeni bildirim |
| 30 dk | Riskli haber uyarısı; **takip listesi sorusu** ("bakmak ister misin?", sessiz); takip kuralları (desteğe yakın, RSI, hacim) |
| Her gün 08:45 ve 20:00 | Şirket takvimi (bilanço, temettü) hatırlatması |
| Her gün 19:15 | Hedef dağılımdan sapma hatırlatması |
| Pazar 20:10 | Haftanın dersi |
| 4 saatte bir | Kripto çıkış/tepe analizi |
| Her gün 09:30 | Evren güncelleme · 09:45 kurumsal işlemler (temettü/bölünme) · 10:15 birikim hatırlatma |
| Her gün 16:05 | Okul raporu (okul modu açıksa) |
| Her gün 18:35–19:00 | BIST günlük tarama, çıkış analizi, gün sonu, satış sonrası |
| New York 16:20 | ABD günlük kontrol |
| Cuma 19:00 | BIST güç sıralaması · Cumartesi 10:00 ABD güç sıralaması · Pazar 20:00 haftalık özet |
| 1 dk / 15 sn | Panele veri gönderme / panel komutlarını okuma |

### 3.4 Telegram komutları (menü)

Temel: `/komutlar /portfoy /bakiye /aldim /plan /firsat /takip /tara`
Kripto: `/analiz /haber /vadeli /duygu /new_alert /backtest`
BIST: `/incele /bist /guc /temel /gunsonu /temettu` · ABD: `/abd /temel AAPL`
Portföy: `/grafik /risk /kiyas /palarm /birikim /hesap /pozisyonlar /sat /duzelt /kayitsil`
Alarm: `/view_alerts /cancel_alert` · Takip/karne: `/rapor /haftalik /golge /karne /gunluk /disiplin`
Yeni: `/hedef /sanal /ders /kap /olaylar /takip kural` · Makro: `/makro /takvim` · Sistem: `/model /maliyet /durum /okul /pozisyon /sil /sifirla /set_config /get_logs /start`

Düz yazı da anlaşılır: "BTC ne durumda", "portföy", "bakiye", "şu an alabileceğim bir şey var mı", "takip listem", "THYAO 300 üstünde kapanırsa haber ver", "astordan 4 tane 260 TL'den aldım". Ekran görüntüsü atılırsa portföy okunur (Kimi K3).

### 3.5 `.env` anahtarları (değerleri yalnız bilgisayarda, GitHub'a gitmez)

`TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_ID, DEEPSEEK_API_KEY, NVIDIA_API_KEY / KIMI_API_KEY / GLM_API_KEY, TIINGO_API_KEY, FRED_API_KEY, BLS_API_KEY, CFTC_APP_TOKEN, EVDS_API_KEY (isteğe bağlı), SEC_USER_AGENT, WEB_URL, BOT_API_KEY`

---

## 4. Web paneli (`kapanis`)

### 4.1 Backend (`kapanis\backend`)

| Dosya | Görev |
|---|---|
| `server.py` | FastAPI: giriş (JWT çerez), veri uçları, komut kuyruğu, derlenmiş arayüzü ve `/logos` klasörünü sunar |
| `chart_data.py` | Grafik sayfası verisi: Binance/Yahoo mumları + SMA 20/50/200, RSI 14, hacim ortalaması, VWAP (60 sn önbellek) |
| `.env` | `MONGO_URL, DB_NAME, JWT_SECRET, BOT_API_KEY, ADMIN_EMAIL, ADMIN_PASSWORD, CORS_ORIGINS` |

**API uçları** (`/api/...`):
- Giriş: `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me`
- Okuma: `GET /overview /extras /alerts /positions /decisions /signals /signals/{id} /macro /derivatives /usage /report /backtest /settings /candles/{sembol} /chart/{kod}?tf=&market= /bot/status /commands`
- Yazma (hepsi kuyruğa gider, bot uygular): `POST /alerts`, `DELETE /alerts/{id}`, `PATCH /positions/{id}/stop`, `POST /positions/{id}/close`, `POST /decisions/{id}/action`
- Bot için: `POST /ingest/{koleksiyon}`, `GET /commands/pending`, `POST /commands/{id}/done`

### 4.2 Frontend (`kapanis\frontend\src`)

**Sayfalar** (`pages\panel\`):
| Sayfa | Adres | Veri |
|---|---|---|
| Genel bakış | `/app` | overview, extras, macro, candles |
| Portföy | `/app/portfoy` | extras (portföy, geçmiş grafiği, hedef dağılım, kıyas, kur) |
| Takip listem | `/app/takip` | extras.takip_listesi, takip kuralları, seçili kodlar için yapay zekâ analizi |
| Pozisyonlar | `/app/pozisyonlar` | positions (+ "Sattım"), Sanal sekmesi |
| Grafik | `/app/grafik?kod=&piyasa=&tf=` | chart (+ alış/plan çizgileri, destek/direnç bölgeleri, sinyal işaretleri, "Analiz et") |
| Planlar & fırsatlar | `/app/planlar` | extras.planlar, firsat ("Şimdi tara") |
| Sinyaller | `/app/sinyaller` | signals, decisions (+ Aldım/Pas) |
| Alarmlar | `/app/alarmlar` | alerts (+ kur/sil) |
| Disiplin | `/app/disiplin` | extras, report, haftanın dersi |
| Rapor & karne, Backtest, Makro, Vadeli, Maliyet, Ayarlar | `/app/rapor` ... | report, backtest, macro, derivatives, usage, settings |
| Giriş | `/giris` | auth |
| Tanıtım sitesi | `/`, `/ozellikler`, `/nasil-calisir`, `/kurallar`, `/sss`, `/iletisim` | — |

**Tasarım sistemi** (Claude Design "Kapanış" sisteminden):
- `src\ds\` — `bundle.js` (hazır React bileşenleri, `window.Kapanis`), `bundle.css`, `tokens.css` (renk/yazı değişkenleri). Kaynak: https://claude.ai/artifact/5npq45f4RNzq5dRrSEHbwV
- `components\kp.jsx` — aynı sistemle yazılmış kendi bileşenlerimiz (Segmented, Chip, ChangeBadge, RSI çubuğu...)
- `components\AssetLogo.jsx` — **tek logo bileşeni** (40px daire; dolu logolar daireyi doldurur, sembol logolar beyaz rozette)
- `components\PanelLayout.jsx` — kenar menü, üst çubuk (bot durumu, piyasa saatleri, A−/A+, tema)
- `lib\` — `format.js` (tr-TR sayı: 1.240,50 · %2,41), `theme.js` (koyu/açık, yazı boyutu), `dsmap.js` (bot verisi → bileşen), `portfolio.js`, `api.js`, `useData.js`

**Logolar** (`frontend\public\logos\`): `BIST\` (536), `ABD\` (7.662), `KRIPTO\` (497) + eski BIST kopyaları kökte. Sıra: kendi dosyan → internetteki ücretsiz logo → baş harfler. Yeni dosya koymak için yeniden başlatma gerekmez.

---

## 5. Çalıştırma ve bakım

| İş | Nasıl |
|---|---|
| Hepsini başlat | `KAPANIS-BASLAT.bat` (eski süreçleri kapatır, MongoDB'yi açar, arayüz değiştiyse derler, API + botu açar, tarayıcıyı açar) |
| Durdur | `KAPANIS-DURDUR.bat` |
| Çalışıyor mu? | `kriptografikbotu\kapanis_surecler.ps1` |
| Arayüzü elle derle | `kapanis\frontend` içinde `npx craco build` |
| Testler | bölüm 3.1 |
| Arşiv | GitHub private depolar (bölüm 2). `.env`, loglar, `.venv`, `node_modules`, `build` gitmez |

Telefon: Tailscale kurulu. `kriptografikbotu\mobil-panel.ps1` paneli yalnız Tailscale ağına HTTPS ile açar; telefonda adres + `/app`, sonra "Ana ekrana ekle" (PWA).

Sınırlar: bilgisayar kapalıyken bot ve panel çalışmaz. BIST verisi ~15 dk gecikmeli (Yahoo).

---

## 6. Dış servisler

| Servis | Ne için | Ücret / sınır |
|---|---|---|
| Telegram Bot API | mesajlar | ücretsiz |
| DeepSeek (V4.1 Flash) | yapay zekâ | **ücretli** (yoğun saat 2×; `/maliyet`) |
| NVIDIA (Kimi K3, GLM 5.3) | yapay zekâ, ekran görüntüsü okuma | ücretsiz kredi |
| Binance (spot + vadeli, public) | kripto fiyat, mum, funding | ücretsiz |
| Yahoo Finance | BIST, ABD (yedek), endeksler, kur | ücretsiz, resmi değil |
| Tiingo | ABD fiyat | ücretsiz, günde ~1000 istek |
| SEC EDGAR | ABD bilançoları | ücretsiz |
| İş Yatırım | BIST bilançoları | ücretsiz |
| FRED, BLS, CFTC | makro, enflasyon, COT | ücretsiz |
| alternative.me, CoinGecko | korku-açgözlülük, dominans | ücretsiz |
| RSS (CoinDesk, Fed, SEC...), Google News | haberler | ücretsiz |
| CoinCap, Financial Modeling Prep | logo yedeği | ücretsiz |
| TradingView Lightweight Charts | grafik kütüphanesi (yerelde) | açık kaynak, sınırsız |

---

## 7. Plan yaparken bakılacak açık konular

- **APK:** istenirse Capacitor ile PWA'dan paketlenebilir.
- **Panelden yapılamayanlar** (yalnız Telegram): temel analiz (`/temel`), takip listesine ekleme/çıkarma.
- **Vergi hesabı:** bilerek eklenmedi.
- **ABD bütçesi girilmedi:** `/abd butce 1000` (yoksa ABD ilk kademe ve günlük zarar sınırı hesaplanamaz).
- **Alış tarihi olmayan pozisyonlar:** kıyas ve dolar/enflasyon bazlı getiri için `/duzelt ID tarih=...`.
- **Tanıtım sitesi** henüz eski tasarımda; yalnız renkleri yeni.
- **Logo:** birkaç yazılı logo (AYGAZ, CVX) daireye kırpılınca kenarları kesiliyor; istenirse dosyaları değiştirilebilir.
