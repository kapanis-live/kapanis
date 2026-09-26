Tasarım dili çok iyi, koru. Ama içerik spec'ten sapmış, şunları düzelt:

1. Mock veriyi uydurma: bölüm 8'deki örnek JSON'ları birebir kullan (KTLEV, SHIB, BTC 84186 USD, THYAO 290.75 TL, NVDA...). Kripto ve ABD USD, BIST TL. Kullanıcı adı /api/auth/me'den (mock: "Admin"). Tarih bugünün tarihi.
2. Skor -5…+5 aralığında, "güven skoru" ifadesini kaldır (skor olasılık değil). Kararlar yalnızca AL / BEKLE / PAS / TUT. Model adı analysis.text sonundaki "🧠 ..." satırından (Kimi K3 / DeepSeek V4.1 Flash / GLM 5.3). "Ufuk" gibi spec'te olmayan alanları kaldır.
3. Sinyal ayrıntısına 6.6'daki "Kod kapısı" bölümünü ekle: analysis.gate.kurallar her kural bir satır, ✅ gecti / ❌ kaldi / ⚠️ uyari + detay, üstte "Kapı: GEÇTİ/KALDI". Altına "Sonra ne oldu" (outcome) ve "Kullanıcı ne yaptı" (user_action). 4 gösterge paneli analysis.panels'ten. "Aldım"a basınca bot kararı AL değilse ek onay iste.
4. Portföy tablosu 6.3'teki tüm sütunlar: Varlık · Adet · Ort. maliyet · Fiyat · Değer · Günlük % · Toplam % · K/Z tutarı · $/TL bazında · Reel % · Temettü. Üstte piyasa başına kart (BIST TL, Kripto USD, ABD USD ayrı; tek TL toplamı yapma). Hafta sonu BIST/ABD için "Son seans".
5. Takip listesi 6.4'e göre: sütunlar Kod(💼) · Fiyat · Günlük % · Haftalık % · Trend · RSI · Destek (fiyat + %) · Direnç (fiyat + %), destek–fiyat–direnç mini çubuğu, "X/Y yükselişte" özeti ve ısı haritası, çoklu seçim + "Telegram'da analiz et" (/takip KOD1 KOD2 panoya kopyalar). "Varlık ekle" butonu da "/takip ekle KOD" komutunu kopyalasın; site listeyi değiştiremez.
6. Genel Bakış 6.2'ye göre: kripto ve BIST günlük K/Z ayrı kartlar, açık risk (open_r), makro rejim -5…+5 ve regime_label, öne çıkanlar (highlights), veri tazeliği tablosu (veri_durumu; kapiyi_etkiler olan bayatsa kırmızı bant). Üst çubuğa NYSE saati ekle.
7. Sayı biçimi spec'teki gibi her yerde aynı: +4.80%, -1.10%, 84 176.50, 0.00000594, 46.198 adet.

Sonra Pozisyonlar, Alarmlar ve Giriş sayfalarını da 6.5 / 6.7 / 6.1'e göre tamamla.
