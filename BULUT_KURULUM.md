# Kapanış'ı buluta taşıma (bilgisayar kapalıyken çalışsın)

Bu belge, siteyi ve Telegram botunu kendi bilgisayarından çıkarıp bulutta 7/24 çalıştırmak için gereken
adımları anlatır. Hesapları, kartı ve anahtarları **sen** oluşturur ve girersin. Depoda hiçbir gerçek anahtar yoktur.

## 1. Mimari

```
                 ┌──────────────────────────────┐
 tarayıcı ──────▶│ web  (FastAPI + React panel) │──┐
 (Google / e-posta│  /app, /api  · port $PORT    │  │   MongoDB Atlas
  Clerk ile giriş)└──────────────▲───────────────┘  ├──▶ kullanıcılar, portföyler, analizler,
                                 │ X-Bot-Key         │    komut kuyruğu, botun data/ yedeği
                 ┌───────────────┴──────────────┐  │
 Telegram ◀─────▶│ worker (Telegram botu,       │──┘
                 │ alarmlar, zamanlanmış işler) │
                 └──────────────────────────────┘
```

- **web**: site ve API. Kullanıcı oturumunu Clerk doğrular. Şifreler Kapanış'ta tutulmaz.
- **worker**: botun kendisi. 7/24 çalışmalı; uyuyan (sleep) bir plana konmamalı.
- **MongoDB Atlas**: iki süreç aynı veritabanını kullanır. Botun `data/*.json` dosyaları da burada yedeklenir
  (`cloud_store.py`), çünkü bulutta disk her yeniden başlatmada silinir.
- Tek Docker imajı iki süreci de çalıştırır: `/app/start.sh web` ve `/app/start.sh worker`.

**Roller**
- **Sistem sahibi** (`OWNER_EMAIL`): botun portföyünü, sinyallerini, alarmlarını ve ayarlarını görür. Bugünkü panelin tamamı.
- **Kullanıcı** (kayıt olan herkes): kendi gerçek portföyü (Portföyüm), piyasa sayfaları, grafik ve günlük sınırlı yapay zekâ analizi.
  Başkasının portföyünü, kararlarını ya da analizlerini göremez. Botun kişisel verisine erişemez.

## 2. Gerekli hesaplar

| Servis | Ne için | Not |
|---|---|---|
| MongoDB Atlas | veritabanı | Ücretsiz M0 küme yeter. Bölge: Frankfurt (eu-central-1). |
| Clerk | giriş (Google, e-posta + şifre, e-posta kodu) | Hobby planı. Canlı ortam (production) için kendi alan adın gerekir. |
| Heroku **ya da** Render **ya da** bir Linux sunucu | web + worker | Aşağıda üç seçenek var. |
| Alan adı | kapanis.app gibi | Clerk canlı ortamı ve HTTPS için. |

Fiyatlar ve öğrenci paketi (GitHub Student Developer Pack) kredileri değişebilir. Karar vermeden önce her servisin güncel sayfasına bak.

**Bölge önemli:** Binance API'si ABD veri merkezlerinden gelen istekleri reddeder. Web ve worker'ı **Avrupa'da**
(Heroku `eu`, Render `frankfurt`) çalıştır.

## 3. MongoDB Atlas

1. Atlas'ta bir proje ve M0 (ücretsiz) küme aç, bölge Frankfurt.
2. Database Access: bir kullanıcı oluştur (güçlü şifre).
3. Network Access: bulut servislerinin IP'si sabit olmadığı için `0.0.0.0/0` gerekebilir. Bu durumda güvenlik şifreye dayanır;
   şifreyi uzun ve rastgele seç.
4. Connect → Drivers: bağlantı adresini al (`mongodb+srv://...`). Bu adres hem web'in `MONGO_URL`'i hem worker'ın
   `STATE_MONGO_URL`'i olur.

## 4. Clerk

1. Clerk'te bir uygulama oluştur.
2. **User & Authentication → Email, phone, username**
   - Email address: açık. **Verify at sign-up** açık, yöntem **Email verification code**.
   - Password: açık.
3. **SSO connections → Google**: açık. Canlı ortamda kendi Google OAuth bilgilerini girmen gerekir
   (Clerk ekranı adım adım gösterir).
4. **Domains**: canlı ortam için alan adını ekle (ör. `kapanis.app`). Clerk'in istediği DNS kayıtlarını alan adı sağlayıcına gir.
5. **API keys** ekranından al:
   - `CLERK_PUBLISHABLE_KEY` (`pk_live_...`, herkese açık olabilir)
   - `CLERK_SECRET_KEY` (`sk_live_...`, **gizli**, yalnız web servisine)
   - Frontend API URL (ör. `https://clerk.kapanis.app`)
     - `CLERK_ISSUER` = bu adres
     - `CLERK_JWKS_URL` = bu adres + `/.well-known/jwks.json`

Backend, Clerk'in "e-posta doğrulandı" demediği hiçbir hesabı kabul etmez. Google ile girenlerin e-postası Google
tarafından doğrulanmış sayılır; onlardan ayrıca kod istenmez.

## 5. Ortam değişkenleri

Tam liste ve açıklamalar: `deploy/web.env.example` ve `deploy/bot.env.example`.

