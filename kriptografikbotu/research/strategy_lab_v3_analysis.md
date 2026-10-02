# Strategy Lab v3 — araştırma ve proje analizi

Bu çalışma yalnız araştırmadır. Yeni stratejiler danışmana, Telegram komutlarına,
panel API'sine veya mevcut advisor ruleset'e bağlanmamıştır. Otomatik production
terfisi yoktur. Sonuçların hiçbiri mevcut danışmanın geçmiş performansı olarak
yorumlanmamalıdır; burada tanımlanan adaylar ayrı stratejilerdir.

## Projenin mevcut yapısı

- `main.py`, Telegram komutlarını ve zamanlanmış işleri yönetir. `/danis` ve
  `/firsat` mevcut `danisman.py` motorunu çağırır.
- `danisman.py`, kapanmış 15m/1h/4h/1d mumlarla teknik yapı, kırılım, risk ve
  pozisyon büyüklüğü hesaplar. `ruleset()` ve `ruleset_hash()` karar kurallarını
  sürümler. Mevcut `research/stop_limit.py` bağlantısı bu çalışma öncesinden vardır.
- `advisor.py`, portföydeki mevcut pozisyonlara satış ve koruma planı üretir;
  kripto danışmandan farklı bir modüldür.
- `danisman_paper.py`, danışman raporlarını ve sonraki sonuçları kaydeder.
  Bu sonuçlar danışmanın kararlarına geri beslenmez.
- Kardeş `kapanis/backend/advisor_api.py`, aynı danışmanı HTTP üzerinden sunar.
  `trend_rule.py` günlük Donchian adayının ayrı araştırma kanıtını taşır.
- `research/engine.py`, günlük stratejiler, rastgele kontrol ve eski locked holdout
  testlerini içerir. Kendi otomatik `PRODUCTION` değerlendirmesi vardır. V3 bu
  değerlendiriciyi çağırmaz; yalnız sabit `CRYPTO` evrenini alır.

Mevcut günlük motorun kapanış fiyatıyla işlem varsayımı bu intraday çalışma için
uygun değildir. V3, ayrı bir sonraki mum açılışı simülatörü kullanır. Eski günlük
rejim eşlemesi intraday'e doğrudan taşınmamıştır: günün BTC kapanışı henüz
bilinmiyorsa kullanılamaz.

## Veri ve dönemler

Locked holdout sınırı, mevcut günlük önbelleklerin son mum tarihi olan
27 Eylül 2026'dan 365 gün geriye gidilerek sabitlenmiştir: **27 Eylül 2025 00:00 UTC**.
Bu sınırı belirlemek için yalnız tarih kapsamı incelenmiştir. V3, eski locked
holdout fiyatlarını özellik, sinyal, kalibrasyon veya sonuç hesabına dahil etmez.
Önceki sonuç dosyaları değiştirilmemiştir.

- Isınma verisi: 1 Kasım 2022'den itibaren.
- Geliştirme: 1 Ocak 2023 dahil, 27 Eylül 2024 hariç.
- Validation: 27 Eylül 2024 dahil, 27 Eylül 2025 hariç.
- Locked holdout: yüklenmez, değerlendirilmez.
- BTC günlük rejimi için 1 Ocak 2022'den başlayan, yine holdout öncesinde biten veri kullanılır.

Kodun mevcut evreni **77 coin** içerir; eski belgelerdeki 76 sayısı güncel değildir.
6.964.003 kapanmış 15m mum indirildi. Geliştirme döneminde 72, validation döneminde
66 coin için fiyat verisi vardır. NANO ve BZRX bu tarih aralığında bu sembollerle
veri vermez. SRM, ANC ve MIR yalnız ısınma döneminde veri verir. Eksik varlıkların
sermaye payı nakitte kalır; sonuçlar yalnız veri veren coinleri seçerek hesaplanmaz.

