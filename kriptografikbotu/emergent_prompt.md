# KriptoKapı — emergent.sh için site prompt'u

> Kullanım: "ANA PROMPT" bölümünün tamamını ilk mesaj olarak yapıştır. Site oluştuktan sonra
> "DEVAM PROMPTLARI" bölümündeki mesajları sırayla, her biri bitince tek tek gönder.
> Prompt oluşturucular tek seferde her şeyi mükemmel yapamaz; parça parça daha iyi sonuç verir.
> "KriptoKapı" geçici isim — değiştireceksen iki bölümde de değiştir.

---

## ANA PROMPT

"KriptoKapı" adında bir kripto teknik analiz platformu inşa et. Bu platform, arkada çalışan bir Telegram botunun (Binance verisi + DeepSeek yapay zekâ analizi + FRED/BLS/CFTC makro verisi) web yüzüdür. İki bölümden oluşur:

1. **Halka açık tanıtım sitesi** (`/`, `/ozellikler`, `/nasil-calisir`, `/kurallar`, `/sss`, `/iletisim`)
2. **Giriş gerektiren uygulama paneli** (`/app/...`)

Arayüz dili tamamen Türkçe. Tema tamamen siyah. Hedef his: profesyonel trading terminali (TradingView + Bloomberg Terminal + Linear'ın sadeliği). Gösterişli değil, güven veren, yoğun ama nefes alan.

Şimdilik backend yok. Tüm veriyi aşağıda tanımlanan TypeScript tipleriyle birebir uyumlu, gerçekçi mock veriyle doldur. Veri erişimini tek bir `src/lib/api.ts` katmanında topla; her fonksiyon Promise döndürsün ve 300–600 ms sahte gecikme içersin. `VITE_API_URL` ortam değişkeni tanımlıysa mock yerine gerçek REST uç noktalarını çağırsın (uç nokta listesi aşağıda).

### 1. Marka ve tasarım sistemi

**Renkler (CSS değişkeni olarak tanımla):**
- `--bg`: #000000 (sayfa)
- `--surface`: #0A0A0A (kart)
- `--surface-2`: #111111 (kart içi alan, input)
- `--border`: #1F1F1F, hover'da #2A2A2A
- `--text`: #EDEDED, `--text-2`: #8A8A8A, `--text-3`: #555555
- `--up` / AL / hedef: #26A69A
- `--down` / İPTAL / stop: #EF5350
- `--warn` / BEKLE: #F5C518
- `--info` / TETİKLENDİ: #2196F3
- SMA renkleri: SMA20 #F5C518, SMA50 #2196F3, SMA200 #E040FB
- Vurgu rengi yok; tek vurgu beyazdır (#FFFFFF birincil butonlar: beyaz zemin, siyah yazı).

**Tipografi:**
- Metin: Inter (400/500/600). Başlıklar sıkı harf aralığı (-0.02em).
- Tüm fiyat, yüzde, token, TL/USD değerleri: JetBrains Mono, `font-variant-numeric: tabular-nums`.
- Boyutlar: sayfa başlığı 28px, kart başlığı 13px büyük harf #8A8A8A letter-spacing 0.06em, büyük metrik 32px mono, tablo 13px.

**Sayı ve zaman biçimi:**
- Ondalık ayırıcı nokta, binlik ayırıcı ince boşluk: `84 350.25`. Tüm sitede aynı.
- Coin'e göre ondalık: BTC 2, ETH 2, NEAR 3, ONDO 4. Yüzdeler 2 ondalık ve işaretli: `+1.24%`.
- Para: `+1.24 USD`, `3.12 TL`. Pozitif yeşil + ▲, negatif kırmızı + ▼. Renk asla tek başına anlam taşımaz; her zaman ok veya işaret de olur.
- Tüm saatler Europe/Istanbul, 24 saat: `25.09 21:15`. Göreli zaman tooltip'te: "12 dk önce".

**Bileşenler:**
- Kart: 12px köşe, 1px kenarlık, gölge yok, iç boşluk 20px (mobilde 16px).
- Rozetler (küçük, büyük harf, 11px, 4px köşe, %12 opaklıkta renkli zemin + tam renkli yazı): `AL`, `BEKLE`, `PAS`, `İPTAL`, `TETİKLENDİ`, `AKTİF`, `PASİF`, `BAYAT`, `CANLI`.
- Butonlar: birincil (beyaz zemin siyah yazı), ikincil (kenarlıklı), tehlike (kırmızı kenarlık kırmızı yazı), olumlu (yeşil zemin siyah yazı — sadece "Aldım" için).
- Input: #111111 zemin, odakta beyaz 1px kenarlık. Sayı input'ları mono.
- Tablolar: satır yüksekliği 44px, zebra yok, hover'da #111111, başlık yapışkan, sayılar sağa hizalı.
- Tooltip: #1A1A1A zemin, 12px.
- İkonlar: lucide-react, 16px, stroke 1.5. Emoji kullanma.
- Animasyon: sadece hover (150ms), modal/drawer açılışı (200ms ease-out), yeni gelen fiyatın 600ms hafif parlaması (yükselişte yeşil, düşüşte kırmızı arka plan solması). `prefers-reduced-motion` açıksa hepsi kapalı.
- Boş durum, yükleniyor (iskelet/skeleton), hata durumu her liste ve kart için ayrı tasarlanacak (örnek metinler aşağıda).

**Logo:** "KriptoKapı" yazı logosu, Inter 600, yanında küçük bir kapı/geçit ikonu: iki dikey çizgi arasında yukarı bakan bir ok (fiyatın kapıdan kapanışla geçmesi fikri). Tek renk beyaz.

### 2. Halka açık tanıtım sitesi

**Üst menü:** logo, Özellikler, Nasıl Çalışır, Kurallar, SSS, sağda "Giriş" (ikincil) ve "Panele Git" (birincil). Kaydırınca menüye #000 %80 opak + backdrop blur.

**Ana sayfa (`/`):**
- Hero: büyük başlık "Dokunma değil, kapanış." Alt başlık: "Binance verisini kendisi çeker, indikatörleri kendisi hesaplar, alarm kapanışla tetiklenince grafiği ve kararı Telegram'ına yollar." İki buton: "Panele Git", "Nasıl çalışır?". Sağda (mobilde altta) sahte bir Telegram sohbet ekranı mockup'ı: önce grafik görseli mesajı (mum + SMA çizgileri, caption: "BTC/USDT 15m KAPANIŞ ABOVE · Tetik 85 000 · Kapanış 85 120"), ardından analiz mesajı ("KARAR: AL — ilk kademe 25 USD ..."), altında "Aldım / Pas / Alarmı sil" butonları.
- Canlı şerit: BTC, ETH, SOL, NEAR fiyatları ve 24s değişim (mock, 5 sn'de bir hafif değişsin).
- "Neden farklı" 3 sütun: (1) "Kapanış disiplini — iğne asla tetiklemez", (2) "BTC kapı mantığı — her altcoin kararında BTC ayrıca kontrol edilir", (3) "Goalpost yasağı — pozisyon açıkken stop aşağı çekilemez, kod engeller".
- Özellik ızgarası (6 kart, ikon + başlık + 1 cümle): Kapanış alarmları, Yapay zekâ kararı, Pozisyon takibi, Makro rejim skoru, Vadeli kalabalık ölçer, Backtest.
- "Bir sinyalin yolculuğu" yatay zaman çizelgesi (mobilde dikey): Binance mumu kapanır → hacim ve ATR kontrolü → grafik gönderilir → DeepSeek kararı → Aldım/Pas → stop/hedef takibi → haftalık rapor.
- Makro önizleme kartı: rejim skalası (-5…+5) ve 5 bileşen çipi.
- Alt CTA: "Kurallarla işlem yap, hisle değil." + "Panele Git".
- Footer: logo, bağlantılar, ve **yasal uyarı**: "KriptoKapı yatırım tavsiyesi vermez. Gösterilen analizler bilgi amaçlıdır ve otomatik üretilir. Kripto varlıklar yüksek risk içerir; kararlarınızın sorumluluğu size aittir." Bu uyarı footer'da her sayfada olsun.

**Özellikler (`/ozellikler`):** her özellik için bölüm: başlık, 2–3 cümle açıklama, sağda o özelliğin paneldeki ekran görüntüsü yerine ilgili bileşenin canlı mock versiyonu (ör. alarm tablosunun 3 satırlık hali, rejim skalası, R eğrisi).

**Nasıl Çalışır (`/nasil-calisir`):** mimari şeması (kutular + oklar, SVG): Binance WebSocket + REST → İndikatör motoru (SMA 20/50/200, RSI 14 Wilder, ATR 14 Wilder, Volume MA 20, günlük VWAP) → Alarm motoru → DeepSeek V4 Pro → Telegram. Yanda makro kaynaklar: FRED, BLS, CFTC. Altında "Neden ekran görüntüsü değil sayı?" bölümü: piksel okuma hatası yok, daha ucuz, bot proaktif.

**Kurallar (`/kurallar`):** botun uyduğu kuralların her biri bir kart: Dokunma ≠ kapanış; BTC kapı mantığı; Plan formatı (Tetik/Teyit/İptal/Hedef); Goalpost yasağı; Risk/ödül < 1 ise pas; ATR stop kontrolü; Hacim teyidi; Haber tek başına sebep değil; Kesinlik dili yasak; Korelasyonlu coinler tek işlem sayılır; Spot, kaldıraçsız, küçük kademe. Her kartta kısa "Örnek" kutusu.

**SSS (`/sss`):** akordeon. Sorular: "Bot benim yerime alım satım yapar mı?" (Hayır, sadece uyarır ve kayıt tutar), "Hangi borsayı kullanıyor?", "Neden sadece kapanış?", "Sessiz saat nedir?", "Maliyeti ne kadar?", "Verilerim nerede tutuluyor?", "Kaldıraç önerir mi?" (Hayır).

**İletişim (`/iletisim`):** basit form (ad, e-posta, mesaj) + Telegram bağlantısı. Form şimdilik sadece başarı toast'ı göstersin.

### 3. Giriş

- `/giris`: ortada kart, e-posta + şifre, "Telegram ile giriş" ikincil butonu (şimdilik mock). Hatalı girişte kart sallanmasın, sadece input altı kırmızı mesaj.
- Mock kullanıcı: `eto` / herhangi şifre kabul. Oturum localStorage'da.
- `/app/*` rotaları oturum yoksa `/giris`'e yönlendirsin.

### 4. Uygulama paneli (`/app`)

**Kabuk:**
- Masaüstü: sol dikey menü (240px, daraltılabilir 64px ikon moduna). Menü: Genel Bakış, Alarmlar, Pozisyonlar, Analiz, Makro, Vadeli, Backtest, Rapor, Maliyet, Ayarlar. Altta kullanıcı adı ve çıkış.
- Mobil: alt tab bar (Genel, Alarmlar, Pozisyonlar, Makro, Daha fazla). "Daha fazla" bir alt sayfa açar.
- Üst şerit (her sayfada sabit): sayfa başlığı; BTC fiyatı + 24s değişim; "BTC KAPI" rozeti (AÇIK yeşil / TEMKİNLİ sarı / KAPALI kırmızı); makro rejim rozeti "NÖTR -1/5"; sessiz saat ikonu (aktifse ay ikonu + "Sessiz 09:00–16:00"); bugünkü harcama "3.12 TL"; bildirim zili (son 10 olay açılır listede).
- Komut paleti: `Ctrl+K` ile açılır; "alarm kur", "BTC analiz", "rapor 30 gün" gibi eylemler ve sayfalar aranır.

**4.1 Genel Bakış (`/app`)**
- 4 metrik kartı: Aktif alarm, Açık pozisyon (+ anlık K/Z), Bu hafta isabet %, Bu ay maliyet (TL + ay sonu tahmini). Her kartta küçük sparkline.
- "Son sinyaller" akışı (sol, geniş): her satır: saat, coin logosu + parite, olay rozeti (TETİK / İPTAL / HEDEF / YAKLAŞIYOR / TEYİT BOZULDU), kapanış fiyatı, botun kararı rozeti (AL/BEKLE/PAS), kullanıcı aksiyonu (Aldı / Pas / —). Satıra tıklayınca sağdan Analiz çekmecesi açılır.
- "BTC kapısı" kartı: 15m / 1h / 4h / 1d satırları; her satırda fiyatın SMA20/50/200'e göre konumu (▲ üstünde / ▼ altında), RSI değeri ve mini RSI çubuğu. Altında "Testere bölgesi 84 000 – 85 000" bandı; fiyat bu bandın içindeyse sarı "BTC işlem vermiyor, sadece filtre" notu.
- "Takvim" kartı: bugün ve yarın; olay adı, TR saati, geri sayım. Olaya 2 saatten az kaldıysa kartın kenarlığı sarı ve "Yeni giriş yok — veri sonrası ilk 15dk kapanışını bekle".
- "Açık pozisyonlar" mini listesi: her biri stop↔hedef ilerleme çubuğu ile.

**4.2 Alarmlar (`/app/alarmlar`)**
- Üstte sabit bilgi şeridi (kilit ikonu): "Sadece mum KAPANIŞI kontrol edilir. İğne (high/low) asla tetiklemez."
- Filtreler: durum (Aktif/Tetiklendi/İptal/Pasif/Tümü), parite, zaman dilimi. Arama.
- Tablo sütunları: Parite, Yön (ABOVE ▲ / BELOW ▼), Tetik, TF, İptal, Hedef, R/R, Cooldown, Hacim şartı (✓/—), Durum, Son tetik, Tetik sayısı, işlemler (⋯ menü: Düzenle, Backtest et, Grafikte aç, Sil).
- Mobilde tablo yerine kart listesi.
- "Yeni alarm" butonu → sağdan çekmece (mobilde tam ekran sayfa):
  - Parite seçici (arama + takip listesi: BTC, ETH, SOL, NEAR, ONDO, HYPE, AAVE, UNI, BCH, XRP, LINK, AVAX, ARB; USDT paritesi), seçince son fiyat, 15m ATR ve RSI gösterilir.
  - Mod: "KAPANIŞ" sabit, kilitli, yanında "?" tooltip: "Dokunma asla tetiklemez."
  - Yön: ABOVE/BELOW segment kontrol.
  - Tetik, İptal, Hedef sayı input'ları; yanında "son fiyattan %" canlı gösterimi.
  - Zaman dilimi: 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w (varsayılan 15m).
  - Cooldown: 15m, 30m, 1h, 4h, 1d çipleri + özel.
  - Hacim şartı anahtarı (varsayılan açık): "Kırılım mumunun hacmi Volume MA(20) üstünde olmalı."
  - Canlı doğrulama ve önizleme kutusu:
    - ABOVE'da iptal tetiğin altında, hedef üstünde olmalı (BELOW'da tersi); hata kırmızı satır içi.
    - R/R = |hedef − tetik| / |tetik − iptal|; 1'in altında kırmızı "R/R zayıf — kural gereği pas", 1–1.5 sarı, üstü yeşil.
    - |tetik − iptal| < 1×ATR ise sarı "Gürültüye takılma riski yüksek".
    - Şart şu an zaten sağlanıyorsa mavi bilgi: "Bir sonraki kapanışta hemen tetiklenebilir."
    - 25 USD örnek kademe için dolar riski: "25 USD'de risk ≈ 0.62 USD".
  - Mini grafik önizleme: son 100 mum, tetik/iptal/hedef çizgileri.
  - Kaydet → toast "Alarm kuruldu: BTC/USDT #4".

**4.3 Analiz / Alarm detayı (`/app/analiz/:id` ve çekmece)**
- Sol (geniş): candlestick grafik (lightweight-charts). Paneller yukarıdan aşağı: (1) mumlar + SMA20/50/200 + günlük VWAP (kesikli gri) + tetik (beyaz kesikli, sağda etiket "TETİK 85 000"), iptal (kırmızı kesikli), hedef (yeşil kesikli); tetiklenen mumun üstünde küçük işaret. (2) RSI(14), 30/70 kesikli. (3) ATR(14). (4) Hacim çubukları (yeşil/kırmızı) + Volume MA(20) çizgisi. Zaman dilimi seçici (15m/1h/4h/1d), crosshair'de OHLCV + tüm indikatör değerleri üst lejantta.
- Sağ kolon "Bot kararı" kartı:
  - En üstte büyük: `KARAR: AL — ilk kademe 25 USD` (renkli rozet + metin). BEKLE ise ne beklendiği ("Sonraki 15m mum 84 200 üstünde kapanırsa AL").
  - Satırlar: ŞU AN, Tetik, Teyit, İptal, Hedef (R/R), Stop mesafesi % ve ATR katı, Dolar riski.
  - Uyarı çipleri: "Hacim teyidi yok, doğrulanamadı", "Gürültüye takılma riski yüksek", "Sessiz saatte tetiklendi — güncel fiyatla tekrar teyit et".
  - "BTC kapısı" alt kartı ve "Makro" tek satırı ("Rejim NÖTR, 48 saatte olay yok").
  - "Vadeli" tek satırı ("Funding normal · OI 24s +4.5% · yeni para giriyor").
  - Butonlar: `Aldım` (yeşil), `Pas` (ikincil), `Alarmı sil` (tehlike). "Aldım" modal açar: giriş fiyatı (varsayılan son fiyat), miktar USD (varsayılan önerilen kademe), stop, hedef → Kaydet.
- Altta "Analiz metni" — botun tam metni, mono değil Inter, satır aralığı rahat.

**4.4 Pozisyonlar (`/app/pozisyonlar`)**
- Sekmeler: Açık / Kapanmış.
- Açık pozisyon kartı: parite, kaynak ("alarm #3" veya "elle"), giriş, miktar USD, adet, stop, hedef, anlık fiyat, K/Z USD ve %, R. Yatay ilerleme çubuğu: solda stop (kırmızı), sağda hedef (yeşil), giriş işaretli, anlık fiyat noktası. Stop kırıldıysa kart kırmızı kenarlık + "STOP KAPANIŞLA KIRILDI — kural: sat".
- Kart eylemleri: "Stopu yukarı çek" (input; yeni değer mevcut stoptan düşükse buton pasif ve açıklama: "Goalpost yasağı: açık pozisyonda stop aşağı çekilemez"), "Stop girişe (risk sıfır)", "Sattım" (fiyat modalı), "Düzelt" (giriş/miktar).
- Kapanmış tablo: parite, giriş → çıkış, K/Z USD, R, süre, kapanış nedeni (STOP / HEDEF / ELLE rozeti), kural ihlali (varsa kırmızı çip + tooltip "Stop kırıldı, pozisyon tutuldu").
- Üstte toplam: açık K/Z, bu ay gerçekleşen K/Z, toplam R.

**4.5 Makro (`/app/makro`)**
- Rejim göstergesi: -5…+5 yatay skala, 11 bölme, iğne mevcut skorda; etiket "NÖTR (-1)". Altında 5 bileşen çipi: Likidite 0, Dolar −, Kredi spreadi 0, VIX +, Reel faiz −. Tooltip'lerde eşikler ("4 haftalık değişim > +%1 ise +").
- Açıklama satırı: "Rüzgârın yönünü anlatır, tahmin değildir. Makro tek başına giriş sebebi değildir."
- Kart ızgarası (her kartta değer, 4 hafta değişim, mini çizgi grafik, veri tarihi, bayatsa `BAYAT` rozeti):
  - Net likidite (Fed bilançosu − TGA − RRP), milyar $, 4h ve 13h değişim
  - Geniş dolar endeksi — alt etiket: "FRED trade-weighted endeks, klasik DXY değil"
  - ABD 2Y, ABD 10Y, 10Y−2Y eğri, 10Y reel faiz
  - HY kredi spreadi, VIX (1 yıllık yüzdelik), Fed faiz üst bandı
- Enflasyon & istihdam: CPI yıllık, core yıllık, core son 3 ay aylık değerleri (bar), 3 ay yıllıklandırılmış core, trend rozeti (SOĞUYOR / ISINIYOR / YATAY). NFP son 3 ay (bar), işsizlik ve 3 ay önceki, saatlik ücret yıllık.
- CFTC COT (CME BTC ve ETH yan yana): kaldıraçlı fon net ve haftalık değişim, varlık yöneticisi net, açık pozisyon; 52 haftalık yüzdelik için yarım daire gösterge (90 üstü veya 10 altı ise "Pozisyonlanma uç noktada" uyarısı). Not: "Kaldıraçlı fon short'u büyük ölçüde ETF baz (cash-and-carry) işlemidir. Rapor salı verisidir, cuma yayınlanır."
- Takvim: önümüzdeki 14 gün tablo (tarih, TR saati, olay, geri sayım); FOMC satırları vurgulu.

**4.6 Vadeli (`/app/vadeli`)**
- Coin seçici (takip listesi). Kartlar: Funding son (% ve aralık 4s/8s), 7 gün ortalama, yıllıklandırılmış, son 100 kayıt yüzdeliği; Açık pozisyon (USD) ve 24s değişim; Long/short hesap oranı ve 24 saat önce.
- Yorum çipi: "Funding normal" / "Long tarafı kalabalık — long tasfiye riski" / "Short tarafı kalabalık — short sıkışması olasılığı".
- 2×2 matris: satırlar Fiyat ▲/▼, sütunlar OI ▲/▼; hücreler "Yeni para (sağlıklı trend)", "Short kapanışı (kısa ömürlü olabilir)", "Yeni short", "Long çözülmesi". Mevcut durumun hücresi vurgulu.
- Not: "Vadeli işlem yapmıyoruz; bu veri sadece kaldıraçlı tarafın ne kadar kalabalık olduğunu gösterir."

**4.7 Backtest (`/app/backtest`)**
- Form: parite, yön, tetik, zaman dilimi, iptal, hedef, gün (30/90/180/365). İptal/hedef boşsa açıklama: "Tetik anındaki ATR ile: iptal 1.5×ATR, hedef 2×ATR."
- Sonuç: üç kart yan yana "Tümü / Hacim teyitli / Hacimsiz": tetik, hedef, stop, açık, isabet %, ortalama R, toplam R. En iyi olan kartın kenarlığı beyaz.
- Kümülatif R eğrisi (çizgi), her işlem noktası yeşil/kırmızı.
- Fiyat grafiği üzerinde tetik noktaları işaretli.
- Son tetikler tablosu: zaman, giriş, sonuç (HEDEF/STOP/AÇIK), mum sayısı, R.
- Altta sabit gri not: "Geçmiş sonuç geleceği garanti etmez; kuralın karakterini gösterir."
- "Bu kuralla alarm kur" butonu formu Alarm çekmecesine taşır.

**4.8 Rapor (`/app/rapor`)**
- Dönem: 7 / 30 / 90 gün / özel.
- İşlem performansı kartları: işlem sayısı, isabet %, toplam K/Z USD, ortalama R, toplam R, en iyi / en kötü işlem, kural ihlali sayısı (0 ise yeşil onay "Disiplin tam").
- K/Z takvimi (GitHub benzeri ısı haritası; gün başına K/Z).
- "Bot karar isabeti": AL / BEKLE / PAS için yığılmış bar (sonra hedefe gitti / stopa gitti / açık). Büyük metrik: "AL→hedef + PAS→stop isabeti %64".
- "Karara uyma": bot AL dediğinde aldın mı, PAS dediğinde pas geçtin mi — halka grafik.
- R dağılımı histogramı.

**4.9 Maliyet (`/app/maliyet`)**
- Kartlar: Bugün, Son 7 gün, Bu ay (TL büyük, USD küçük), analiz başı ortalama TL, ay sonu tahmini.
- Günlük harcama bar grafiği (30 gün), barlar yoğun/indirimli tarife olarak iki tonlu.
- Token dağılımı yığılmış bar: önbellekten / önbelleksiz / output. Açıklama: "Maliyetin çoğu output (modelin düşünme token'ları). Sistem promptu önbellekten gelir."
- 24 saatlik tarife şeridi: hafta içi TR 04:00–07:00 ve 09:00–13:00 "YOĞUN ×2" koyu, diğer saatler "İNDİRİMLİ"; şu anki saat işaretli.
- Son 50 çağrı tablosu: zaman, etiket ("BTC analiz et", "[ALARM] NEAR"), tarife, önbellek/önbelleksiz/output token, TL.
- Fiyat tablosu (DeepSeek V4 Pro, 1M token): önbellekten $0.022/$0.044, önbelleksiz $0.66/$1.32, output $1.98/$3.96 (indirimli/yoğun). Kur alanı düzenlenebilir.

**4.10 Ayarlar (`/app/ayarlar`)**
- Sessiz saatler: başlangıç/bitiş saat seçici, gün çipleri (Pzt–Paz). Açıklama: "Sadece 'yaklaşıyor' ön-uyarıları susar. Kapanış onaylı tetikler her zaman gelir. Sessiz saat bitiminden 5 dk sonra günlük özet gönderilir."
- Sabah brifi saati (varsayılan 08:30, yanında "09:00 sonrası yoğun tarife" uyarısı).
- Takip listesi: coin çipleri, ekle/çıkar.
- Ön filtre: Kod (önerilen) / qwen3 yerel — radyo kartları, qwen seçilirse "Testlerde 4 vakadan 1'ini yanlış sınıfladı" notu.
- Bütçe: kısa vadeli bütçe (varsayılan 100 USD), varsayılan ilk kademe (25 USD).
- Dolar kuru (USD/TRY).
- Telegram bağlantısı: durum (Bağlı ✓), chat id maskeli.
- Kural özeti (salt okunur liste).

### 5. Durum metinleri (microcopy)

- Yükleniyor: iskelet satırlar, metin yok.
- Boş alarmlar: "Henüz alarm yok. İlk kapanış alarmını kur; bot mum kapanınca haber versin." + "Yeni alarm".
- Boş pozisyonlar: "Açık pozisyon yok. Bir alarmda 'Aldım'a bastığında burada görünür."
- Boş rapor: "Bu dönemde kapanan işlem yok."
- Hata: "Veri alınamadı. Binance veya bot bağlantısı yanıt vermiyor." + "Tekrar dene".
- Bayat veri rozeti tooltip: "Bu veri 3 günden eski; düşük ağırlıkla değerlendir."
- Toast'lar sağ altta, 4 sn: "Alarm kuruldu", "Pozisyon kaydedildi", "Stop 84 500'e çekildi", hata toast'ları kırmızı kenarlıklı.

### 6. TypeScript veri tipleri (mock ve gerçek API bunlara uyacak)

```ts
type Direction = "ABOVE" | "BELOW";
type AlertStatus = "aktif" | "tetiklendi" | "iptal" | "pasif";
type Verdict = "AL" | "BEKLE" | "PAS" | "BELİRSİZ";

interface Alert {
  id: number; pair: string;            // "BTC/USDT"
  tetik: number; yon: Direction; timeframe: string; cooldown: string;
  iptal: number | null; hedef: number | null; hacim_sart: boolean;
  durum: AlertStatus; iptal_nedeni?: "kullanici" | "kapanis";
  son_tetik_zamani: string | null; tetikler: string[]; olusturulma: string;
}

interface Position {
  id: number; pair: string; symbol: string;
  giris: number; miktar_usd: number; adet: number;
  stop: number | null; stop_ilk: number | null; hedef: number | null;
  timeframe: string; kaynak: string; karar_id: number | null;
  durum: "acik" | "kapali"; acilis: string;
  kapanis_fiyat: number | null; kapanis_zamani: string | null;
  neden: "stop" | "hedef" | "elle" | null;
  kural_ihlali: { zaman: string; not: string }[];
}

interface Decision {
  id: number; zaman: string; pair: string; timeframe: string; yon: Direction;
  alarm_id: number; kapanis: number; iptal: number | null; hedef: number | null;
  karar: Verdict; kademe_usd: number | null; aksiyon: "aldi" | "pas" | null;
  analiz_metni: string; uyarilar: string[];
}

interface Candle {
  t: number; o: number; h: number; l: number; c: number; v: number;
  sma20: number | null; sma50: number | null; sma200: number | null;
  rsi14: number | null; atr14: number | null; vol_avg20: number | null; vwap: number | null;
}

interface MacroSummary {
  rejim: { skor: number; etiket: string; bilesenler: Record<string, -1 | 0 | 1> };
  fred: Record<string, { ad: string; son: number; tarih: string; "4h_degisim"?: number; "4h_degisim_yuzde"?: number }>;
  bls: { enflasyon: { donem: string; cpi_yillik: number; core_yillik: number; core_aylik_son3: number[]; core_3ay_yilliklandirilmis: number; trend: string };
         istihdam: { donem: string; nfp_degisim_bin_son3: number[]; issizlik: number; issizlik_3ay_once: number; saatlik_ucret_yillik: number } };
  cftc_cme: Record<"BTC" | "ETH", { rapor_tarihi: string; acik_pozisyon: number; kaldiracli_fon_net: number;
    kaldiracli_fon_net_haftalik_degisim: number; kaldiracli_fon_net_52h_yuzdelik: number;
    varlik_yoneticisi_net: number; varlik_yoneticisi_net_52h_yuzdelik: number }>;
  olay_riski_48s: { olay: string; tr_zaman: string; kalan_saat: number }[];
}

interface Derivatives {
  funding_son_yuzde: number; funding_araligi_saat: number; funding_7g_ort_yuzde: number;
  funding_yillik_yuzde: number; funding_100_kayit_yuzdelik: number;
  acik_pozisyon_usd: number; acik_pozisyon_24s_degisim_yuzde: number;
  long_short_hesap_orani: number; long_short_24s_once: number; yorum_ipucu: string;
}

interface UsageRow { utc: string; tarife: "peak" | "offpeak"; hit: number; miss: number; out: number; usd: number; etiket: string }
```

### 7. REST uç noktaları (api.ts gerçek modda bunları çağırsın)

```
GET    /api/overview
GET    /api/alerts?status=
POST   /api/alerts                       body: Alert alanları (id/durum hariç)
DELETE /api/alerts/:pair/:id
GET    /api/chart/:symbol?tf=15m&limit=300   -> Candle[]
GET    /api/decisions?days=
GET    /api/decisions/:id
POST   /api/decisions/:id/action          body: { aksiyon: "aldi" | "pas", giris?, miktar_usd? }
GET    /api/positions?status=
POST   /api/positions                     body: { pair, giris, miktar_usd, stop, hedef, timeframe }
PATCH  /api/positions/:id                 body: { stop?, hedef?, giris?, miktar_usd? }  (409 dönerse goalpost hatası göster)
POST   /api/positions/:id/close           body: { fiyat, neden }
GET    /api/macro
GET    /api/calendar?days=14
GET    /api/derivatives/:coin
POST   /api/backtest                      body: { pair, yon, tetik, timeframe, iptal?, hedef?, gun }
GET    /api/report?days=7
GET    /api/costs
GET    /api/settings    PATCH /api/settings
WS     /ws   (olaylar: price, alert_fired, alert_notice, position_event, analysis_ready)
```

### 8. Mock veri (gerçekçi ve tutarlı olsun)

- Fiyatlar: BTC 84 350 (SMA20 84 240, SMA50 83 930, SMA200 85 050, RSI 55, 15m ATR 194), ETH 2 690, SOL 116.6, NEAR 4.728, ONDO 0.5075, AAVE 144.25.
- Alarmlar: BTC/USDT ABOVE 85 000 15m iptal 83 850 hedef 85 500 cd 1h AKTİF · NEAR/USDT ABOVE 4.760 15m iptal 4.550 hedef 4.830 TETİKLENDİ · ETH/USDT ABOVE 2 708 15m iptal 2 665 hedef 2 783 AKTİF · ONDO/USDT ABOVE 0.5290 15m iptal 0.5000 hacim şartı açık AKTİF · AAVE/USDT BELOW 143.00 15m İPTAL (kapanış).
- Pozisyonlar: ETH/USDT 20 USD @ 2 690 stop 2 665 hedef 2 783 açık · NEAR/USDT 25 USD @ 4.58 stop 4.47 hedef 4.83 açık · kapanmış: ETH +0.45 USD +0.32R (hedef), SOL −1.10 USD −1.0R (stop).
- Karar örneği (analiz metni): "KARAR: BEKLE — NEAR günlük RSI 82, 4.754 direncinden döndü; kovalamak yok. ŞU AN: BEKLE / İZLE. Tetik: 4.56–4.60'a geri çekilme, 15m kapanış 4.58 üstü. Teyit: sonraki mum 4.55 altına sarkmadan tutunma. İptal: 15m kapanış 4.47 altı. Hedef: 4.83, sonra 4.90 (R/R ≈ 2.3). Stop mesafesi %2.4 ≈ 2 ATR; 25 USD'de risk ≈ 0.6 USD."
- Makro: rejim NÖTR −1 (likidite 0, dolar −, kredi 0, VIX +, reel faiz −), net likidite 5 770 milyar $ (4h −0.16%), geniş dolar 119.51 (+1.23%), 2Y 4.85, 10Y 5.11, eğri 0.31, reel 2.76, HY 2.73, VIX 14.21, Fed üst bant 4.00; CPI 2026-08 yıllık 3.4, core 2.45, core aylık son3 [0.29, 0.22, −0.02], 3a yıllık 1.97 SOĞUYOR; NFP son3 [162, 21, 31], işsizlik 4.1 (3a önce 4.3).
- COT BTC: OI 20 773, kaldıraçlı fon net −6 354 (52h yüzdelik 94), varlık yöneticisi net +2 760 (19). ETH: kaldıraçlı −7 722 (67), varlık yöneticisi −1 920 (25).
- Takvim: 29.09 17:00 JOLTS · 30.09 15:30 GDP · 30.09 15:30 PCE · 02.10 15:30 NFP · 14.10 15:30 CPI · 15.10 15:30 PPI · 28.10 21:00 FOMC.
- Vadeli BTC: funding %0.0019/8s, 7g ort %0.0054, OI 8.1 milyar $ (24s −1.68%), L/S 1.23.
- Maliyet: bugün 2 çağrı 3.12 TL, ay sonu tahmini ~94 TL.
- Mock fiyatlar 5 saniyede bir ±%0.05 rastgele yürüsün; K/Z ve ilerleme çubukları buna göre güncellensin.

### 9. Teknik gereksinimler

- React + TypeScript + Vite + Tailwind + React Router. Grafik: `lightweight-charts` (mum ve indikatör panelleri), `recharts` (diğer grafikler). Durum: TanStack Query (api.ts üstünde).
- Klasör yapısı: `src/pages/public/*`, `src/pages/app/*`, `src/components/ui/*` (Button, Card, Badge, Table, Drawer, Modal, Toast, Tooltip, Skeleton, Tabs, SegmentedControl), `src/components/charts/*`, `src/lib/api.ts`, `src/lib/mock/*`, `src/lib/format.ts` (sayı/para/tarih biçimleri tek yerde).
- Responsive kırılımlar: 375, 768, 1280, 1536. 375px'te yatay kaydırma olmayacak; tablolar karta dönüşecek.
- Erişilebilirlik: klavye ile tüm eylemler, odak halkası görünür (beyaz 2px), kontrast WCAG AA, grafiklerin yanında metin özeti.
- SEO (sadece public sayfalar): her sayfaya başlık ve açıklama meta'sı, Open Graph görseli (siyah zemin, logo, "Dokunma değil, kapanış.").
- Performans: grafik bileşenleri lazy load, public sayfalar hızlı açılsın.

### 10. Yapma

- Açık tema, renkli gradient arka plan, neon parlama, glassmorphism kartlar ekleme. Tek istisna: menü arka planındaki hafif blur.
- "Kesin kazanç", "garantili", "%100" gibi ifadeler kullanma; hiçbir metinde getiri vaadi olmasın.
- Kaldıraç, vadeli işlem açma, "long/short aç" butonu ekleme. Platform spot ve kaldıraçsızdır.
- Ücretli üçüncü taraf API'ye bağlama; tüm veri api.ts üzerinden gelecek.
- Stok fotoğraf ve illüstrasyon kullanma; görseller sadece arayüzün kendisi, grafikler ve SVG şemalar.

---

## DEVAM PROMPTLARI (site oluştuktan sonra, sırayla)

**1 — Tasarım tutarlılığı:**
Tüm sayfaları tasarım sistemiyle karşılaştır. Renkler sadece tanımlı CSS değişkenlerinden gelsin. Tüm sayılar JetBrains Mono ve `format.ts` üzerinden biçimlensin (ince boşluk binlik ayırıcı, nokta ondalık, işaretli yüzdeler). Her sayfanın yükleniyor, boş ve hata durumlarını ekle. 375px genişlikte her sayfayı kontrol et, yatay kaydırma kalmasın.

**2 — Analiz grafiği:**
Analiz sayfasındaki grafiği lightweight-charts ile dört senkron panel olarak kur: mum+SMA20/50/200+VWAP, RSI(14), ATR(14), hacim+Volume MA(20). Paneller aynı zaman eksenini paylaşsın, crosshair hepsinde aynı mumu göstersin, üst lejant OHLCV ve tüm indikatör değerlerini göstersin. Tetik/iptal/hedef yatay çizgileri sağ kenarda renkli etiketle olsun. Tetiklenen mumun üstüne işaret koy.

**3 — Alarm çekmecesi:**
Yeni alarm çekmecesindeki canlı doğrulamayı tamamla: yön kuralları, R/R renk eşikleri (<1 kırmızı, 1–1.5 sarı, >1.5 yeşil), 1×ATR gürültü uyarısı, "şart şu an sağlanıyor" bilgisi, 25 USD kademe için dolar riski ve mini grafik önizleme. Hatalıyken Kaydet pasif olsun ve nedeni butonun altında yazsın.

**4 — Pozisyon kuralları:**
Pozisyon kartındaki "Stopu yukarı çek" alanında goalpost kuralını uygula: yeni stop mevcut stoptan düşükse kaydetme ve "Goalpost yasağı: açık pozisyonda stop aşağı çekilemez" mesajını göster. Stop kapanışla kırılmış pozisyonda kart kırmızı kenarlık ve "Sattım / Tutuyorum" butonları göstersin; "Tutuyorum" kural ihlali olarak kaydedilsin ve Rapor sayfasında sayılsın.

**5 — Ana sayfa cilası:**
Hero'daki Telegram mockup'ını gerçekçi yap: koyu Telegram sohbet görünümü, önce grafik görseli mesajı (küçük mum grafiği SVG), sonra analiz mesajı, altında satır içi butonlar. Sayfa açılınca mesajlar 400 ms arayla sırayla belirsin (reduced-motion'da hepsi direkt görünsün). "Bir sinyalin yolculuğu" zaman çizelgesi kaydırmayla adım adım vurgulansın.

**6 — Gerçek API'ye hazırlık:**
api.ts'deki her fonksiyonu 7. bölümdeki uç noktalarla eşleştir. `VITE_API_URL` tanımlıysa fetch kullansın, 409 yanıtında goalpost mesajını göstersin, `/ws` WebSocket'ten gelen `price`, `alert_fired`, `position_event` olaylarıyla TanStack Query önbelleğini güncellesin. Tanımlı değilse mock çalışmaya devam etsin.
