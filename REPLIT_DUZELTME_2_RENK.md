Tasarım çok soluk ve düşük kontrastlı duruyor. Düzeni koru, sadece görsel canlılığı ve kontrastı artır:

RENKLER (koyu tema, CSS değişkeni olarak tanımla):
- Zemin: #050608 (neredeyse siyah, mavi-gri ton yok)
- Kenar çubuğu: #0a0c10 · Kart: #0f1217 · Kart hover: #151a22
- Kenarlık: #252c38 (kartlar zeminden net ayrılsın), kartın üst kenarına 1px #ffffff0f ışık çizgisi
- Yazı: ana #f5f7fa, ikincil #aab4c3, soluk #7c8797 (bundan koyusu kullanma; gövde metni WCAG AA ≥ 4.5:1)
- Yükseliş #1fd67a · Düşüş #ff4d5e · Uyarı/bekle #ffb020 · Bilgi #4da3ff · Marka vurgusu #2dd4bf
- Rozetler: rengin %14 opak zemini + tam renk yazı, köşe 6px

TİPOGRAFİ:
- Sayfa başlığı 32px/700, kart başlığı 15px/600 #f5f7fa
- Ana rakamlar (toplam değer, K/Z) 34–40px JetBrains Mono 600, tabular-nums
- Tablo rakamları 14px/500 ve #e6eaf0; yüzde değerleri 600 ağırlıkta, yükseliş/düşüş renginde ve ▲ ▼ işaretli
- Küçük büyük harf etiketler 11px, letter-spacing 0.08em, #8a96a8

GÖRSEL DETAY:
- Aktif menü öğesi: sol kenarda 3px #2dd4bf çizgi + #2dd4bf1a zemin + beyaz yazı
- Grafikler doygun renkte: çizgi 2px, alan dolgusu rengin %25'ten %0'a dikey gradyanı; donut dilimleri Kripto #2dd4bf, BIST #ffb020, ABD #4da3ff, Altın/Döviz #c084fc, aralarında 2px boşluk
- Tablo satırları 52px, hover'da #151a22, satır ayırıcı #1c222c
- Kartlar arası boşluk 16px, köşe 12px, gölge yok
- Önemli kartlara (toplam değer, bekleyen karar) çok hafif renkli üst gradyan (rengin %8'i, sonra şeffaf)

AÇIK TEMA: zemin #f6f7f9, kart #ffffff, kenarlık #e3e6eb, yazı #0b0d12; yükseliş #0f9d58, düşüş #e5383b.

Yanıp sönme, sürekli hareket eden animasyon olmasın; sadece hover ve sayfa geçişlerinde 150ms yumuşak geçiş.
