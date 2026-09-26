# Kapanış — Web Paneli Tasarım Prompt'u

> Bu metnin tamamını site tasarlayan yapay zekâya (Lovable, v0, Bolt vb.) yapıştır.
> Arayüz dili: **Türkçe**. Tüm butonlar, başlıklar ve boş durum metinleri Türkçe olacak.

---

## 1. Rolün ve görevin

Sen deneyimli bir fintech ürün tasarımcısı ve React ön yüz geliştiricisisin. **"Kapanış"** adlı kişisel yatırım karar destek sisteminin web panelini baştan, modern ve profesyonel bir şekilde tasarlayıp kodlayacaksın.

Arka uç (FastAPI + MongoDB) **hazır ve değişmeyecek**. Senin işin yalnızca ön yüz: aşağıdaki API sözleşmesine birebir uyan, güzel, hızlı, mobilde de rahat kullanılan bir panel.

---

## 2. Ürün ne yapıyor? (tasarımı bu mantık belirler)

Kapanış, tek bir kişinin (admin) kullandığı bir **Telegram botu + web paneli**dir. Üç piyasayı izler:

| Piyasa | Kural | Para birimi | Veri |
|---|---|---|---|
| 🪙 Kripto | Yalnız **spot**, kaldıraç yok, short yok | USD / USDT | Binance, anlık |
| 🇹🇷 BIST | Yalnız **orta / uzun vade** (kısa vade asla) | TL | Yahoo, ~15 dk gecikmeli |
| 🇺🇸 ABD hisseleri | Orta / uzun vade | USD | Tiingo + Yahoo, SEC bilançoları |

Temel ilkeler (arayüz bunları hissettirmeli):

1. **Bot asla işlem yapmaz.** Sadece karar desteği verir. Sitede "Al", "Sat", "Emir gönder" gibi borsaya emir veriyormuş izlenimi veren buton **olmayacak**. Var olan butonlar yalnızca botun kaydını günceller ("Aldım" / "Pas" / "Pozisyonu kapattım").
2. **Sayıları kod hesaplar, yapay zekâ sadece açıklar.** Arayüzde iki tür içerik ayrı görünmeli:
   - "🧮 Kod hesapladı" etiketi: fiyat, yüzde, R/R, skor, kural sonuçları.
   - "🧠 Yapay zekâ yorumu" etiketi: metin analizleri. Hangi modelin yazdığı da gösterilir (Kimi K3 / DeepSeek V4.1 Flash / GLM 5.3; 15 dakikada bir sırayla döner).
3. **Kapanış kuralı:** Alarmlar ve sinyaller sadece mum **kapanışıyla** tetiklenir, fitil/iğne sayılmaz. Bu, ürünün adı ve kimliğidir.
4. **Goalpost yasağı:** Açık pozisyonda stop aşağı çekilemez. Arayüz buna izin vermemeli (bkz. Pozisyonlar).
5. **"Kesin kazanç" dili yok.** Skorlar kalite ölçüsüdür, olasılık değildir. Her yerde sakin, dürüst, abartısız dil.
6. Kullanıcı Türk, öğrenci, küçük bütçeli bireysel yatırımcı. Tasarım onu **aceleye getirmemeli**, disiplin hissettirmeli: FOMO yaratan animasyon, yanıp sönen kırmızı/yeşil, konfeti vb. yok.

---

## 3. Teknik gereksinimler

- **React 18 + React Router v6**, **Tailwind CSS**, **shadcn/ui** bileşenleri, **lucide-react** ikonları.
- Veri çekme: **@tanstack/react-query**. Her sayfa sorgusu `refetchInterval: 8000` ve `refetchOnWindowFocus: true` ile canlı yenilenir.
- HTTP: `axios` örneği, `baseURL = process.env.REACT_APP_BACKEND_URL + "/api"`, `withCredentials: true`. Kimlik doğrulama **httpOnly cookie** ile yapılır (login cevabında `access_token` da döner, istersen `Authorization: Bearer` başlığına da ekle). 401 alınca bir kez `POST /api/auth/refresh` dene, yine 401 ise `/giris`'e yönlendir.
- Grafikler: mum grafiği için **lightweight-charts** (TradingView), diğer grafikler için **recharts**.
- Sayılar **JetBrains Mono** ve `font-variant-numeric: tabular-nums` ile; metinler **Inter**.
- Sayı biçimi: binlik ayırıcı ince boşluk, ondalık nokta → `84 176.50`. Yüzde her zaman işaretli → `+2.84%`, `-9.99%`. Çok küçük fiyatlar bilimsel gösterimle **asla** yazılmaz: `0.00000594` (SHIB). Adetler kesirli olabilir, yuvarlanmaz: `46.198 adet`. Büyük adetler: `5 047 971`.
- Tarih/saat: `Europe/Istanbul`, `tr-TR` biçimi (`26.09 14:50`). Göreli zaman da göster ("3 dk önce").
- Tasarım önizlemesi için `REACT_APP_MOCK=1` olduğunda aşağıdaki örnek JSON'larla çalışan bir **mock modu** ekle; üretimde mock veri **asla** gösterilmeyecek.
- Erişilebilirlik: klavyeyle gezilebilir, renk körlüğü için yükseliş/düşüş sadece renkle değil **ok/işaret** ile de anlatılır (▲ ▼).

