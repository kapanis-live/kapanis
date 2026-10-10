# Kapanış — Kripto ve BIST Karar Botu + Web Paneli

Kişisel kripto ve BIST karar destek sistemi. İşlem **açmaz**, uyarır ve kayıt tutar.
İki parçadan oluşur:

- `kriptografikbotu/` (bu klasör): Python Telegram botu. Asıl beyin. Bulutta **worker** süreci.
- `kapanis/`: FastAPI + MongoDB backend ve React panel. Botun verisini gösterir, paneldeki işlemleri bota iletir,
  kullanıcı hesaplarını (Clerk) ve her kullanıcının kendi portföyünü tutar. Bulutta **web** süreci.

GitHub: `kapanis-live/kapanis` (private, iki klasör birlikte). Bulut kurulumu: o depodaki `BULUT_KURULUM.md`.

Arayüz Türkçe ve İngilizce (kaynak metin Türkçe). Kod yorumları İngilizce.

## Güncel durum (10 Ekim 2026)

Bu bölüm 8 Ekim'den sonra eklenenleri özetler. Alttaki bölümler hâlâ geçerlidir; çeliştiği yerde bu bölüm doğrudur.

**Dil (Türkçe / English):**
- Sitede sağ üstteki isim menüsünden ya da giriş yapmadan site başlığından seçilir. Seçim hesaba yazılır (`users.dil`); bağlı Telegram komut yazmadan aynı dile geçer. `/dil tr|en` de çalışır.
- Kural: **kodda metin Türkçe kalır.** Sitede `t("Türkçe metin")` ile sarılır, İngilizcesi `frontend/src/lib/i18n.jsx` içindeki `EN` sözlüğüne eklenir. Çevirisi olmayan metin Türkçe görünür, hiçbir şey bozulmaz.
- Tek Türkçe kelimenin iki İngilizce anlamı varsa bağlam anahtarı: `t("Açık§tema")`; `§` ve sonrası gösterilmez.
- Botun ve sunucunun veriyle gönderdiği sayılı cümleler (kart uyarıları, kırmızı bayraklar, kaynak satırları, makro notu) sitede kalıpla çevrilir: `i18n.jsx` içinde `PATTERNS` / `PARTS`, kullanım `td(metin)`. **Botta böyle bir cümlenin yazımı değişirse sitedeki kalıp ve `lang.py` içindeki `DATA_PATTERNS` da değişmeli**; yoksa o cümle sessizce Türkçe kalır.
- Tasarım paketi (`frontend/src/ds/bundle.js`) kendi küçük yazılarını `kt()` ile aynı sözlükten geçirir.
- Botta: metin fonksiyonları `code="tr"` alır, İngilizcesi `text_en`. `lang.py`: `get`, `pick`, `label` (etiketler), `data` (kartların sakladığı cümleler).
- Yapay zekâ analizi: hesap English ise modele İngilizce yazması söylenir (`ENGLISH_NOTE`); çeviri adımı yoktur.
- İngilizcede hâlâ Türkçe görünenler: kapı kurallarının gerekçe cümleleri, fırsat taraması metni, Genel Bakış'taki bot notları, eski analiz kayıtları (hepsi yalnız sahibin gördüğü veriler).

