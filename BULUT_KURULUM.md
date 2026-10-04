# Kapanış'ı buluta taşıma

Amaç: site ve Telegram botu, bilgisayar kapalıyken de çalışsın; herkes kendi hesabını açabilsin.
Hesapları, kartı ve anahtarları **sen** oluşturur ve girersin. Depoda hiçbir gerçek anahtar ya da şifre yoktur.

Kararlar (27.09.2026):
- Giriş: Clerk (Google, e-posta + şifre, e-posta kaydında doğrulama kodu).
- Veritabanı: MongoDB Atlas, M0, AWS Frankfurt (eu-central-1).
- Sunucu: **Google Cloud** sanal makine (europe-west3 Frankfurt, IP 34.89.243.88). Azure ve Render yedek seçenek. Heroku kullanılmıyor.
- Telegram botu 7/24 çalışır, uyuyan ücretsiz bir plana konmaz.
- Demo portföy ve sanal bakiye kapsam dışı.

## 1. Mimari

```
                  ┌───────────────────────────────┐
 tarayıcı ───────▶│ web: FastAPI + React panel     │──┐
 (Clerk ile giriş)│ /app sayfaları, /api, $PORT    │  │
                  └───────────────▲───────────────┘  │     MongoDB Atlas (Frankfurt)
                                  │ X-Bot-Key         ├──▶  kullanıcılar, portföyler, analizler,
                  ┌───────────────┴───────────────┐  │     komut kuyruğu, bot_files (botun data/ kopyası)
 Telegram ◀──────▶│ worker: Telegram botu          │──┘
                  │ alarmlar, zamanlanmış işler    │
                  └───────────────────────────────┘
```

Tek Docker imajı iki süreci çalıştırır:

| Süreç | Komut | Ne yapar | Uyuyabilir mi? |
|---|---|---|---|
| **web** | `/app/start.sh web` | Siteyi ve API'yi sunar. Clerk oturumunu doğrular. Kullanıcının portföyünü ve analizlerini ayırır. | Evet, ama uyursa ilk açılış yaklaşık 1 dk sürer. |
| **worker** | `/app/start.sh worker` | Telegram botu. Kapanış alarmları (Binance websocket), 15 dk plan takibi, BIST/ABD günlük işler, panel komut kuyruğunu 15 sn'de bir okur. | **Hayır.** Uyursa alarmlar ve Telegram cevapları durur. |

Worker'ın verisi (`data/*.json`: portföy, alarmlar, kararlar, ayarlar) bulutta diskte kalıcı değildir. `cloud_store.py` bu dosyaları:
- açılışta Atlas'tan geri yükler,
- dakikada bir ve kapanırken Atlas'a yazar.

Beklenmedik bir kapanmada en fazla yaklaşık 1 dakikalık değişiklik kaybolabilir. Loglar Atlas'a yazılmaz; içlerinde Telegram token'ı olabilir.

Web ve worker aynı Atlas veritabanını (`kapanis`) kullanır.

## 2. Ortam değişkenleri

Tam liste ve açıklamalar: `deploy/web.env.example`, `deploy/bot.env.example`.

**Ortak (web ve worker)**

| Değişken | Değer |
|---|---|
| `STATE_MONGO_URL` | `mongodb+srv://kapanis_app:<URL-KODLU-ŞİFRE>@cluster0.3uqpipu.mongodb.net/?appName=Cluster0` |
| `STATE_DB_NAME` | `kapanis` |
| `BOT_API_KEY` | uzun rastgele metin, **iki tarafta aynı**. Yalnız bot ile site arasında kullanılır, kullanıcı oturumundan ayrıdır. |

Şifrede `^ $ # ; < > @ : /` gibi karakterler varsa URL kodlanmalı:
`python -c "import urllib.parse; print(urllib.parse.quote(input('şifre: '), safe=''))"`

**Yalnız web**