---

## 4. Görsel dil

- **Varsayılan koyu tema** (zemin saf siyaha yakın `#000`/`#0a0a0a`, kartlar `#0f0f0f`, ince çizgiler `#1f1f1f`). Açık tema da olsun; sağ üstte tema düğmesi, seçim `localStorage`'da saklansın.
- Renk anlamları (tüm sitede tutarlı):
  - Yükseliş / geçti / TUT → yeşil (`#22c55e` civarı)
  - Düşüş / kaldı / SAT → kırmızı (`#ef4444` civarı)
  - Bekle / uyarı / KISMİ SAT → kehribar (`#f59e0b`)
  - Bilgi / nötr → mavi-gri
  - Piyasa etiketleri: Kripto 🪙, BIST 🇹🇷, ABD 🇺🇸, Altın/Döviz 🥇
- Hava: Bloomberg terminalinin ciddiyeti + Linear/Vercel'in sadeliği. Yoğun ama ferah. Kart köşeleri 12px, gölge yok, ince kenarlık.
- Her kartın sağ üstünde veri tazeliği küçük yazıyla ("Güncelleme: 14:50 · 30 dk'da bir").
- Her veri bileşeninin 4 durumu tasarlanmalı: **yükleniyor** (iskelet), **boş** (ne yapılacağını söyleyen metin + ilgili Telegram komutu), **hata**, **bayat veri** (kehribar "veri eski" rozeti).
- Panelin altında her sayfada sabit küçük not: "Kapanış bir karar destek aracıdır, yatırım tavsiyesi değildir. Bot işlem yapmaz."

---

## 5. Site haritası

### 5.1 Herkese açık site (giriş gerektirmez)
`/` Ana sayfa · `/ozellikler` · `/nasil-calisir` · `/kurallar` · `/sss` · `/iletisim` · `/giris`

### 5.2 Panel (giriş gerekir, `/app` altında)
Sol kenar çubuğu (mobilde alttan açılan menü), gruplu:

- **Özet**
  - `/app` — Genel Bakış
- **Portföy**
  - `/app/portfoy` — Portföy
  - `/app/takip` — 👀 Takip Listem
  - `/app/pozisyonlar` — Pozisyonlar
- **Sinyaller**
  - `/app/sinyaller` — Sinyaller & Analiz
  - `/app/alarmlar` — Alarmlar
- **Performans**
  - `/app/disiplin` — Disiplin & Günlük
  - `/app/rapor` — Rapor & Kural Karnesi
  - `/app/backtest` — Backtest
- **Piyasa**
  - `/app/makro` — Makro
  - `/app/vadeli` — Vadeli (kripto türevleri)
- **Sistem**
  - `/app/maliyet` — Yapay zekâ maliyeti
  - `/app/ayarlar` — Ayarlar