**web**
| Değişken | Değer |
|---|---|
| `AUTH_MODE` | `clerk` |
| `MONGO_URL`, `DB_NAME` | Atlas adresi, `kapanis` |
| `JWT_SECRET` | uzun rastgele metin |
| `BOT_API_KEY` | uzun rastgele metin; worker'daki ile **aynı**. Kullanıcı oturumundan ayrıdır. |
| `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `CLERK_ISSUER` | bölüm 4 |
| `CLERK_AUTHORIZED_PARTIES`, `CORS_ORIGINS` | `https://kapanis.app` |
| `OWNER_EMAIL` | `valenciaennerman@gmail.com` (sistem sahibi) |
| `TRUST_PROXY` | `1` |
| `USER_DAILY_ANALYSES` | kullanıcı başına günlük analiz hakkı (varsayılan 5; DeepSeek ücretli) |
| `TELEGRAM_BOT_USERNAME` | botun kullanıcı adı (@ olmadan) |

**worker**: bugünkü `kriptografikbotu/.env` içindekilerin hepsi, ek olarak:
| Değişken | Değer |
|---|---|
| `WEB_URL` | web servisinin adresi, ör. `https://kapanis.app` |
| `BOT_API_KEY` | web'deki ile aynı |
| `STATE_MONGO_URL`, `STATE_DB_NAME` | Atlas adresi, `kapanis` |

Rastgele anahtar üretmek için: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

## 6. Botun verisini buluta aktarma (bir kez)

Portföyün, alarmların ve kararların bugün `kriptografikbotu/data/` içinde. Bulut botu ilk açıldığında bunları
Atlas'tan okur. Önce bilgisayarından yükle:

```powershell
cd C:\Users\etemk\OneDrive\Desktop\kriptografikbotu
$env:STATE_MONGO_URL = "mongodb+srv://..."   # Atlas adresi
$env:STATE_DB_NAME = "kapanis"
.venv\Scripts\python -c "import cloud_store; print(cloud_store.sync(), 'dosya yüklendi')"
```

Loglar yüklenmez (Telegram token'ı içeren satırlar olabilir).

## 7. Seçenek A: Heroku

```bash
heroku create kapanis --region eu
heroku stack:set container -a kapanis
heroku config:set -a kapanis AUTH_MODE=clerk MONGO_URL=... BOT_API_KEY=... (bölüm 5'teki hepsi)
git push heroku main
heroku ps:scale web=1 worker=1 -a kapanis
heroku domains:add kapanis.app -a kapanis
```

`heroku.yml` iki süreci aynı imajdan kurar. Uyuyan (eco) bir dyno'daki web birkaç saniye geç açılır; worker'ın uyumaması gerekir.

## 8. Seçenek B: Render

Render'da **New → Blueprint** seçip bu depoyu bağla; `render.yaml` iki servisi (Frankfurt) oluşturur. `sync: false`
yazan değişkenleri Render ekranından gir. Render'ın ücretsiz planında arka plan worker'ı yok ve ücretsiz web servisi
15 dakika boşta kalınca uyur. Bu yüzden dosyada iki servis de `starter` planında.

## 9. Seçenek C: Kendi Linux sunucun (ör. öğrenci kredisiyle bir droplet)

```bash
git clone https://github.com/valenciaennerman-cmd/kapanis.git && cd kapanis
cp deploy/web.env.example deploy/web.env     # doldur
cp deploy/bot.env.example deploy/bot.env     # doldur
DOMAIN=kapanis.app docker compose up -d --build
```

Caddy, HTTPS sertifikasını kendisi alır ve yeniler. Alan adının A kaydı sunucunun IP'sini göstermeli.

## 10. Geçiş günü (çakışmayı önle)

Telegram bir botun mesajlarını aynı anda **yalnız bir** sürece verir. Bulut worker'ını açmadan önce bilgisayardaki botu durdur:
`KAPANIS-DURDUR.bat`. İkisi birlikte açık kalırsa Telegram "Conflict" hatası verir ve mesajlar karışır.

Sonra kontrol et:
1. `https://kapanis.app` açılıyor mu?
2. Google ile giriş yapınca `OWNER_EMAIL` hesabı bugünkü paneli görüyor mu?
3. Başka bir e-postayla kayıt olunca kod geliyor mu? Kodu girmeden panel açılmamalı.
4. Telegram'da `/start` botta cevap veriyor mu?
5. Panelden bir analiz iste; sonuç panelde ve (bağlıysa) Telegram'da görünmeli.

## 11. Telegram bağlama (kullanıcılar)

Kullanıcı sitede **Hesap → Telegram'ı bağla**'ya basar ve bir kod alır (10 dakika geçerli, tek kullanımlık, veritabanında
özetlenmiş/hash olarak tutulur). Kodu bota `/bagla KP-XXXXXXXX` olarak yazar. O andan sonra sitede istediği analizler
kendi Telegram'ına da gelir. Bağlamayan kullanıcı sonucu yalnız sitede görür. Bu bağlantı, kullanıcıya botun sahibe özel
komutlarına erişim vermez.

## 12. Bilgisayarda çalıştırma (değişmedi)

`KAPANIS-BASLAT.bat` ile her şey eskisi gibi çalışır (`AUTH_MODE=legacy`: tek yönetici şifresi). Aynı kod iki modda da çalışır.
