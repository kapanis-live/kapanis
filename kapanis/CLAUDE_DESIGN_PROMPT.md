Kapanış adlı kişisel yatırım karar destek panelimin (kripto, BIST, ABD hisseleri) arayüzünü yeniden tasarla. Dil Türkçe. Hedef: ciddi, profesyonel bir finans terminali hissi; Apple / Linear / TradingView sadeliği. Çocuksu, oyuncak gibi görünen hiçbir şey olmasın.

## Yazı tipi ve boyutlar (en önemli istek: yazılar büyük ve rahat okunur olsun)
- Yazı tipi: SF Pro Display (Mac), yoksa Inter. Rakamlar aynı yazı tipinde, tabular-nums (sütunlar hizalı), monospace KULLANMA.
- Temel metin 17–18px, tablo satırları 17px, kod adları (BTC, THYAO) 18px kalın, fiyatlar 18px kalın.
- Sayfa başlığı 34px/700, kart başlığı 18px/700, büyük özet rakamları 30–36px/700.
- Küçük etiketler bile 13px'in altına inmesin. Satır yüksekliği ferah (tablo satırı ~64px).
- Kullanıcı yazı boyutunu A− / A+ ile büyütüp küçültebilsin (tüm ölçüler rem).

## Renkler (sade, doygunluğu kontrollü; pastel/şeker renkleri, neon, gökkuşağı YOK)
- Koyu tema (varsayılan): zemin #050608, kart #0f1217, hover #151a22, çizgi #252c38.
- Yazı: ana #f5f7fa, ikincil #aab4c3, soluk #7c8797.
- Anlam renkleri sadece anlam için: yükseliş #1fd67a, düşüş #ff4d5e, uyarı #ffb020, bilgi #4da3ff, marka vurgusu #2dd4bf.
- Yüzde rozetleri: rengin %15 opak zemini + tam renk yazı + ▲/▼ işareti, köşe 8px.
- Açık tema da olsun: zemin #f6f7f9, kart #ffffff, yazı #0b0d12, yükseliş #0f9d58, düşüş #e5383b.
- Gölge yok, ince kenarlık, köşe 12px; animasyon yalnız 150ms hover/geçiş (yanıp sönme, konfeti yok).

## Grafik sayfası (TradingView kalitesinde)
- Mum grafiği (candlestick): yükselen mum #1fd67a, düşen #ff4d5e, fitiller aynı renk, kenarlık yok.
- Göstergeler açılıp kapanabilen çipler halinde: SMA 20 (#ffb020), SMA 50 (#4da3ff), SMA 200 (#c084fc), VWAP (#2dd4bf) — hepsi 2px ince çizgi, fiyat grafiğinin üstünde.
- Alt bölmeler: Hacim (yükselen mum yeşil, düşen kırmızı, %50 saydam) + hacim ortalaması (ince beyaz çizgi); RSI 14 (turuncu çizgi, 70 kırmızı ve 30 yeşil kesikli seviye çizgileri).
- Bölme oranı yaklaşık: fiyat %65, hacim %17, RSI %18. Izgara çizgileri çok silik (#1c222c).
- Zaman dilimleri: 15 dk, 1 saat, 4 saat, Günlük, Haftalık. Piyasa: Kripto / BIST / ABD. Kod arama kutusu.
- Grafiğin üstünde: logo, kod, son fiyat (büyük, kalın), günlük değişim rozeti.
- Grafiğin altında 4 kart, herkesin anlayacağı dille: Trend (SMA'lara göre), RSI (ısınmış / normal / çok satılmış), Hacim (ortalamanın kaç katı), VWAP (üstünde/altında).
- Saatler İstanbul saati; son mumun henüz kapanmamış olabileceği küçük notla belirtilsin.

## Tablolar (takip listesi, portföy)
- Her satırda şirket/coin logosu (yuvarlak köşeli kare), kalın kod adı, kalın fiyat, günlük ve haftalık yüzde rozetleri, trend (↗ güçlü yeşil, → karışık gri, ↘ zayıf kırmızı), RSI sayısı + küçük çubuk, destek → direnç ve aralarında fiyatın konumunu gösteren çubuk.
- Satıra tıklayınca o kodun grafiği açılsın.

## Pozisyonlar
- Stop / satış fiyatı gibi teknik formlar olmasın. Her pozisyon bir kart: logo, kod, adet; büyük kâr/zarar (tutar + %); "Yatırdığın / Şimdiki değeri / Alış → şimdi" üç kutucuk; iki düğme: "Grafiği aç" ve "Sattım" (fiyat şu anki fiyatla dolu gelir).

Bot asla işlem yapmaz; "Al", "Emir gönder", kaldıraç gibi borsa emri izlenimi veren hiçbir öğe olmasın. Her sayfanın altında: "Yatırım tavsiyesi değildir. Bot işlem yapmaz."