**Üst çubuk** (her panel sayfasında):
- Bot durumu: `GET /api/bot/status` → `last_ingest`. 20 dakikadan yeniyse 🟢 "Bot çevrimiçi", değilse 🔴 "Bot yanıt vermiyor (son veri: …)".
- Piyasa saatleri: 🇹🇷 BIST (hafta içi 10:00–18:00 TR, açık/kapalı), 🇺🇸 NYSE (09:30–16:00 New York saati; yaz saatine dikkat), 🪙 Kripto "7/24". Hafta sonu "Kapalı · son seans Cuma" yazsın.
- Bekleyen komut rozeti: `GET /api/commands` (6 sn'de bir) → `status: "pending"` olanların sayısı: "⏳ 2 işlem bota iletildi".
- Tema düğmesi, kullanıcı menüsü (çıkış: `POST /api/auth/logout`).

---

## 6. Sayfalar — ayrıntılı

### 6.1 Giriş (`/giris`)
- E-posta + şifre, "Giriş yap". `POST /api/auth/login` `{email, password}`.
- 401 → "E-posta veya şifre hatalı." · 429 → sunucunun `detail` mesajını göster (15 dk kilit).
- Ortada logo ("Kapanış" — mum çubuğu + kapanış çizgisi fikri), altında tek satır: "Sadece kapanış konuşur."

### 6.2 Genel Bakış (`/app`) — `GET /api/overview`
Üstte 4–6 istatistik kartı:
- Açık pozisyon (`open_positions`), kurulu alarm (`armed_alerts`), bekleyen karar (`pending_decisions`, >0 ise kehribar ve Sinyaller'e bağlantı).
- Kripto bugün: `day_pnl` USD + `day_pnl_pct`. BIST bugün: `bist_day_pnl` TL + `bist_day_pnl_pct`. Hafta sonu etiketi "Son seans".
- Açık risk: `open_r` (R cinsinden).
- Makro rejim: `regime_score` (-5…+5) yatay ölçekte, `regime_label` ("RİSK-ON", "RİSK-OFF", "karışık").

Sonra:
- **Öne çıkanlar** listesi: `highlights[] {text, tone: up|down|wait|info}` — renkli sol çizgili satırlar.
- **Veri tazeliği** tablosu: `veri_durumu[]` (kaynak adı, son veri zamanı, durum). Kırmızı olan varsa sayfanın en üstünde uyarı bandı.
- **Portföy mini özeti** (`/api/extras` → piyasa başına toplam, bkz. 6.3) ve **takip listesinin en çok yükselen/düşen 3'ü** (bkz. 6.4).
- Sağ kolonda BTC 1 saatlik mini mum grafiği: `GET /api/candles/BTC-USDT`.

### 6.3 Portföy (`/app/portfoy`) — `GET /api/extras` → `portfoy`, `yogunlasma`, `kiyas`
**Piyasa kartları** (BIST TL, Kripto USD, ABD USD, Altın/Döviz). Satırları piyasaya göre toplayıp hesapla:
- Değer = Σ`deger`, Maliyet = Σ`maliyet`, Toplam K/Z = Değer − Maliyet (hem tutar hem %).
- Günlük tutar = Σ(`deger` − `deger` / (1 + `gun_yuzde`/100)); yüzde bununla hesaplanır.
- Etiket: Kripto "24 saat", BIST/ABD hafta içi "Bugün", hafta sonu/kapalıyken **"Son seans"**.

**Portföy tablosu** (piyasa sekmeleri: Tümü / BIST / Kripto / ABD / Altın-Döviz). Sütunlar:
Varlık · Adet · Ort. maliyet (`maliyet/adet`) · Fiyat · Değer · Günlük % · Toplam % · K/Z tutarı · $/TL bazında (`usd_yuzde` TL varlıkta, `tl_yuzde` USD varlıkta) · Reel % (`reel_yuzde`, enflasyondan arındırılmış; yoksa "—") · Temettü.
- Satır tıklanınca sağdan çekmece: ayrıntılar + "Telegram'da analiz: /portfoy analiz".
- Masaüstünde tablo, mobilde her varlık bir kart (üst satır ad + değer, alt satır günlük/toplam rozetleri).
- **Dağılım halkası** (recharts pie): varlıkların değere göre payı (TL ve USD ayrı ya da `usd_try` ile çevrilmiş tek halka; seçilebilir).
- **Yoğunlaşma uyarıları**: `yogunlasma.uyarilar[]` → ⚖️ kehribar kutular.
- **Kıyas** kartı (`kiyas`): "Senin portföyün %X" ve altında `kiyas.kiyas[] {ad, yuzde, fark, not}` (BIST100, USD, altın, mevduat…). `fark>0` → "yendin" yeşil, `<0` → "geride" kırmızı.

### 6.4 👀 Takip Listem (`/app/takip`) — `GET /api/extras` → `takip_listesi`
Kullanıcının izlediği ama elinde olmayabilecek kodlar. 16 coin, 35 BIST, 53 ABD hissesi. Bot bunları **otomatik analiz etmez**; Telegram'da 30 dakikada bir "bakmak ister misin?" diye sorar. Site sadece kodla hesaplanmış hızlı durumu gösterir (30 dk'da bir yenilenir).

- Üstte sekmeler: 🪙 Kripto (16) · 🇹🇷 BIST (35) · 🇺🇸 ABD (53) — sayılar veriden.
- Araçlar: kod arama, sıralama (liste sırası, günlük ↑/↓, haftalık ↑/↓, RSI, desteğe yakınlık), filtre çipleri (↗ güçlü trend / ↘ zayıf / RSI>70 ısınmış / RSI<30 / desteğe %2'den yakın / 💼 portföyümde).
- Özet satırı: "27/35 yükselişte" + mini ısı haritası (her kod bir kare, renk günlük %'ye göre).
- Tablo sütunları: Kod (portföydeyse 💼) · Fiyat · Günlük % · Haftalık % · Trend (`↗ güçlü` yeşil, `→ karışık` gri, `↘ zayıf` kırmızı, `az veri`) · RSI (≥70 kehribar, ≤30 kırmızı; küçük çubuk) · Destek (fiyat + uzaklık %) · Direnç (fiyat + uzaklık %).
- **Destek–fiyat–direnç** mini çubuğu: her satırda fiyatın destek ile direnç arasındaki konumu.
- `hata` alanı olan satır: "veri alınamadı" gri.
- Çoklu seçim kutucukları + alttan açılan eylem çubuğu: "Telegram'da analiz et" → seçilen kodlarla `/takip KOD1 KOD2` komutunu panoya kopyalar (site yapay zekâyı doğrudan çağırmaz).
- Bilgi notu: Kripto "günlük = 24 saatlik değişim"; BIST/ABD "günlük = son seans"; BIST "~15 dk gecikmeli".

### 6.5 Pozisyonlar (`/app/pozisyonlar`) — `GET /api/positions`
- Sekmeler: Açık / Kapanmış (son 10).
- Kart veya tablo: sembol, piyasa, giriş, güncel, stop, hedef, adet (`size`), K/Z (`pnl` + `pnl_pct`), R/R, açılış tarihi.
- Stop ile hedef arasında fiyatın konumunu gösteren yatay ilerleme çubuğu (stop kırmızı uç, hedef yeşil uç, giriş işaretli).
- **Stop güncelle**: `PATCH /api/positions/{id}/stop {stop}`. Arayüz yeni stop mevcut stoptan düşükse butonu kapatıp "Goalpost kuralı: stop aşağı çekilemez" yazar. Sunucu 409 dönerse `detail`'i göster.
- **Kapattım** (sattım kaydı): `POST /api/positions/{id}/close`. BIST pozisyonunda gerçekleşen satış fiyatı **zorunlu** alan (`{price}`). Onay penceresi: "Bu sadece botun kaydını günceller, borsada işlem yapmaz."
- Her komuttan sonra satırda "⏳ Bota iletildi" rozeti, bot işleyince kendiliğinden kalkar (`/api/commands` pending listesinden düşünce).
- `stop` veya `target` null ise (portföy olarak girilmiş varlık) "stop yok" gri rozeti.

### 6.6 Sinyaller & Analiz (`/app/sinyaller`) — `GET /api/signals`, `GET /api/signals/{id}`, `GET /api/decisions`
**Bekleyen kararlar** bandı (en üstte, `decisions` içinde `status: "pending"`): sembol, bot kararı, giriş/stop/hedef, R/R, not. İki buton: "✅ Aldım" / "❌ Pas" → `POST /api/decisions/{id}/action {verdict: "Aldım" | "Pas"}`. Bot kararı AL değilse "Aldım"a basınca ek onay iste.

**Sinyal listesi** (sol) + **ayrıntı** (sağ, mobilde ayrı ekran):
- Liste: sembol, piyasa rozeti, zaman dilimi, tip ("Kapanış ABOVE"), skor (-5…+5 renkli), tek satır özet, zaman.
- Ayrıntı:
  - 4 gösterge paneli `analysis.panels[] {title, value, detail}` (Trend, RSI, Hacim/MA20, ATR/VWAP).
  - **Bot kararı** büyük rozet: `analysis.bot_decision.verdict` (AL yeşil / BEKLE kehribar / PAS kırmızı / TUT) + gerekçe.
  - **Kod kapısı** (en önemli bölüm): `analysis.gate.kurallar[]` her kural bir satır, ✅/⚠️/❌ ikonlu, `kural` başlık + `detay`. Üstte "Kapı: GEÇTİ / KALDI". Kural ↔ sonuç ilişkisini anlatan küçük not.
  - **Sonra ne oldu**: `analysis.outcome {sonuc: hedef|stop|acik, cikis, mum, R}` — "Hedefe 14 mumda ulaştı, +2.1R" gibi.
  - Kullanıcı ne yaptı: `analysis.user_action` (Aldım / Pas / —).
  - **Yapay zekâ metni**: `analysis.text` — markdown olarak, "🧠 Yapay zekâ yorumu" başlıklı, daraltılabilir kutuda. Metin sonunda "🧠 model adı" satırı varsa rozet olarak göster.
  - Mum grafiği (`/api/candles/{symbol}` — `/` yerine `-`: `BTC-USDT`), giriş/stop/hedef yatay çizgileri ve SMA20/50/200. BIST (`.IS`) sembollerinde mum verisi yok → "BIST grafiği Telegram'da: /grafik THYAO".

### 6.7 Alarmlar (`/app/alarmlar`) — `GET /api/alerts`, `POST /api/alerts`, `DELETE /api/alerts/{id}`
- Durum sekmeleri: Kurulu (`armed`) / Tetiklendi (`triggered`) / İptal (`cancelled`).
- Satır: sembol, yön (long = "üstünde kapanırsa", short = "altında kapanırsa"), tetik, iptal, hedef, R/R, not, oluşturma zamanı.
- **Yeni alarm** formu (yalnız kripto): sembol (ör. `BTC/USDT`), yön, tetik, iptal (opsiyonel), hedef (opsiyonel), zaman dilimi (`15m, 1h, 4h, 1d`), bekleme süresi (`30m, 1h, 4h`), not.
  - Anlık doğrulama: long'da iptal < tetik < hedef; short'ta tersi. Hatalıysa buton kapalı + açıklama.
  - Gönderince "⏳ Bota iletildi"; bot reddederse Telegram'a sebebi yazar (formun altında bunu belirt).
- Sil → onay penceresi → `DELETE`.
- Boş durum: "Kurulu alarm yok. Telegram'da düz yazıyla da kurabilirsin: 'THYAO 300 üstünde kapanırsa haber ver'".

### 6.8 Disiplin & Günlük (`/app/disiplin`) — `GET /api/extras`
- **Disiplin kalkanı** (`disiplin`): açık/kapalı, zarar serisi `seri`, bekleme bitişi `bekleme_bitis` (varsa geri sayım), piyasa başına günlük zarar ve "⛔ yeni giriş yok / ✅ serbest" (`piyasa.KRIPTO`, `piyasa.BIST`), son 7 gün kural olayları `olaylar {ad: sayı}`.
- **Gölge portföy** (`golge {TL|USD: {sinyal, kapanan, kazanan, acik, net, acik_net, gercek_net, aldigin}}`): "Botun her ŞİMDİ AL'ını alsaydın" vs "senin gerçek sonucun" yan yana iki sütun çubuk.
- **İşlem günlüğü** (`gunluk`): kapanan işlem, plana uyum (`plan_uyumu.stop_uygulandi/hedef/arada/gec_stop`), satıştan 5 gün sonra (`satis_sonrasi.ort_5g, erken, iyi`), en sık hata (`en_sik_hata.hata/sayi`).
- **Birikim planları** (`birikim[] {id, varlik, gun, tutar, para, adet, ortalama}`): "Her ayın 5'i 50 USD BTC" kartları.
- **Plan listesi** (`plan_listesi[]`): çipler.
- **Piyasa duygusu** (`duygu.korku_acgozluluk {deger, etiket}`, `duygu.piyasa.btc_dominans`): 0–100 yarım daire gösterge.

### 6.9 Rapor & Kural Karnesi (`/app/rapor`) — `GET /api/report`, `extras.karne`
- Performans kartları: işlem sayısı, isabet oranı (`win_rate` 0–1 → %), ort. planlanan R/R, toplam R, en iyi/en kötü R.
- Kümülatif R eğrisi (işlemlerden hesapla).
- İşlem tablosu: sembol, piyasa, giriş, çıkış, R, sonuç (win/loss), kapanış tarihi.
- **Kural karnesi** (`rule_stats`): her kural için "geçtiğinde kazanma %" vs "kaldığında kazanma %"; yan yana çubuk. `extras.karne[]` öneri cümleleri altta. Az veri varsa "En az 20 sonuçlanmış karar gerekiyor".

### 6.10 Backtest (`/app/backtest`) — `GET /api/backtest`
Strateji adı, dönem, metrik kartları (işlem, isabet, kâr faktörü, maks. düşüş R, beklenti R), `equity_curve[]` alan grafiği, `note` (komisyon + kayma düşüldü). Boşsa: "Telegram'da /backtest komutuyla çalıştır".

### 6.11 Makro (`/app/makro`) — `GET /api/macro`
Rejim skoru büyük gösterge (-5…+5) + `regime_label`. Bileşenler `components[] {name, value, score}` (net likidite, dolar, kredi spreadi, VIX, reel faiz) — her biri -1/0/+1 renkli. `dxy_alt` kartı. **Takvim** `calendar[] {time, title, country, importance}`: önümüzdeki 14 gün, zaman çizelgesi; 2 saat içindekiler kehribar ("veriye 2 saat kala yeni giriş yok"). `note` paragrafı. `stale: true` ise bayat rozeti.

### 6.12 Vadeli (`/app/vadeli`) — `GET /api/derivatives`
BTC ve ETH kartları: funding oranı (`funding_rate` %), açık pozisyon (`open_interest` USD, kısaltılmış: 12.4B), long/short oranı, COT yüzdeliği (0–100 çubuk), baz (`basis` %). Not: "Bilgi amaçlı; bot vadeli işlem yapmaz."

### 6.13 Maliyet (`/app/maliyet`) — `GET /api/usage`
Bugünkü toplam yapay zekâ maliyeti (USD ve `usd_try` ile TL), çağrı sayısı, giriş/çıkış token. Saatlik maliyet sütun grafiği `hourly[] {hour, cost, calls}`, üstünde tarife bandı `tariff[] {hour, rate, tier: yüksek|düşük}` (ucuz saatler açık renk). Not: Kimi K3 ve GLM 5.3 NVIDIA ücretsiz kredisiyle, DeepSeek ücretli.

### 6.14 Ayarlar (`/app/ayarlar`) — `GET /api/settings`
Salt okunur: `params[] {label, value}` tablo; `rules_readonly[]` "Değişmez kurallar" listesi (kilit ikonlu). Ayarların Telegram'dan değiştirildiğini belirten not (`/set_config`, `/bist butce`, `/abd butce`, `/takip aralik`).

---

## 7. Herkese açık site içeriği

- **Ana sayfa:** Başlık "Kapanış — sadece kapanış konuşur." Alt başlık: "Kripto, BIST ve ABD hisselerini kurallarla izleyen kişisel karar destek botu. İşlem yapmaz; disiplin yapar." Üç piyasa kartı, "Nasıl çalışır" 4 adım (alarm kur → kapanış gelir → kod kapısı kontrol eder → yapay zekâ açıklar, sen karar verirsin), Telegram ekran görüntüsü maketi, "Panele giriş" butonu.
- **Özellikler:** Kapanış alarmları, kod kapısı (R/R, hacim teyidi, BTC kapısı, makro rejim, disiplin kalkanı), üç yapay zekâ rotasyonu ve konsey oyu, portföy + takip listesi, BIST temel analiz (İş Yatırım bilançoları, USD büyüme, kırmızı bayraklar), ABD temel analiz (SEC, analist tahmin revizyonları), gölge portföy, kural karnesi, okul modu (09–16 sessiz), ekran görüntüsünden portföy okuma.
- **Kurallar:** Ayarlar'daki değişmez kurallar + "spot, kaldıraç yok", "BIST kısa vade yok", "goalpost yasağı".
- **SSS:** "Bot benim yerime alım yapar mı? — Hayır." "Veriler anlık mı? — Kripto anlık, BIST ~15 dk gecikmeli." "Skor olasılık mı? — Hayır, kalite ölçüsü." vb.
- **İletişim:** sade form ya da e-posta bağlantısı.

---

## 8. API sözleşmesi ve örnek veriler (birebir uy)

Tüm uç noktalar `/api` altında, giriş gerektirir (cookie). Alan adları Türkçe/İngilizce karışık — **değiştirme, olduğu gibi kullan.**

```
GET  /api/auth/me                      → {id, email, name, role}
POST /api/auth/login {email,password}  → {id, email, name, role, access_token}
POST /api/auth/refresh | /api/auth/logout
GET  /api/bot/status                   → {id:"bot", last_ingest: ISO | null}
GET  /api/overview   GET /api/extras   GET /api/alerts   GET /api/positions
GET  /api/decisions  GET /api/signals  GET /api/signals/{id}
GET  /api/macro      GET /api/derivatives  GET /api/usage  GET /api/report
GET  /api/backtest   GET /api/settings     GET /api/candles/{BTC-USDT}
GET  /api/commands                     → [{type, payload:{id,...}, status:"pending"|"done", created_at}]
POST   /api/alerts {symbol, side:"long"|"short", entry, stop?, target?, note?, timeframe, cooldown}
DELETE /api/alerts/{id}
PATCH  /api/positions/{id}/stop {stop}          (409 = goalpost)
POST   /api/positions/{id}/close {price?}       (BIST'te price zorunlu, 400)
POST   /api/decisions/{id}/action {verdict:"Aldım"|"Pas"}
→ yazma uçlarının hepsi {queued:true, command:{...}} döner; bot birkaç saniye içinde işler.
```

Not: `overview`, `macro`, `usage`, `report`, `backtest`, `settings` tek belge döner (dizi olarak gelirse ilk elemanı al). `extras` henüz gönderilmediyse `{id:"extras", guncelleme:null}` döner → boş durum göster.

**`GET /api/extras` örneği (kısaltılmış):**
```json
{
  "id": "extras",
  "guncelleme": "2026-09-26T14:50:00+03:00",
  "portfoy": [
    {"ad": "KTLEV", "piyasa": "BIST", "adet": 46.198, "para": "TL", "maliyet": 1808.65, "deger": 607.97,
     "fiyat": 13.16, "gun_yuzde": -9.99, "toplam_yuzde": -66.39, "usd_yuzde": null, "tl_yuzde": null,
     "reel_yuzde": null, "temettu": 0},
    {"ad": "SHIB", "piyasa": "KRIPTO", "adet": 5047971, "para": "USD", "maliyet": 29.98, "deger": 29.88,
     "fiyat": 0.00000592, "gun_yuzde": -0.17, "toplam_yuzde": -0.34, "usd_yuzde": null, "tl_yuzde": 1.2,
     "reel_yuzde": null, "temettu": 0}
  ],
  "yogunlasma": {"uyarilar": ["BIST'te BIMAS portföyün %24'ü"]},
  "kiyas": {"portfoy_yuzde": -13.97, "kiyas": [{"ad": "BIST100", "yuzde": 4.1, "fark": -18.07, "not": null}]},
  "golge": {"TL": {"sinyal": 4, "kapanan": 2, "kazanan": 1, "acik": 2, "net": 120.5, "acik_net": -30.2, "gercek_net": 45.0, "aldigin": 1}},
  "disiplin": {"aktif": true, "seri": 0, "bekleme_bitis": null,
               "piyasa": {"KRIPTO": {"gunluk_zarar": 0, "engel": false}, "BIST": {"gunluk_zarar": 0, "engel": false}},
               "olaylar": {}},
  "gunluk": {"islem": 3, "plan_uyumu": {"stop_uygulandi": 1, "hedef": 1, "arada": 1, "gec_stop": 0},
             "satis_sonrasi": {"n": 2, "ort_5g": 1.8, "erken": 1, "iyi": 1}, "en_sik_hata": null},
  "birikim": [{"id": 1, "varlik": "BTC", "gun": 5, "tutar": 50, "para": "USD", "adet": 0.0012, "ortalama": 81000}],
  "plan_listesi": ["BTC", "SOL", "THYAO"],
  "duygu": {"korku_acgozluluk": {"deger": 62, "etiket": "Açgözlülük"}, "piyasa": {"btc_dominans": 57.3}},
  "karne": ["Hacim teyidi kuralı geçtiğinde kazanma oranı %64, kaldığında %31: kuralı koru."],
  "takip_listesi": {
    "zaman": 1790423400,
    "piyasalar": {
      "KRIPTO": [{"kod": "BTC", "fiyat": 84186, "gun_yuzde": -0.55, "hafta_yuzde": 3.7, "trend": "↗ güçlü",
                  "rsi": 64, "destek": 79182, "destek_yuzde": -5.9, "direnc": 87396, "direnc_yuzde": 3.8}],
      "BIST": [{"kod": "THYAO", "fiyat": 290.75, "gun_yuzde": 0.78, "hafta_yuzde": 1.8, "trend": "↘ zayıf",
                "rsi": 46, "destek": 290.03, "destek_yuzde": -0.2, "direnc": 294.48, "direnc_yuzde": 1.3},
               {"kod": "XYZ", "hata": "veri alınamadı"}],
      "ABD": [{"kod": "NVDA", "fiyat": 225.1, "gun_yuzde": 0.22, "hafta_yuzde": 1.3, "trend": "↗ güçlü",
               "rsi": 55, "destek": 215.6, "destek_yuzde": -4.2, "direnc": 227.9, "direnc_yuzde": 1.3}]
    }
  }
}
```
`takip_listesi.zaman` Unix saniyesidir (ISO değil). `trend` değerleri: `"↗ güçlü"`, `"→ karışık"`, `"↘ zayıf"`, `"↗"`, `"↘"`, `"az veri"`. `rsi`, `destek`, `direnc`, `gun_yuzde`, `hafta_yuzde` null olabilir.

**`GET /api/signals` elemanı:**
```json
{"id": "sig_42", "symbol": "SOL/USDT", "timeframe": "15m", "market": "KRIPTO", "currency": "USD",
 "type": "Kapanış ABOVE", "score": 3, "summary": "SOL 121 üstü kapanış; hacim teyitli, BTC kapısı açık.",
 "created_at": "2026-09-26T13:15:00+03:00",
 "analysis": {
   "panels": [{"key": "trend", "title": "Trend (15m)", "value": "Yukarı", "detail": "SMA20 üstü, SMA50 üstü"}],
   "bot_decision": {"verdict": "AL", "confidence": null, "reason": "kapanış 121.2"},
   "text": "**Karar: AL (ilk kademe)** ... \n\n🧠 Kimi K3",
   "gate": {"ok": true, "rr": 2.4, "kurallar": [{"kural": "R/R", "durum": "gecti", "detay": "2.4 ≥ 1.0"}]},
   "outcome": {"sonuc": "hedef", "cikis": 128.3, "mum": 14, "R": 2.1},
   "user_action": "Aldım"}}
```
`kurallar[].durum`: `"gecti"` ✅, `"kaldi"` ❌, `"uyari"` ⚠️. `gate` bazı eski kayıtlarda `{gecti, kurallar}` biçimindedir, `kurallar` string dizisi olabilir ("✅ R/R: 2.4 ≥ 1.0") — ikisini de işle.

**`GET /api/positions` elemanı:**
```json
{"id": "pos_13", "symbol": "AVAX/USDT", "side": "long", "market": "KRIPTO", "currency": "USD",
 "entry": 10.81, "stop": null, "target": null, "current": 10.965, "size": 2.77376, "rr": null,
 "pnl": 0.43, "pnl_pct": 1.43, "opened_at": "2026-09-26T12:00:00+03:00", "status": "open", "queued": false}
```
BIST sembolleri `KTLEV.IS`, ABD sembolleri `NVDA.US` biçimindedir; ekranda son eki at, piyasa rozetini göster.

**`GET /api/overview`:**
```json
{"id": "overview_current", "updated_at": "…", "open_positions": 13, "armed_alerts": 4, "pending_decisions": 1,
 "day_pnl": 0.87, "day_pnl_pct": 1.47, "bist_day_pnl": 73.46, "bist_day_pnl_pct": 0.53, "open_r": 0,
 "regime_score": 2, "regime_label": "RİSK-ON",
 "highlights": [{"text": "Son alarm kararı: SOL/USDT → AL (kapanış 121.2)", "tone": "up"}],
 "veri_durumu": [{"kaynak": "Binance 15m mum", "durum": "güncel", "zaman": "…", "yas": "4 dk",
                  "not": "BTC/USDT", "kapiyi_etkiler": true}]}
```
`veri_durumu[].durum`: `"güncel"` 🟢, `"eski"` 🟡, `"bayat"` 🔴, `"yok"` ⚪. `kapiyi_etkiler: true` olan bir kaynak bayat/yok ise sayfanın üstünde kırmızı bant göster: "Karar kapısını etkileyen veri eski — yeni AL verilmez."

Diğer belgelerin alanları 6. bölümde yazıldığı gibidir.

---

## 9. Yapma listesi

- Borsaya emir gönderiyormuş gibi görünen hiçbir şey (sepet, "Hemen al", kaldıraç kaydırıcısı, short butonu).
- Uydurma sayı, sahte "yapay zekâ tahmini", "%87 olasılıkla yükselir" gibi ifadeler.
- Yanıp sönen fiyat animasyonları, sürekli hareket eden ticker bandı, konfeti, oyunlaştırma.
- Ön yüzde alım-satım kararı hesaplamak (kararı bot verir; site sadece gösterir). Basit toplam/yüzde hesapları serbest.
- Açık pozisyonda stopu aşağı çekmeye izin veren form.
- İngilizce arayüz metni (teknik kısaltmalar RSI, SMA, ATR, R/R, VWAP hariç).
- API alan adlarını değiştirmek veya yeni zorunlu uç nokta varsaymak.

---

## 10. Teslim ve kabul kontrol listesi

- [ ] Tüm sayfalar 360 px mobilde yatay kaydırma olmadan çalışıyor (tablolar mobilde karta dönüşüyor).
- [ ] Koyu/açık tema, seçim hatırlanıyor.
- [ ] Her veri bileşeninde yükleniyor / boş / hata / bayat durumları var.
- [ ] Sayılar tabular, `0.00000594` gibi küçük fiyatlar ve `46.198` gibi kesirli adetler doğru görünüyor.
- [ ] Hafta sonu BIST/ABD için "Son seans" etiketi kullanılıyor.
- [ ] Yazma işlemlerinden sonra "⏳ Bota iletildi" rozeti çıkıyor ve bot işleyince kayboluyor.
- [ ] Goalpost engeli (arayüz + 409 mesajı) ve BIST kapanışında zorunlu fiyat alanı var.
- [ ] 401'de refresh deneniyor, olmazsa giriş sayfasına dönülüyor.
- [ ] `REACT_APP_MOCK=1` ile bölüm 8'deki örnek verilerle tüm sayfalar dolu görünüyor.
- [ ] Kod hesabı ("🧮") ve yapay zekâ yorumu ("🧠 model adı") görsel olarak ayrı.
- [ ] Her panel sayfasının altında "Yatırım tavsiyesi değildir. Bot işlem yapmaz." notu var.