| Değişken | Değer |
|---|---|
| `AUTH_MODE` | `clerk`: eski yerel yönetici girişi tamamen kapanır |
| `VITE_CLERK_PUBLISHABLE_KEY` | `pk_test_...` / `pk_live_...` (tarayıcıya gider, gizli değil) |
| `CLERK_SECRET_KEY` | `sk_test_...` / `sk_live_...` (**gizli**, yalnız web'de) |
| `CLERK_AUTHORIZED_PARTIES`, `CORS_ORIGINS` | sitenin adresi, ör. `https://kapanis.app` |
| `OWNER_EMAIL` | `admin@example.com` (kendi giriş e-postan): botun portföyünü ve sinyallerini gören tek hesap |
| `JWT_SECRET` | uzun rastgele metin |
| `TRUST_PROXY` | `1` |
| `USER_DAILY_ANALYSES` | kullanıcı başına günlük yapay zekâ analizi (varsayılan 5; DeepSeek ücretli) |
| `TELEGRAM_BOT_USERNAME` | botun kullanıcı adı, @ olmadan |

Clerk'in adresi (issuer) ve imza anahtarları (JWKS) publishable key'in içinden otomatik çıkarılır. Ayrıca girmen gerekmez.

Not: Panel Vite değil, Create React App (craco). Publishable key tarayıcıya derleme sırasında değil, çalışırken
`/api/auth/config` üzerinden gider. Bu yüzden anahtar değişince yeniden derlemek gerekmez; `VITE_` adı da kabul edilir.

**Yalnız worker**: bilgisayardaki `kriptografikbotu/.env` içindekilerin hepsi (`TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_ID`,
`DEEPSEEK_API_KEY`, `NVIDIA_API_KEY`, `TIINGO_API_KEY`, `FRED_API_KEY`, `BLS_API_KEY`, `CFTC_APP_TOKEN`, `SEC_USER_AGENT`), ek olarak:

| Değişken | Değer |
|---|---|
| `WEB_URL` | web'in adresi, ör. `https://kapanis.app` |

Rastgele anahtar üretmek için: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

## 3. Clerk ayarları (bir kez)

- **User & Authentication → Email**: açık. *Verify at sign-up* açık, yöntem **Email verification code**.
- **Password**: açık.
- **SSO → Google**: açık.
- Geliştirme anahtarları (`pk_test`/`sk_test`) `localhost`'ta çalışır.
- Canlı site için Clerk'te **production instance** oluştur:
  - Alan adını ekle ve DNS kayıtlarını gir.
  - Google için kendi OAuth bilgilerini gir.
  - Anahtarları `pk_live`/`sk_live` ile değiştir.

Backend, Clerk'in "e-posta doğrulandı" demediği hesabı kabul etmez. Google ile girenlerden ayrıca kod istenmez.

## 4. Seçenek A: Render

1. Render → **New → Blueprint** → bu depoyu seç. `render.yaml` iki servisi Frankfurt'ta oluşturur:
   `kapanis-web` (web) ve `kapanis-bot` (worker).
2. Her serviste **Environment** bölümüne bölüm 2'deki değerleri gir (`sync: false` yazanlar).
3. Worker'ı henüz **başlatma** ya da **suspend** et. Önce bölüm 6'daki geçiş adımları.
4. **Settings → Custom Domain**: alan adını web servisine bağla.

Render'ın ücretsiz planında arka plan worker'ı yok ve ücretsiz web servisi 15 dakika boşta kalınca uyur.
Bu yüzden `render.yaml`'da iki servis de `starter` planında. Güncel fiyatı Render'da kontrol et.

## 5. Linux sanal makine (Google Cloud — kullanılan; Azure aynı adımlar)

**Google Cloud notları**
- Bölge Avrupa olmalı (europe-west3 Frankfurt). Ücretsiz e2-micro yalnız ABD bölgelerinde; oraya kurulursa Binance çalışmaz.
- VPC firewall: VM ayarlarında *Allow HTTP traffic* ve *Allow HTTPS traffic* işaretli olmalı (ufw'ye ek olarak).
- Alan adı yoksa HTTPS için `34-89-243-88.sslip.io` kullan (IP'yi gösteren ücretsiz ad; Caddy sertifikayı bununla alır).
- MongoDB Atlas → Network Access: VM IP'si (34.89.243.88/32). Veri aktarımı bilgisayardan yapılacaksa bilgisayarının IP'si de izinli kalmalı.
- Bağlantı: Google Cloud konsolundaki **SSH** düğmesi ya da `gcloud compute ssh`. Kurulum betiği (5.3) Docker/swap/firewall kurulu değilse kullanılır; deploy key kısmı her durumda gerekir.

### Azure'a özel adımlar (5.1–5.2)

Microsoft Azure sanal makine

Azure for Students kredisiyle (kart gerekmez) küçük bir Ubuntu makine. Site, bot ve HTTPS aynı makinede,
`docker-compose.yml` ile çalışır. Kredi bitince kaynaklar durur, kartından para çekilmez. Öğrenci olduğun sürece
kredi her yıl yenilenebilir. Kalan krediyi Azure portalında **Cost Management** ya da
[microsoftazuresponsorships.com/Balance](https://www.microsoftazuresponsorships.com/Balance) gösterir.

#### 5.1 Makineyi oluştur (portal.azure.com)

**Virtual machines → Create → Azure virtual machine**

| Alan | Değer |
|---|---|
| Subscription | Azure for Students |
| Resource group | Create new → `kapanis` |
| Virtual machine name | `kapanis-vm` |
| Region | **(Europe) Germany West Central** (Frankfurt). Öğrenci aboneliği izin vermezse *West Europe*, *North Europe* ya da *Sweden Central*. **ABD bölgesi seçme** (Binance engeller). |
| Availability options | No infrastructure redundancy required |
| Security type | Standard |
| Image | Ubuntu Server 24.04 LTS - x64 Gen2 |
| Size | **B1s** (1 vCPU, 1 GiB). Portal "free services eligible" diyorsa ilk 12 ay makine ücreti yok. Yoksa **B2ats_v2** (2 GiB) ya da B1s. Aylık fiyat ekranda yazar. |
| Authentication type | SSH public key |
| Username | `kapanis` |
| SSH public key source | Generate new key pair, ad: `kapanis-vm_key` |
| Public inbound ports | Allow selected ports: **SSH (22), HTTP (80), HTTPS (443)** |

- **Disks:** OS disk type *Standard SSD*, *Delete with VM* işaretli.
- **Networking:** yeni public IP (varsayılan), *Delete public IP and NIC when VM is deleted* işaretli.
- **Management:** *Enable auto-shutdown* **kapalı** olmalı. Açık kalırsa bot her gece durur.

**Review + create → Create**. Açılan pencerede **Download private key and create resource**. İndirilen
`kapanis-vm_key.pem` dosyası makineye giriş anahtarındır: kimseyle paylaşma, git'e koyma.
`C:\Users\etemk\.ssh\` içine taşı.

Makine açılınca: **kapanis-vm → Overview → DNS name → Not configured** → *DNS name label*: `kapanis` → Save.
Adres şöyle olur: `kapanis.germanywestcentral.cloudapp.azure.com` (bölgeye göre değişir). Kendi alan adın olana kadar site bu adreste açılır.

#### 5.2 Makineye bağlan (Windows PowerShell)

```powershell
icacls $HOME\.ssh\kapanis-vm_key.pem /inheritance:r /grant:r "$($env:USERNAME):R"
ssh -i $HOME\.ssh\kapanis-vm_key.pem kapanis@kapanis.germanywestcentral.cloudapp.azure.com
```

(İlk komut, Windows'un "anahtar dosyası herkese açık" uyarısını giderir.)

### 5.3 Kurulum betiği (makinede, bir kez)

`deploy/azure-vm-setup.sh` dosyasının içeriğini kopyala. Makinede `nano azure-vm-setup.sh`, yapıştır, kaydet (Ctrl+O, Enter, Ctrl+X). Sonra:

```bash
sh azure-vm-setup.sh
```

Betik şunları yapar:
- Docker'ı kurar.
- 2 GB swap ekler (1 GB bellekte panel derlemesi yoksa yarıda kalır).
- Güvenlik duvarında yalnız 22/80/443'ü açar.
- Sonda bir **deploy key** (salt okunur anahtar) yazdırır.

O satırı GitHub'da ekle: **kapanis deposu → Settings → Deploy keys → Add deploy key**. *Allow write access* işaretleme.
Sonra `exit` ile çıkıp tekrar bağlan (Docker yetkisi yeni oturumda geçerli olur).

### 5.4 Kodu indir ve ayarları gir

```bash
git clone git@github.com:kapanis-live/kapanis.git
cd kapanis
echo "DOMAIN=kapanis.germanywestcentral.cloudapp.azure.com" > .env
cp deploy/web.env.example deploy/web.env
cp deploy/bot.env.example deploy/bot.env
nano deploy/web.env      # bölüm 2: web değerleri
nano deploy/bot.env      # bölüm 2: worker değerleri
chmod 600 deploy/*.env
```

Botun anahtarlarını elle yazmak yerine bilgisayardan kopyalayabilirsin (bilgisayarda, PowerShell):

```powershell
scp -i $HOME\.ssh\kapanis-vm_key.pem C:\Users\etemk\OneDrive\Desktop\kriptografikbotu\.env kapanis@kapanis.germanywestcentral.cloudapp.azure.com:kapanis/deploy/bot.env
```

Sonra makinede `nano deploy/bot.env`:
- `WEB_URL` satırına dokunma: `docker-compose.yml` bot için `http://web:8001` (iç ağ) verir.
  Bot uçları (`/api/bot/*`, `/api/ingest/*`, `/api/commands/pending`) internetten kapalıdır; bot web'e yalnız iç ağdan ulaşır.
- `PUBLIC_URL=https://kapanis.live` ekle (Telegram mesajlarındaki bağlantılar için).
- Şu satırları ekle: `STATE_MONGO_URL=...` (URL-kodlu şifreyle) ve `STATE_DB_NAME=kapanis`.
- `OLLAMA_URL` satırı varsa sil; sunucuda Ollama yok.

`deploy/web.env` içinde:
- `CLERK_AUTHORIZED_PARTIES` ve `CORS_ORIGINS` = `https://kapanis.germanywestcentral.cloudapp.azure.com`.
- `BOT_API_KEY` iki dosyada aynı olmalı.

Bu dosyalar git'e girmez.

### 5.5 Önce yalnız siteyi aç

```bash
docker compose up -d --build web caddy
docker compose logs -f web      # Ctrl+C ile çık
```

- İlk derleme küçük makinede 10-20 dakika sürebilir.
- Caddy HTTPS sertifikasını kendisi alır. Tarayıcıda `https://kapanis.germanywestcentral.cloudapp.azure.com` açılmalı.
- Clerk geliştirme anahtarı (`pk_test`) bu adreste de çalışır, sayfada "Development mode" etiketi görünür.
- Kalıcı site için Clerk production instance ve kendi alan adın gerekir (bölüm 3).

**Bot (worker) bu aşamada kapalı kalır.** Bölüm 6'daki sırayla açılır: `docker compose up -d worker`.

### 5.6 Günlük işler

| İş | Komut (makinede, `~/kapanis` içinde) |
|---|---|
| Bot günlüğü | `docker compose logs -f --tail 100 worker` |
| Güncelleme (yeni kod) | `git pull && docker compose up -d --build` |
| Yeniden başlat | `docker compose restart worker` (ya da `web`) |
| Durum | `docker compose ps` |
| Bellek | `free -h` |

Makine yeniden başlatılırsa servisler kendiliğinden açılır (`restart: unless-stopped`).

### 5.7 Güvenlik ve yedek

- `deploy/Caddyfile`: HTTPS, güvenlik başlıkları (HSTS, iframe yasağı, nosniff), bot yollarını dışarıya 404.
  Kontrol: `curl -sI https://kapanis.live | grep -i strict` ve `curl -s -o /dev/null -w '%{http_code}' https://kapanis.live/api/commands/pending` → `404`.
- Hız sınırı API'de: IP başına dakikada 180 istek, kullanıcı başına dakikada 40 grafik, en fazla 3 açık canlı bağlantı (`RATE_*`).
- Telegram: sesli sorgu yalnız siteye bağlı hesaplar için, saatte 6; herkese açık komutlar 10 dakikada 30.
- **Günlük yedek:** worker her gün 03:30'da bütün veritabanını `backups` birimine yazar
  (`kapanis-YYYYMMDD-HHMM.jsonl.gz`, son 14 gün). Alınamazsa sahibine Telegram uyarısı gelir.
  Atlas M0 kendi yedeğini tutmaz; bu dosyalar tek kopyadır, ara sıra bilgisayara indir:

```bash
docker compose exec worker ls -l /app/kriptografikbotu/backups
docker compose cp worker:/app/kriptografikbotu/backups ./yedek-indir     # sonra scp ile bilgisayara
```

**Sunucu dışı kopya:** `deploy/bot.env` içine `BACKUP_PASSWORD=uzun-bir-sifre` yazarsan her gece yedeğin şifreli
kopyası bot sohbetine dosya olarak gelir (45 MB'a kadar). Şifreyi başka bir yerde de sakla; şifresiz açılmaz.
Şifreli dosyayı geri yüklemek: `BACKUP_PASSWORD=... python scripts/restore_backup.py DOSYA.jsonl.gz.enc --yes --db kapanis_geri`.

**Site izleme:** bot 5 dakikada bir siteyi (internetten) ve API'yi (iç ağdan) yoklar; 10 dakika cevap yoksa ve
düzelince Telegram'a yazar. Botun kendisi durursa bunu söyleyecek kimse yok: ücretsiz bir dış izleyici
(ör. UptimeRobot, 5 dakikada bir https://kapanis.live) kurup e-posta uyarısı açman önerilir.

Geri yükleme (önce yeni bir veritabanı adına, kontrol et, sonra `DB_NAME`/`STATE_DB_NAME`'i değiştir):

```bash
docker compose exec -w /app/kriptografikbotu worker python scripts/restore_backup.py backups/kapanis-20260927-0330.jsonl.gz            # deneme
docker compose exec -w /app/kriptografikbotu worker python scripts/restore_backup.py backups/kapanis-20260927-0330.jsonl.gz --yes --db kapanis_geri
```

## 6. Geçiş günü (sıra önemli)

Telegram bir botun mesajlarını aynı anda **yalnız bir** sürece verir. İki bot birlikte açık kalırsa Telegram
"Conflict" hatası verir, mesajlar ve alarmlar karışır.

1. **Bilgisayardaki botu durdur:** `KAPANIS-DURDUR.bat`. Görev yöneticisinde `python main.py` kalmadığından emin ol.
2. **Son veriyi Atlas'a yükle** (bilgisayarda, `kriptografikbotu` klasöründe):
   ```powershell
   .venv\Scripts\python scripts\import_data_to_atlas.py          # önce deneme: ne yükleneceğini gösterir
   .venv\Scripts\python scripts\import_data_to_atlas.py --yes    # yükle
   ```
   - Bağlantı adresini `.env.atlas` dosyasından okur ve adresi ekrana yazmaz.
   - Atlas'ta daha yeni veri varsa durur; üzerine yazmak için `--overwrite` gerekir.
   - Atlas'ta var olanın üzerine yazmadan önce onu `data/atlas_yedek_<zaman>.json` olarak bilgisayara yedekler.
3. **Sunucudaki worker'ı başlat** (Azure/VPS: `docker compose up -d worker`; Render: *Resume/Deploy*).
   Açılışta veriyi Atlas'tan geri yükler.
4. **Kontrol et:**
   - Telegram'da `/pozisyonlar` bugünkü portföyünü gösteriyor mu?
   - Sitede Google ile `OWNER_EMAIL` hesabıyla girince bugünkü panel geliyor mu?
   - Başka bir e-postayla kayıt olunca kod geliyor mu? Kodu girmeden panel açılmamalı.
   - Panelden bir analiz iste: sonuç panelde ve (bağlıysa) Telegram'da görünmeli.
5. Geri dönmek gerekirse:
   - Önce sunucudaki worker'ı durdur.
   - Sonra bilgisayarda `KAPANIS-BASLAT.bat`.
   - Bulutta değişen veriyi bilgisayara almak için Atlas'taki `bot_files` gerekir. Bu durumda bana haber ver; bunun için ayrı bir betik yok.

## 7. Kullanıcılar ve veri ayrımı

- **Sistem sahibi** (`OWNER_EMAIL`): bugünkü panelin tamamı. Botun portföyü, sinyaller, alarmlar, disiplin, raporlar.
- **Kullanıcı** (kayıt olan herkes):
  - Kendi gerçek portföyü (Portföyüm), Grafik & Analiz, Makro, Vadeli, Hesap.
  - Başkasının portföyünü, analiz geçmişini ya da Telegram bağlantısını göremez.
  - Botun kişisel verisine sunucu tarafında da erişemez (403).
- **Analiz akışı** (her kullanıcı için aynı):
  1. "Analiz et" → komut kuyruğuna kullanıcı kimliği ve istek kimliğiyle yazılır.
  2. Worker aynı analiz motorunu çalıştırır.
  3. Sonuç yalnız o kullanıcının paneline yazılır.
  4. Telegram bağlıysa kullanıcının kendi sohbetine de gider.
  5. Kullanıcı analizine senin portföyün, planların ya da sohbet geçmişin eklenmez.
- **Telegram bağlama:**
  1. Sitede Hesap → Telegram'ı bağla → kod (10 dk, tek kullanımlık, veritabanında hash'li).
  2. Kullanıcı bota `/bagla KP-XXXXXXXX` yazar.
  3. Bağlantı kullanıcıya botun sahibe özel komutlarını açmaz.
- Şifreler Kapanış'ta tutulmaz (Clerk'te). Broker ya da borsa şifresi istenmez. Bot işlem yapmaz.

## 8. Bilgisayarda çalıştırma

`KAPANIS-BASLAT.bat` eskisi gibi çalışır:
- Yerel MongoDB kullanılır.
- `AUTH_MODE=both`: yönetici şifresi geçerli.
- `backend/.env`'e `CLERK_SECRET_KEY` eklenince Clerk girişi de açılır; Clerk geliştirme ortamı `localhost`'ta çalışır.