15m kaynak mumlar 1h ve 4h için UTC sınırlarında gruplanır. Eksik alt mum içeren
saat veya dört saatlik bloklar kullanılmaz. Kaynak, [Binance public data](https://github.com/binance/binance-public-data)
ve holdout öncesi tarih sınırı verilmiş [Binance spot REST](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md)
verisidir. Arşivlerin 2025 sonrası mikro-saniye tarihleri mili-saniyeye çevrilir.

## Önceden belirlenen strateji tanımları

| Aday | Kapanışta giriş koşulu |
|---|---|
| breakout_retest_continuation | Önceki 20 mum tepesinin 0,1 ATR üzerinde hacimli kırılım; SMA50/200 yükseliş filtresi; sonraki 10 mum içinde seviyeye 0,25 ATR toleransla retest ve yükselen kapanış |
| liquidity_sweep_reclaim | Önceki 20 mum dibinin en az 0,1 ATR altına süpürme; aynı mumun seviye üzerinde, açılışından yüksek, hacimli kapanışı |
| failed_breakout_reclaim | Hacimli kırılımın ardından seviye altında kapanış; 10 mumluk pencere içinde seviye +0,1 ATR üzerinde hacimli geri alış |
| vwap_reclaim | Aynı UTC gününde önceki kapanış VWAP altında veya eşit; mevcut kapanış VWAP ve EMA20 üzerinde; hacim teyidi |
| relative_strength_rotation | Her 24 mumda, SMA200 üzerinde ve pozitif 63 mum getirisi olan coinleri BTC'ye göre fazla getiriyle sırala; ilk üç coin |
| compression_expansion_v2 | Önceki beş mumda ATR ve Bollinger genişliği yüzdelikleri ≤0,20; 20 mum tepesinin 0,1 ATR üzerinde hacimli kırılım ve SMA50/200 yükseliş filtresi |

Hacim teyidi, mevcut kapanmış mum hacminin önceki 20 mum ortalamasının en az
1,2 katıdır. İşlem, sinyal mumunun ardından gelen mumun açılışında gerçekleşir.
Sinyal mumunun kapanışı üzerinden fill yapılmaz. Her iki tarafta %0,10 komisyon
ve %0,05 olumsuz slippage vardır. Spot, yalnız long, kaldıraçsızdır.

Yapısal stop giriş sinyalinde sabitlenir; en az 1 ATR mesafe kullanılır. Rotation
stopu sinyal kapanışından 2 ATR aşağıdadır. Ortak çıkışlar: stop altında kapanış,
2R hedef üzerinde kapanış veya 48 kapanmış mum. Çıkış da sonraki açılıştadır.
Rotation ayrıca sıralamadan çıkınca satar. Açılış boşluğu nedeniyle kayıp 1R'yi aşabilir.
Bu, kapanış teyitli stop modelidir; intrabar stop emri testi değildir.

Beş bağımsız adayda coin başına başlangıç sermayesi eşittir ve coinler arasında
yeniden dağıtım yapılmaz. Rotation gerçek nakit hesabıyla en fazla üç pozisyon
taşır; yeni pozisyon toplam güncel sermayenin en fazla üçte biriyle açılır.
Allocation farklılığı nedeniyle CAGR'lar aynı portföy kullanımını temsil etmez.

## Sonuçları okuma

`strategy_lab_v3_results.json` içinde altı aday, üç zaman dilimi ve iki dönem
için **36 ayrı değerlendirme** vardır. Her değerlendirme şu ölçümleri içerir:
trade count, win rate, mean/median R, profit factor, CAGR, max drawdown, Sharpe,
Sortino, exposure, MFE, MAE, false breakout rate ve ortalama taşıma süresi.

- Oranlar ondalık kesirdir; örneğin `0.12`, %12'dir. Drawdown pozitif büyüklüktür.
- R, maliyetler düşülmüş birim P&L'nin başlangıç stop mesafesine oranıdır.
- Profit factor parasal net kazanç / parasal net kayıptır; R toplamları oranı değildir.
- Sharpe ve Sortino günlük UTC portföy getirilerinden hesaplanır.
- MFE ve MAE başlangıç R birimindedir. Yalnız elde tutulan kapanmış mumların
  yüksek/düşük fiyatları ve çıkış açılışı dahildir; çıkış mumunun sonraki uçları dahil değildir.
- Ortalama taşıma süresi saattir.
- False breakout, üç kapanmış elde tutma mumu içinde sabit kırılım seviyesi altında
  kapanıştır. Kırılım içermeyen sweep, VWAP ve rotation için tanımsızdır; `null`
  raporlanır. Erken biten belirsiz gözlem pencereleri paydadan çıkarılır.
- `by_regime`, coin'in kendi zaman dilimindeki giriş rejimidir. `by_btc_regime`,
  giriş sinyali anında bilinen son kapanmış günlük BTC rejimidir. İkisi ayrıdır.
- Her rejim tablosunda TREND_UP, TREND_DOWN, RANGE, HIGH_VOL ve PANIC bulunur.
  Sıfır işlemli hücrelerde R ve oranlar `null` kalır; sıfır getiri nakit durumudur.
- Rejim bazlı portföy ölçümleri giriş rejimine atanan P&L'nin tam takvim boyunca
  katkısını gösterir. Yalnız o rejimde işlem açan yeni bir strateji testi değildir.

## Sınırlar ve proje bulguları

1. Mevcut evren point-in-time exchange evreni değildir. Delist olmuş coinleri
   içermesi seçilim yanlılığını azaltabilir; ortadan kaldırmaz. Yeniden adlandırılmış
   semboller birleştirilmez; örneğin mevcut LUNA serisi eski Terra çöküşünün tam
   geçmişi olarak kabul edilmemelidir.
2. Veri sonu ve dönem sonu için son mevcut mumun açılışı tasfiye fiyatıdır; bu
   mumun önceki kapanışında çıkış planı verilmiş kabul edilir. `data_end` işaretleri
   gerçek delist likiditesinin yeniden kurulamadığını gösterir. Sonuçlar bu
   varsayım nedeniyle iyimser olabilir. Normal sinyaller ve tasfiyeler ayrıdır.
3. Sabit slippage, emir defteri kapasitesi veya gerçek fill kalitesi kanıtı değildir.
   Çok likit ve küçük coinler aynı maliyet senaryosuyla test edilir.
4. Günlük eski motorun `PRODUCTION` etiketi ve danışmanın araştırma metinleri
   bu çalışmayla güncellenmemiştir. V3 hiçbir production kararı üretmez.
5. Bu ilk turda parametre optimizasyonu, random-entry kontrolü veya çoklu test
   düzeltmesi yoktur. Validation sonuçları, tek başına istatistiksel edge kanıtı değildir.

Koruma denetimi, root Python kaynaklarını, eski araştırma kaynaklarını ve önceki
iki sonuç dosyasını SHA-256 ile karşılaştırır. JSON içindeki `integrity` ve
`execution_audit` alanları bu kontrollerin kanıtını taşır. Yeni dosyalar yalnız
`research/` altında bulunur. Veri önbelleği ve JSON mevcut `.gitignore` kuralları
nedeniyle yereldir.

Çalıştırma: `python research/strategy_lab_v3.py`

Kontrol: `python -m unittest research.test_strategy_lab_v3 -v`

## İlk çalıştırmanın sonuçları

36 değerlendirme tamamlandı. 14 test geçti. JSON şeması, tüm istenen metrikler,
rejimlerde işlem sayılarının toplamları, dönem ayrımı ve holdout denetimleri
doğrulandı. 84 mevcut kaynak/sonuç dosyasının hash'i aynı kaldı. Veri indirme
hatası yoktur; tarihsel veri bulunmayan semboller ayrıca raporlanır.

**Geliştirme ve validation'ın ikisinde de pozitif mean R üreten kombinasyon yoktur.**
15m adayların tamamı iki dönemde de negatif mean R verir. 1h adayların tamamı da
iki dönemde negatiftir. 4h sonuçları daha karışıktır; hiçbir aday iki dönemde
pozitif mean R'yi korumaz.

| Strateji | Zaman | Geliştirme mean R | Validation mean R | Validation PF | Validation CAGR | Validation işlem |
|---|---|---:|---:|---:|---:|---:|
| breakout_retest_continuation | 15m | -0,525 | -0,407 | 0,698 | -%35,89 | 11.749 |
| breakout_retest_continuation | 1h | -0,245 | -0,111 | 0,929 | -%4,88 | 2.945 |
| breakout_retest_continuation | 4h | -0,047 | -0,073 | 1,073 | %2,35 | 682 |
| liquidity_sweep_reclaim | 15m | -0,434 | -0,419 | 0,688 | -%55,15 | 20.246 |
| liquidity_sweep_reclaim | 1h | -0,311 | -0,258 | 0,777 | -%26,15 | 5.098 |
| liquidity_sweep_reclaim | 4h | 0,009 | -0,173 | 0,757 | -%12,62 | 1.084 |
| failed_breakout_reclaim | 15m | -0,323 | -0,285 | 0,677 | -%31,80 | 7.300 |
| failed_breakout_reclaim | 1h | -0,168 | -0,088 | 0,946 | -%3,13 | 1.871 |
| failed_breakout_reclaim | 4h | 0,156 | -0,085 | 0,956 | -%1,25 | 445 |
| vwap_reclaim | 15m | -0,371 | -0,285 | 0,797 | -%43,57 | 21.536 |
| vwap_reclaim | 1h | -0,169 | -0,101 | 0,871 | -%20,70 | 6.775 |
| vwap_reclaim | 4h | 0,048 | -0,045 | 0,921 | -%8,16 | 1.944 |
| relative_strength_rotation | 15m | -0,199 | -0,223 | 0,803 | -%99,33 | 2.983 |
| relative_strength_rotation | 1h | -0,078 | -0,058 | 0,799 | -%72,13 | 714 |
| relative_strength_rotation | 4h | -0,102 | 0,019 | 0,921 | -%26,04 | 197 |
| compression_expansion_v2 | 15m | -0,542 | -0,373 | 0,689 | -%20,50 | 5.591 |
| compression_expansion_v2 | 1h | -0,237 | -0,151 | 0,795 | -%5,66 | 1.140 |
| compression_expansion_v2 | 4h | -0,030 | 0,169 | 1,260 | %2,88 | 240 |

Compression 4h validation'da 240 işlem, %40 win rate, +0,169 mean R, 1,26 PF,
%2,88 CAGR ve %3,28 max drawdown üretir. Geliştirmede mean R negatiftir;
bu nedenle iki dönem boyunca sürdürülen bir üstünlük göstermez.

Rotation 4h'nin pozitif ortalama R'sine rağmen parasal PF ve CAGR negatiftir.
Breakout retest 4h'de bunun tersi görülür. Çelişki değildir: ortalama R her işlemi
eşit sayar; parasal P&L, farklı stop mesafeleri, sermaye büyüklükleri ve işlem
sırasıyla ağırlıklandırılır. Sonuçlar yalnız tek bir metrikle sıralanmamalıdır.

BTC günlük rejim dağılımları geliştirmede 251 TREND_UP, 71 TREND_DOWN, 136 RANGE,
143 HIGH_VOL, 34 PANIC günüdür. Validation'da sırasıyla 112, 24, 158, 44, 27 gündür.
BTC rejimi ve coin rejimi bazında tüm metrikler JSON içinde ayrı tutulur.

Bu sonuçlar araştırma bulgusudur. Hiçbir aday için production kararı verilmedi;
holdout'u açma, advisor ruleset'i değiştirme veya otomatik entegrasyon yapılmadı.