**Her hesaba açılanlar** (sahibin sonucu botun kendi portföyünden; diğer hesaplarınki sitedeki Portföyüm'den):
- ABD hisselerinin ortak riski (Portföy sağlığı), günde 5.
- Hisse kartı (BIST ve ABD), günde 10.
- Aylık rapor (Karnem), istek üzerine, günde 3. Ayın ilk günü kendiliğinden hazırlanır: sahibe bot 09:30'da, pozisyonu olan diğer hesaplara site 10:00'da kuyruğa yazar (`monthly_auto_once`, hesap ve ay başına bir kez, ilk 3 gün içinde telafi eder; boş ay mesaj atmaz).
- Takip listesi (`/app/takip`): kodlar sitede durur (`watchlists`, hesap başına en çok 30 kod), satırları bot istek üzerine hesaplar (`watch.request`, günde 24, Telegram'a mesaj atmaz). Bilanço günü ve temel puan yalnız botun zaten izlediği hisselerde dolar. Takip uyarı kuralları yalnız sahipte.
- Yük sınırı: hesap başına günlük sınırın yanında bütün hesapların toplamı için de günlük tavan var (`GLOBAL_DAILY_STOCK_CARDS`, `GLOBAL_DAILY_US_BOOKS`, `GLOBAL_DAILY_MONTHLY_REPORTS`). Son 3 saatte hazırlanmış bir hisse kartı aynı hisseyi isteyen sonraki hesaba bota sorulmadan verilir (`CARD_SHARE_HOURS`); kart yalnız piyasa verisidir.
- Aylık raporda sitedeki kısmi satışlar ayrı satış satırı olarak gider (`server._monthly_rows`, `parca`).
- Yol: site isteği sunucuda kuyruğa komut olarak yazılır (girdi komutla gider), bot hesaplar, sonucu `sonuclar` içinde `<tür>:<hesap id>` kimliğiyle saklar; sunucu onu yalnız o hesaba verir. Hesap silinince sonuçlar da silinir.

**Yeni özellikler (bot):**
- `/bist kart THYAO` — BIST hisse kartı (İş Yatırım mali tabloları + Yahoo). `/abd tara`, `/bist tara` — hisse tablosu (S&P 100, BIST evreni).
- `/aylik`, `/aylik 2026-09` — aylık rapor: getiri (TL ve USD), endekslere göre fark, en çok kazandıran / kaybettiren, işlemler, yoğunlaşma.
- `/dil tr|en`.
- Karışık bildirimler piyasa anahtarını dinler: sabah brifi, pazar özeti, şirket takvimi, takip kuralları kapalı piyasanın satırlarını atlar; modele hangi piyasayı yazmayacağı söylenir. Yazılan komutlar (`/haftalik`) her piyasayı gösterir.

**Yeni özellikler (site):**
- Hisse kartı (`/app/hisse`, iki piyasa), Hisse tablosu (`/app/tarama`), Şirket takvimi (`/app/takvim`), Karnem'de aylık rapor.
- Takip listesinde güç / bilanço günü / temel puan sütunları.
- Tanıtım sayfaları, giriş ve kayıt İngilizce de açılır.
- İlk girişte portföy eklemeden bakılabilecek sayfalar kartı.

**Bilinen açıklar:** dil ve "her hesaba açılanlar" canlıda gerçek ikinci hesapla denenmedi. Sabah brifinde modelin kapalı piyasayı gerçekten yazmadığı denenmedi (talimat veriliyor). Uygulama bildirimi gerçek telefonda doğrulanmadı.

## Önceki durum (8 Ekim 2026)

Bu bölüm 28 Eylül'den sonra eklenenleri özetler. Alttaki "28 Eylül 2026" bölümü hâlâ geçerlidir; çeliştiği yerde bu bölüm doğrudur.

**Ürünün yönü:** karar desteği. Bot işlem yapmaz, AL/SAT demez. Öneri olarak yalnız geçmiş veri testinden geçen kural gösterilir; test edilmemiş ya da testten kalan her şey "bilgi" etiketiyle gelir. Bütün test sonuçları: `research/README.md`.

**Test özeti (hepsi maliyet düşülerek, rastgele girişle ve al-tut ile kıyaslanarak):**
- Geçen tek kural: **ay dönümü** (ayın son 2 + ilk 3 işlem günü), kripto ve BIST'te. ABD'de (S&P 100) geçmedi.
- Trend takibi: araştırmada (kilitli yılda rastgeleyi geçemedi). Diğer 7 günlük kural: reddedildi. ABD'de 9 kuralın 9'u reddedildi; al-tut açık ara önde.
- Gün içi 6 aday (kırılım-retest, likidite süpürme, VWAP geri alışı...): reddedildi.
- Destek/direnç: 3 çizim yöntemi (pivot, hacim profili, tepki filtreli) × 5 olay, rastgele seviyelerle kıyas: hiçbiri sıfırın üstünde değil. Kırılım sonrası retest rastgeleden tutarlı biçimde iyi ama maliyet sonrası yine eksi; taze yılda da kaldı.
- "Çok dokunulan seviye zayıftır", "FVG mıknatıstır", 7 şartlı "güven puanı": veride desteklenmedi. Güven puanı ters çalıştı (çok şart = daha kötü sonuç).
- Stop mesafesi: 15 dk ATR'ye göre 1 ATR'lik stop 24 saatte %89 değiyor, değenlerin %82'si girişin üstüne dönüyor. Hiçbir mesafe kırılım girişini kârlı yapmadı.
- Bilanço sonrası sürüklenme (ABD, SEC tarihleriyle): iyi tepkiden sonra piyasanın üstünde getiri yok.
- Açık pozisyon (OI) değişim hızı: test edilemedi (borsa 30 gün veri tutuyor); `oi_store.py` veriyi biriktiriyor.

**Yeni özellikler (bot):**
- `/seviye` — 30 dakikada bir destek/direnç taraması (60 coin, BIST evreni, S&P 100). Kapanan mumda: direnç kırıldı, destek kırıldı, destekte tutundu, dirence takıldı. Telegram'a özet, siteye "BİLGİ" kaydı. Coin kayıtlarında 7 şartlı puanın geçmişte ne yaptığı yazar. ABD kayıtlarında bilanço riski kuralı var.
- `/midas`, `/midas yok STX`, `/midas var STX` — Midas'ta alınamayan coinler taramalara girmez.
- `/bildirimler`, `/kripto ac|kapat`, `/bist ac|kapat`, `/abd ac|kapat` — piyasa bazlı otomatik bildirim anahtarları. Varsayılan: kripto kapalı, BIST ve ABD açık. Kapalı piyasadan otomatik mesaj gelmez; komutlar çalışır, alarmlar silinmez, bastırılan mesaj sonradan gönderilmez.
- `/abd kart NVDA` — ABD hisse kartı: trend, SPY/QQQ/sektöre göre güç, bilanço tarihi ve riski, son bilanço tepkisi (bağlam), analist tahmin revizyonu, temel puan, kaba değerleme etiketi, her sayının kaynağı ve tarihi. Her kart denetim kaydına yazılır.
- `/abd portfoy` — ABD portföyü: sektör ve tema dağılımı, korelasyon, beta, dört senaryo (SPY −%10, QQQ −%10, 10Y faiz +0,50, VIX 30). Cetvel, tahmin değil.
- ABD takvimi her yıl için hesaplanır (tatiller, 13:00 kapanışları, premarket / seans / after-hours, Türkiye saati iki saat diliminden).
- `/portfoy` paralel hesaplanır; "Sat" düğmesi yerine "Sil" (satış sayılmaz, K/Z'ye girmez).
- Uygulama bildirimi: botun Telegram'a attığı her otomatik mesaj, bildirimi açık cihazlara da gider (Web Push).

**Yeni özellikler (site):**
- Sinyaller sayfası: 30 dakikalık seviye kayıtları "BİLGİ" rozetiyle; AL etiketi ve Aldım/Pas düğmesi yok.
- Stratejiler: laboratuvar tablosunda ABD satırları; ay dönümü kartında "ABD'de geçmedi".
- ABD hisse kartı sayfası (`/app/abd`); Portföy sağlığında ABD hisselerinin ortak riski (yalnız sahibe).
- Ayarlar: üç piyasa bildirim anahtarı. Hesap: bu cihazda uygulama bildirimi aç/kapat ve test düğmesi.
- Sağ üstte isme basınca menü (hesap, alarmlar, bot ayarları, çıkış). A−/A+ yazı boyutu düğmesi kaldırıldı.
- Mobil: cam görünümlü yüzen alt çubuk, kayan vurgu, yönlü sayfa geçişi; çevrimdışı ekranı; uygulama yeni sürümde kendini yeniler.

**Android:** Trusted Web Activity paketi (`live.kapanis.twa`, sürüm 1.2.0). Play Store'da değil; APK doğrudan kurulur. İmza anahtarı depoda değildir.

**Depo:** GitHub `kapanis-live/kapanis` (organizasyon, gizli).

**O gün bilinen açıklar (ilk ikisi 10 Ekim'de kapandı):** karışık içerikli bildirimler (sabah brifi, haftalık özet, şirket takvimi, takip kuralları) piyasa anahtarına bağlı değil. ABD portföy bölümü yalnız sahip için. Uygulama bildirimi gerçek telefonda henüz doğrulanmadı. Analist tahmin geçmişi ve hisse saatlik verisi ücretsiz kaynaklarla sınırlı.

## Önceki durum (28 Eylül 2026)

**Yayın:** kapanis.live canlı (Google Cloud VM, Docker: web + worker + Caddy). Giriş Clerk production (Google, e-posta + şifre, e-posta kodu). Veri MongoDB Atlas. Güncelleme: kod GitHub'a (`kapanis-live/kapanis`), sonra VM'de Google Cloud SSH penceresinden `bash ~/guncelle.sh`. Site görünümü değiştiyse önce `build-new.tgz` "Upload file" ile yüklenir.

**Güvenlik:** bot uçları (`/api/bot/*`, `/api/ingest/*`, `/api/commands/pending`) internetten kapalı (Caddy 404 + `X-Kapanis-Public` işareti); worker web'e iç ağdan (`http://web:8001`) bağlanır. Hız sınırı: IP başına dakikada 180 istek, kullanıcı başına dakikada 40 grafik, en fazla 3 canlı bağlantı. Güvenlik başlıkları (HSTS, iframe yasağı, nosniff). Her gece 03:30 veritabanı yedeği (`db_backup.py`, 14 gün, geri yükleme `scripts/restore_backup.py`).

**Kanıt kuralı:** öneri olarak yalnız geçmiş veri testinden geçen kural gösterilir (maliyet düşülür, dönem ikiye bölünür, batan coinler dahil edilir, al-tut ve aynı sürede rastgele gir-çık ile karşılaştırılır). Testler `research/` klasöründe, sonuçlar `research/README.md`.
- Direnç kırılımında AL: işlem başı −0,21R, rastgeleden farksız → **otomatik AL önerileri kapalı** (`config.BUY_SIGNALS`, varsayılan kapalı). Plan teyidi/tarayıcı/BIST-ABD AL kartları yerine bilgi notu gelir.
- Destek/direnç bölgeleri: rastgele seviyeden farksız → yalnız bilgi, karar gerekçesi değil.
- Momentum rotasyonu: batan coinler dahil edilince çöktü → eklenmedi.
- **Kripto trend takibi** (günlük kapanış 20 günün tepesi + 200 günlük ortalama üstü → gir; 10 günün dibi altı → çık): Strategy Engine 2.0 testinde (son 12 ay kilitli) durumu **ARAŞTIRMA**: geliştirme döneminde rastgele zamanlamayı geçti, kilitli dönemde fark ölçülemedi. Kazandırdığı kanıtlanmadı; asıl etkisi düşen piyasada dışarıda kalmak. Sitede bilgi ve alarm olarak sunulur, "kanıtlanmış" denmez. Canlı karnesi tutulur (geriye dönük doldurma yok).
- **Strategy Engine 2.0** (`research/engine.py`, `regime.py`, `strategies.py`, `run_v2.py`): her aday aynı standartla (maliyet, batan coinler, kilitli son 12 ay, al-tut ve 20 rastgele eşle karşılaştırma, yıllık dilimler, rejime göre işlem sonuçları). Denenenler: trend içi geri çekilme, sıkışma kırılımı, göreli güç, yatayda dönüş → kripto ve BIST'te hepsi ELENDİ. Sonuçlar sitede Strateji Laboratuvarı'nda (`kapanis/backend/lab_results.json`).

**Yeni özellikler (bot):** `/sessizlik` (bildirim gelmeyecek saatler, düz yazıyla: "hafta içi 12.00-14.30 arası bildirim atma"; biriken bildirimler sonra tek özet), `/sessiz` (hiç bildirim; `/plan` ile açılır), `/plan 45dk` (plan güncellemesi aralığı), `/ne ASTOR` ("ne yapayım": adetli plan, test edilmiş çıkış seviyesiyle), satışta gerçek fiyat ve tarih (`/sat ID FIYAT dün`), eski "Sattım @" düğmesi önce fiyat sorar, sinyal kartında canlı durum (aktif / geç kaldın / süresi doldu / geçersiz), ATR stopu zorunlu, stop sonrası 4 saat bekleme. Sesli komut kaldırıldı. `/okul` yerine `/sessizlik`.

**Yeni özellikler (site):**
- Alarmlarım: fiyat, RSI ve trend alarmları, yalnız mum kapanışında; portföy pozisyonlarının stop/hedef ve trend çıkış uyarıları kendiliğinden. Bağlı Telegram'a gider.
- Grafikten alarm: grafikte fiyata tıkla ya da destek/direnç seç.
- Haftalık özet: pazar 20:00 Telegram.
- Strateji Kurucu: kanıt tablosu, 30 coinin trend durumu, "Haber ver", canlı karne; BIST filtresi "test edilmedi" etiketli.
- Karnem: kendi kapattığın işlemlerden isabet, ortalama kazanç/kayıp, tutma süresi, stop altı satışlar, satış sonrası hareket.
- Portföy sağlığı: ağırlık (TL), tepeden düşüş, trend durumu, birlikte hareket edenler, uyarılar.
- 404 sayfası.

## Değiştirilemez kurallar

Yeni özellik bu kuralları bozmamalı:

1. **Dokunma ≠ kapanış.** Hiçbir sinyal mum içi high/low ile tetiklenmez; sadece kapanmış mumun kapanış fiyatı.
2. **Goalpost yasağı.** Açık pozisyonda stop aşağı çekilemez. Kodla engellenir (`positions.update`, `conversation_store.apply_update`, web backend 409).
3. **Spot, kaldıraçsız.** Kripto bütçesi ~100 USD; ilk kademe normalde 25 USD, RİSK-OFF'ta 15 USD. BIST bütçesini kullanıcı Telegram'dan `/bist butce 5000` ile girer; ilk kademe en fazla bütçenin %25'i, planlanan işlem stop riski en fazla %2'sidir. Bütçe girilmeden BIST AL sinyali verilmez.
4. **Kesinlik dili yok.** "Kesin kazanç" gibi ifade yok; yatırım tavsiyesi değildir.
5. **Sayılar ve kararın kendisi kodla verilir, LLM hesaplamaz.** `gate.py` KALDI derse DeepSeek AL diyemez; kapının sonucu her analizin altına eklenir. İndikatör, R/R, rejim skoru, destek/direnç, haber etiketi hep Python'da. DeepSeek sadece yorumlar.
6. **Veri uydurma yok.** Veri yoksa "doğrulanamadı".
7. **Ücretsiz altyapı.** Ücretli indikatör/haber API'si yok. Tek ücretli servis DeepSeek.

## Bot mimarisi

| Dosya | Görev |
|---|---|
| `main.py` | Telegram komutları, butonlar, zamanlanmış işler (15 dk kontrol, sabah brifi 08:30, okul raporu 16:05, veri takvimi uyarıları, web senkronu) |
| `config.py` | Tüm ayarlar ve `.env` okuma. Veri klasörü `data/` |
| `market.py` | Binance spot REST, indikatörler (SMA20/50/200, RSI14 Wilder, ATR14 Wilder, Volume MA20, günlük VWAP), destek/direnç bölgeleri, coin özeti |
| `derivatives.py` | Binance vadeli: funding, açık pozisyon, long/short, baz |
| `macro.py` | FRED (likidite, dolar, faiz, VIX, rejim skoru), BLS (CPI/NFP), CFTC COT, veri takvimi |
| `news.py` | Ücretsiz RSS haberleri; kaynak güvenilirliği ile kripto ilgisi **ayrı** ölçülür |
| `llm.py` | Üç model 15 dakikalık dilimlerle sırayla: Kimi K3 → DeepSeek V4.1 Flash (`deepseek-flash`, .env DEEPSEEK_MODEL ile değişir) → GLM 5.3 (Kimi ve GLM NVIDIA API'den, `NVIDIA_API_KEY`). Biri hata verirse sıradaki cevap verir; cevabın altında 🧠 model adı. Kimi/GLM'e sistem kurallarına ek olarak PROJE.md, uzun sohbet geçmişi ve son kararlar/işlemler gider (büyük bağlam). `/model` ile sabitlenebilir. Cevaptaki `<STATE>` bloğundan planları kaydeder. qwen3 (Ollama) ön filtresi opsiyonel |
| `system_prompt.py` | Botun kuralları ve üslubu; sonuna `ornek_analizler.md` eklenir (DeepSeek önbelleği için sabit önek) |
| `gate.py` | Kripto karar kapısı ve "Aldım" yönlendirmesi. BIST kararları `bist_signals.py` kapısından geçer |
| `scanner.py` | Otomatik tarayıcı: 13 coinde 4h/1d direnç bölgesinin hacimli 15m kapanışla kırılmasını arar, otomatik plan kurar (🤖). Sonraki mum tutarsa `gate.py` karar verir → 🟢 ŞİMDİ AL. Tarama DeepSeek kullanmaz |
| `bist.py` | Yahoo'dan kapanmış BIST mumları, BIST 100 ve USD/TRY, seans ve tatil takvimi, TL adet/bütçe kuralları |
| `bist_signals.py` | BIST 30'da hacimli direnç kırılımı ve trend içi geri çekilme; günlük aday, sonraki seansta saatlik teyit, ayrı karar kapısı |
| `exits.py` | Portföy çıkış/tepe analizi (kripto 4h, BIST günlük): TUT / KISMİ SAT / SAT, olası tepe bölgesi, iz süren stop ve başa baş önerisi (sadece yukarı). DeepSeek kullanmaz |
| `watcher.py` | 15 dk'da bir plan kontrolü (tetik/teyit/iptal/hedef), "ŞİMDİ AL" kural listesi, pozisyon stop/hedef takibi |
| `alert_engine.py` | Binance WebSocket; sadece `x: true` kapanmış mumda kapanış alarmı |
| `alerts_store.py` | `alerts.json`, `settings.json` (sessiz saat, okul modu) |
| `positions.py` | `positions.json`, `decisions.json` (karar günlüğü), son backtest |
| `conversation_store.py` | `history.json` (diskte son 100 tur; DeepSeek'e son 15 tur gider), `state.json` (planlar) |
| `charts.py` | mplfinance grafik: mum+SMA, RSI, ATR, hacim |
| `backtest.py` | Kapanış bazlı backtest ve karar sonucu değerlendirme |
| `costs.py` | DeepSeek token/TL takibi (`usage.jsonl`), yoğun/indirimli tarife |
| `corporate.py` | BIST bedelsiz/bölünme (açık pozisyon, alarm ve planları otomatik ölçekler), temettü geliri ve geçen yılın tarihlerinden tahmin; USD/TRY ve TÜFE (EVDS, opsiyonel anahtar) ile dolar ve enflasyon bazlı getiri |
| `discipline.py` | Disiplin kalkanı: üst üste 2 zarar = 24 saat yeni AL yok, günlük zarar bütçenin %3'ünü geçerse o piyasada gün biter. İki kapıda da `disiplin` kuralı |
| `sentiment.py` | Korku & Açgözlülük (alternative.me), BTC/ETH dominansı ve stablecoin payı (CoinGecko). ≥80'de ilk kademe küçülür; tek başına sinyal değil |
| `risk.py` | Yoğunlaşma (varlık %40, sektör %50), 30 günlük korelasyon, pozisyonlardan geriye dönük portföy değeri |
| `journal.py` | İşlem günlüğü: alış/satış nedeni, plana uyum (fiyattan ölçülür), en sık hata |
| `dca.py` | Birikim planları: aylık hatırlatma, "Aldım" ile kayıt, düşüşte ayda bir ekstra kademe önerisi |
| `assets.py` | Altın/döviz portföy varlıkları (piyasa `DIGER`, TL): gram altın = GC=F × USD/TRY ÷ 31,1035, dolar, euro. TUT/SAT verilmez. TEFAS desteklenmez (site otomatik isteği engelliyor) |
| `benchmark.py` | Kıyas: portföy vs BIST 100, BTC, gram altın, dolar, mevduat (`/kiyas faiz 45`), aynı tarihlerle ve TL maliyet ağırlıklı. Satış sonrası 5/20 gün takibi |
| `shadow.py` | Gölge portföy: kapıdan geçen her ŞİMDİ AL'ı aynen alsaydın (kapanışla, komisyon/kayma düşülmüş), gerçek sonucunla yan yana |
| `risk_news.py` | Riskli haber alarmı: Binance delist/izleme duyuruları, kripto RSS ve BIST Google News; eldeki/listedeki varlık + risk kelimesi. DeepSeek yok |
| `eod.py` | BIST gün sonu raporu (18:45): kapanış, hacim, SMA, RSI, destek/direnç, plan ve pozisyon durumu |
| `model_score.py` | Model karnesi: konsey oyları ve alarm yorumlarını yazan model, kapanışla sonuçlanan kararlara göre puanlanır (`/karne`) |
| `strength.py` | BIST haftalık güç sıralaması (~200 hisse, haftalık kapanış: 13/26 hafta endekse göre güç, 52h zirveye uzaklık, hacim, trend) ve sektör rotasyonu; cuma 19:00 ve `/guc` |
| `pf_alarm.py` | Portföy alarmı: piyasa başına bakiye (varlık + nakit) şimdiye göre %X ya da bir seviyeyi geçince bir kez haber verir (`/palarm`, 15 dk) |
| `watchlist.py` | Takip listesi (kripto/BIST/ABD, `settings.json` → `takip_listesi`). Otomatik analiz YOK: 30 dk'da bir sessizce "bakmak ister misin?" sorar (`/takip`, `/takip aralik`, 08:00 öncesi/sessiz saatte sormaz, cevapsız eski soruyu siler). Tek/çoklu seçim → 📊 kodla hızlı durum (fiyat, gün/hafta %, SMA50/200 trendi, RSI, en yakın destek/direnç) veya 🧠 analiz (tek kod: o piyasanın tam motoru; çoklu: [TAKİP] karşılaştırma). Panel: extras.takip_listesi (30 dk önbellek, `data/takip_durum.json`), Tiingo kotası kullanılmaz |
| `structure.py` | Kripto karar motoru (kodla): rejim, HH/HL/LH/LL yapı + BOS/CHoCH, likidite (önceki gün/hafta tepe-dip, eşit tepe/dip, süpürme), hacim profili POC/VAH/VAL, MACD, Bollinger sıkışması, RSI uyumsuzluğu, konfluens /100 (kalite, olasılık değil), BIST için Weinstein Stage. `market.snapshot` → `teknik_motor`; kapıda `yapı (4h)`, `konfluens`, `likidite` bloklamayan kurallar |
| `fundamentals.py` | BIST yatırım motoru: İş Yatırım mali tabloları (ücretsiz), TTM, USD bazlı büyüme, marjlar, FCF, net borç/FAVÖK, faiz karşılama, ROE, F/K, FD/FAVÖK, PD/DD, FCF verimi, bankalara ayrı metrik, kırmızı bayraklar, skor (katalizör/yönetim hariç). `/temel`, `/incele` verisi (`BIST_TEMEL`), `/guc` ilk 10'a skor |
| `us.py` | ABD hisseleri: fiyat Tiingo (`TIINGO_API_KEY`, günlük 900 istek / saatte 45 sembol sayacı) yoksa Yahoo; NYSE takvimi (2026 tatiller, yarım günler); kapı SPY/QQQ (200G + 50G>200G), VIX, 10Y, DXY; teknik (aylık/haftalık/günlük trend, 50/200G, 10 haftalık, 52h zirve, RS SPY/QQQ/sektör ETF, Stage, volatilite daralması, birikim hacmi, bilanço boşluğu). Semboller `AAPL.US`, piyasa `ABD`, USD |
| `us_fund.py` | ABD yatırım motoru: SEC EDGAR companyfacts (resmi, ücretsiz; etiket değişimlerini birleştirir, YTD'den çeyrek türetir) + Yahoo quoteSummary (EPS tahmin trendi 30/90g, revizyon sayıları, sürprizler, sonraki bilanço, ileri F/K, PEG, açığa satış, insider, kurumsal). Büyüme/ivme, marjlar, FCF, SBC/seyreltme, geri alım, hissedar getirisi, ROE/ROIC, net nakit, değerleme, Rule of 40, uyarılar, patlama listesi, 100 puan skor + durum. Guidance ücretsiz veride yok |
| `us_signals.py` | ABD plan takibi ve kapı (günlük kapanış; endeks kapısı, haftalık trend, bilançoya 5 gün kala giriş yok, R/R≥2, disiplin, `/abd butce` kademe/risk), günlük kapanış alarmları, haberler, yapay zekâ verisi |
| `web_sync.py` | Web panel köprüsü: bot verisini panel şemasına çevirip `/api/ingest` ile gönderir, panel komutlarını uygular |

Veri: `data/` klasöründe JSON dosyaları. Veritabanı yok (bot tarafında).

### Portföy, disiplin ve uzun vade

- Uzun vadeli varlıklar (birikim alımları ve `/portfoy` ile içe aktarılanlar) kısa vade kademe limitine ve disiplin kalkanına girmez (`positions.is_trade`). Birikim alımlarına TUT/SAT uyarısı gönderilmez.
- Zamanlanmış işler: 09:45 bölünme/temettü kontrolü (başlangıçta da bir kez), 10:15 birikim hatırlatması, pazar 20:00 haftalık özet (metin + grafik + tek DeepSeek yorumu).
- Stopu aşağı çekme denemesi ve SAT kararına rağmen tutma kural olayı olarak kaydedilir; `/rapor`, `/disiplin` ve haftalık özette görünür.
- Portföy sihirbazı: ~200 BIST hissesi ve popüler coinler (günde bir Yahoo/Binance ile doğrulanır, `universe.py`), sayfalı ve çoklu seçim. `/bakiye`: piyasa başına ayrı bakiye (varlık + nakit) ve bugün/hafta/toplam K/Z (`balance.py`).
- Komutlar: `/hesap`, `/grafik`, `/risk`, `/duygu`, `/disiplin`, `/gunluk`, `/haftalik`, `/birikim`, `/temettu`.
- 📸 Ekran görüntüsü: aracı kurum/borsa portföy ekranı Kimi K3 ile okunur (`llm.read_holdings`, boş cevapta 4 deneme), onayla portföye eklenir. GLM 5.3 NVIDIA'da görsel kabul etmiyor.
- Konsey: kapıdan geçen her ŞİMDİ AL'da (kripto ve BIST) üç model arka planda oy verir (`llm.council`), oylar karara kaydedilir.
- ABD: `/abd`, `/abd AAPL`, `/temel AAPL`, `/abd guc` (S&P 100, cumartesi 10:00), `/abd butce`, New York kapanışından sonra (16:20 ET) plan/alarm işi.
- Ek komutlar: `/golge`, `/kiyas`, `/gunsonu`, `/karne` (kural karnesi: `gate.rule_advice`, kurallar otomatik değişmez). Düz yazıyla kapanış alarmı ("THYAO 300 üstünde kapanırsa haber ver") onay butonuyla kurulur.
- İçe aktarılan varlıkların alış tarihi bilinmez: `/duzelt ID tarih=2025-03-01` girilene kadar dolar/enflasyon getirisi ve kıyasa girmez.
- Zamanlanmış işler: 18:45 BIST gün sonu, 19:00 satış sonrası kontrolü, 30 dk'da bir riskli haber, 15 dk'da bir panel `extras` dokümanı (web panelde "Portföy & Disiplin" sayfası, `kapanis/frontend/src/pages/panel/Portfolio.jsx`).

### BIST akışı

- `/bist butce 5000`: BIST'e ayrılan TL bütçesini kalıcı kaydeder/değiştirir; kademe, adet ve stop riski yeni değerden hesaplanır. `/bist`: bütçe, endeks kapısı, aday/pozisyon durumu. `/incele THYAO`: hisse analizi (`/bist THYAO` da çalışır; `/analiz THYAO` BIST'e yönlendirir). `/bist tara`, `/bist kapat`, `/bist ac`: günlük tarayıcı.
- `/bist backtest THYAO 320 stop=300 hedef=360 gun=90`: son 180 güne kadar kapalı saatlik mumlarda verilen fiyat seviyesini, maliyet sonrası net R ile sınar. Bu test günlük strateji ve BIST 100 kapısının tarihsel performansı değildir.
- BIST orta/uzun vadedir (`config.BIST_CONFIRM_TF = "1d"`): haftalık kapanış haftalık SMA20 üstünde olmalı, aday sonraki günlerin KESİN günlük kapanışıyla (18:35 işi, `bist_signals.daily_check`) doğrulanır, stop ≥ 1,5 günlük ATR, hedef ≥ %8, net R/R ≥ 2. Çıkış kararı haftalık kapanışla (`exits.frames`), stop/hedef takibi günlük kapanışla (`watcher`). Eski kısa vade modu için `BIST_CONFIRM_TF = "1h"`.
- Tarama hafta içi 18:35'te kapanmış günlük mumlarla çalışır. Veri yaklaşık 15 dakika gecikebilir; emir fiyatı aracı kurumdan kontrol edilir.
- Kod kapısı seans, veri güncelliği, günlük trend, BIST 100'e göre 20 günlük güç, hacim, maliyet sonrası R/R ≥ 1,5, tavan/boşluk, BIST 100 yönü, tam adet ve azami %2 stop riskini denetler. BIST 100 kapalıysa AL vermez. DeepSeek yalnız geçen sinyale kısa yorum ekler.
- `Aldım` işlemi TL ve tam adetle pozisyon açar. Elle gerçek alım `/bist aldim THYAO 320 4 stop=300 hedef=360` ile kaydedilir. Gerçek fiyat veya adet farklıysa `/duzelt ID giris=FIYAT adet=N`. Satış gerçek fiyatla `/sat ID FIYAT`; panelde de gerçekleşen satış fiyatı gerekir.
- BIST 30 ve tatil listeleri 2026 sonuna kadar geçerlidir. 2027 listesi/takvimi girilene kadar otomatik BIST sinyali durur.

## Web panel mimarisi

- `kapanis/backend/server.py`: FastAPI. Panel verisi MongoDB'den okunur.
- Giriş (`identity.py`, `AUTH_MODE`):
  - `legacy`: bu bilgisayardaki tek yönetici şifresi.
  - `clerk`: Google, e-posta + şifre, e-posta doğrulama kodu.
  - `both`: ikisi birlikte.
  - Clerk jetonu imza (JWKS), süre, issuer ve izinli site ile doğrulanır. E-postası doğrulanmamış hesap kabul edilmez. Şifreler Kapanış'ta tutulmaz.
- Roller:
  - **Sahip** (`OWNER_EMAIL` ya da yerel yönetici): botun portföyü, sinyaller, alarmlar, ayarlar.
  - **Kullanıcı**: kendi portföyü (`user_api.py`: `portfolios` = nakit, pozisyonlar, işlemler), piyasa sayfaları, kendi analizleri. Günde `USER_DAILY_ANALYSES` analiz hakkı.
  - Sahibe özel uç noktalar diğerlerine 403 döner.
- Bot → web: `POST /api/ingest/{collection}?replace=true` (`X-Bot-Key` başlığı, kullanıcı oturumundan ayrı).
- Web → bot: paneldeki işlemler veriyi değiştirmez, `commands` kuyruğuna yazılır (`user_id`, `request_id`, `role`, `telegram_chat_id` ile).
  - Bot `GET /api/commands/pending` ile 15 sn'de bir alır, uygular, `POST /api/commands/{id}/done` der.
  - Sahip olmayan kullanıcının komutu yalnız `analysis.request` olabilir.
  - Analiz `personal=False` ile çalışır: sahibin planı, pozisyonları ve sohbet geçmişi prompt'a girmez, geri yazılmaz.
  - Sonuç yalnız o kullanıcının `analyses` kaydına ve (bağlıysa) kendi Telegram'ına gider.
- Telegram bağlama: sitede tek kullanımlık kod (10 dk, hash'li) → bota `/bagla KOD` → `users.telegram_chat_id`.
  Sahibin kişisel bildirimleri `ALLOWED_CHAT_ID`'ye gider.
- `kapanis/frontend/src`: React 19 + Create React App/craco (Vite değil) + Tailwind + Claude Design "Kapanış" tasarım sistemi (`src/ds`).
  - Sayfalar `pages/panel/*`, tanıtım `pages/public/*`, API `lib/api.js`.
  - Clerk: `@clerk/react`. Publishable key tarayıcıya çalışırken `/api/auth/config` ile gelir; derleme gerekmez.
- Tasarım: koyu/açık tema, büyük yazı (A−/A+), renk yalnız anlam için (yeşil yükseliş, kırmızı düşüş, sarı bekle).

## Çalıştırma

**Bu bilgisayar**
1. MongoDB yerel servis (`mongodb://127.0.0.1:27017`).
2. `.env` dosyalarını doldur: `kriptografikbotu/.env` (`.env.example`) ve `kapanis/backend/.env` (`.env.example`).
3. Masaüstündeki `KAPANIS-BASLAT.bat`:
   - MongoDB, panel API'si ve bot açılır.
   - Arayüz değiştiyse derlenir.
   - Panel http://localhost:8001/app adresinde.
   - Durdurmak için `KAPANIS-DURDUR.bat`.
4. Telefon: Tailscale ile `https://gesellschaft.tailf4d432.ts.net/app`.

**Bulut** (bilgisayar kapalıyken): tek Docker imajı, `web` + `worker`, MongoDB Atlas (Frankfurt), Render ya da Linux VPS.
- Adımlar: `BULUT_KURULUM.md`.
- Botun `data/` klasörü Atlas'a `scripts/import_data_to_atlas.py` ile aktarılır.
- Bulutta `cloud_store.py` onu dakikada bir yedekler.

Python 3.11, Node 20+.
- Bot bağımlılıkları: `requirements.txt`.
- Panel backend'i: `kapanis/backend/requirements.txt` (buluttaki sade liste: `requirements.cloud.txt`).
- Panel frontend'i: `kapanis/frontend/package.json` (`npm install --legacy-peer-deps`).

## Yeni özellik eklerken

- Mevcut kod stiline uy: kısa fonksiyonlar, Türkçe kullanıcı metni, İngilizce yorum.
- Yeni sayısal kontrol → Python'da hesapla, DeepSeek'e hazır sonuç ver.
- Yeni Telegram komutu → `main.py` içinde `@authorized` handler + `HELP` metni + gerekirse `BOT_MENU`.
- Panelde yeni veri → `web_sync.py` içinde `build_*` fonksiyonu + backend `INGEST_COLLECTIONS` + frontend sayfası.
- Panelde kullanıcıya özel veri → her sorguda oturumdaki `user["id"]` ile filtrele; kimliği istekten okuma.
- Sahibe özel bir şey ekliyorsan backend'de `require_owner`, frontend'de `own(...)` rota koruması kullan.
- `.env`, `.env.atlas`, `data/`, loglar, `.venv`, `node_modules` asla paylaşılmaz ve commit edilmez.


## Kripto ↔ BIST eşitliği
- Analiz: `/analiz BTC` ↔ `/incele THYAO` (çoklu zaman dilimi, destek/direnç, haber, makro/endeks kapısı)
- Alarm: `/new_alert` (Binance websocket, 15m…) ↔ `/bist alarm THYAO ABOVE 300 1h|1d` (Yahoo, kapanış; `.IS` alarmları websocket'e girmez)
- Tarayıcı + ŞİMDİ AL: `scanner.py` ↔ `bist_signals.daily_scan/hourly_check` (grafik + kod kapısı + Aldım/Pas)
- Haber: RSS (`/haber`) ↔ Google News TR (`/bist haber`)
- Portföy ve çıkış: `/portfoy` ortak; `/bist portfoy` sadece BIST. Kısmi satış: `/sat ID FIYAT adet=N|yuzde=50`
