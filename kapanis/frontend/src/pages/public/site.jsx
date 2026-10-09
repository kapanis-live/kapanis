// Tanıtım sitesi: Claude Design "Kapanış" sistemi (Site sayfaları). Metinler sistemin gerçekte yaptığıyla uyumlu:
// kullanıcıya Telegram'dan analiz sonuçları ve kendi alarmları (fiyat/RSI kapanışı, pozisyon stop/hedef) gider.
import { createElement as h, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { K, U } from "@/ds";
import { useLang, translate, currentLang } from "@/lib/i18n";

// Metinler Türkçe yazılır; ziyaretçi English seçtiyse sözlükteki karşılığı gösterilir (lib/i18n.jsx).
// Sayfa bileşenleri useLang() çağırır: dil değişince sayfa yeniden çizilir.
const tx = (text, vars) => translate(currentLang(), text, vars);

// Site içindeki /... linkleri (başlık, alt bilgi, düğmeler) sayfa yenilemeden açılsın
export function SiteShell({ active, children }) {
  const navigate = useNavigate();
  useLang();
  const onClickCapture = (e) => {
    const a = e.target.closest?.("a[href]");
    const href = a?.getAttribute("href");
    if (!href || !href.startsWith("/") || href.startsWith("//") || e.metaKey || e.ctrlKey || e.shiftKey || a.target === "_blank") return;
    e.preventDefault();
    navigate(href);
    window.scrollTo(0, 0);
  };
  return h("div", { className: "kp-site", onClickCapture },
    h(K.SiteHeader, { active }), h("main", { className: "kp-site__main" }, children), h(K.SiteFooter, null));
}

function SecHead(kicker, title, lead) {
  return h("div", { className: "kp-sec__head" }, kicker ? h("div", { className: "kp-sec__kicker" }, kicker) : null,
    h("h2", { className: "kp-sec__title" }, title), lead ? h("p", { className: "kp-sec__lead" }, lead) : null);
}
export function PageHero(kicker, title, lead) {
  return h("section", { key: "hero", className: "kp-sec" }, h("div", { className: "kp-wrap" },
    h("div", { className: "kp-sec__head", style: { marginBottom: 0 } }, h("div", { className: "kp-sec__kicker" }, kicker),
      h("h1", { className: "kp-hero__title", style: { fontSize: "2.75rem" } }, title), lead ? h("p", { className: "kp-sec__lead" }, lead) : null)));
}
function CTA() {
  return h("section", { className: "kp-band" }, h("div", { className: "kp-wrap kp-cta" },
    h("h2", { className: "kp-cta__title" }, tx("Portföyünü ekle, kapanışı bekle.")),
    h("div", { className: "kp-cta__actions" }, h(K.Button, { variant: "primary", href: "/kayit" }, tx("Ücretsiz hesap aç")), h(K.Button, { variant: "secondary", href: "/giris" }, tx("Giriş yap")))));
}
const check = (content) => h("li", null, h(K.Icon, { name: "check", size: 18, stroke: 2.25 }), h("span", null, ...[].concat(content)));

const MARKETS = () => [
  { kicker: tx("Kripto"), dot: "var(--cat-2)", title: tx("Yalnız spot"), text: tx("Binance fiyatlarıyla BTC, ETH ve diğer spot pariteler."), items: [tx("15 dk ve 4 saatlik mum kapanışı"), tx("Kaldıraç, vadeli, açığa satış yok"), tx("Dolar bazında K/Z")] },
  { kicker: "BIST", dot: "var(--cat-1)", title: tx("Orta ve uzun vade"), text: tx("BIST hisseleri, günlük kapanış ve BIST 100 karşılaştırması."), items: [tx("Günlük kapanış teyidi"), tx("BIST 100’e göre güç, maliyet sonrası R/R"), tx("Tam adet, TL bazında K/Z")] },
  { kicker: tx("ABD"), dot: "var(--cat-3)", title: tx("Hisseler"), text: tx("ABD hisseleri, dolar bazında takip."), items: [tx("Günlük ve haftalık kapanış"), tx("Bilanço takvimi uyarısı"), tx("Dolar bazında K/Z")] },
];
const RULES = () => [
  { icon: "chart", title: tx("Kapanış teyidi"), detail: tx("Sinyal yalnız mum kapanışıyla sayılır. Fitil ve iğne sayılmaz.") },
  { icon: "stopup", title: tx("Goalpost yasağı"), detail: tx("Açık pozisyonda stop yalnız yukarı taşınır, asla aşağı çekilmez.") },
  { icon: "code", title: tx("Sayıları kod hesaplar"), detail: tx("R/R, stop, hacim ve kurallar kodda. Yapay zekâ yalnız açıklar.") },
  { icon: "shield", title: tx("İşlem yok"), detail: tx("Emir göndermez, kaldıraç yok, aracı kurum şifresi istemez.") },
];
const HOW = () => [
  { title: tx("Portföyünü ekle"), detail: tx("Aldığın kodu, adedi, alış fiyatını ve stopunu gir. Hedef isteğe bağlı.") },
  { title: tx("Grafiğe bak"), detail: tx("Mum grafiği, SMA 20/50/200, RSI ve hacim; İstanbul saatiyle.") },
  { title: tx("“Analiz et”e bas"), detail: tx("Kod son kapanmış mumla kuralları sayar, yapay zekâ sonucu açıklar.") },
  { title: tx("Sonuç panelde"), detail: tx("İstersen aynı sonuç Telegram’dan da gelir.") },
];

function HeroVisual() {
  const c = useMemo(() => U.demoCandles("THYAO", "1d", 312.5, 60), []);
  return h("div", { className: "kp-card", style: { display: "flex", flexDirection: "column", gap: "1rem" } },
    h("div", { className: "kp-sighead" },
      h("div", { className: "kp-sighead__id" }, h(K.Ticker, { symbol: "THYAO", name: tx("Günlük · örnek"), logo: { code: "THYAO", market: "BIST" } }),
        h("span", { style: { fontSize: "1.625rem", fontWeight: 700 } }, "₺312,50")),
      h(K.DecisionBadge, { decision: "BEKLE", size: "lg" })),
    h(K.MiniChart, { candles: c, height: 150, symbol: "THYAO" }),
    h("div", { className: "kp-tile", style: { gap: "0.375rem" } },
      h("span", { className: "kp-tile__label" }, tx("Sonuç")),
      h("span", { style: { fontWeight: 600 } }, tx("Direnç ₺318,00. Günlük mum bunun üstünde KAPANMADAN sinyal sayılmaz."))),
    h(K.GateList, { summary: false, items: [
      { status: "gecti", rule: "Trend", detail: tx("Fiyat SMA 50 ve SMA 200 üstünde") },
      { status: "uyari", rule: tx("Kapanış teyidi"), detail: tx("Fitil ₺319,40’a çıktı, kapanış ₺312,50: sayılmadı") },
      { status: "gecti", rule: tx("R/R (maliyet sonrası)"), detail: tx("2,1 · eşik 1,5") },
    ] }),
    h("p", { className: "kp-note" }, tx("Örnek analiz · yatırım tavsiyesi değildir")));
}

export function Home() {
  useLang();
  const markets = MARKETS();
  return h(SiteShell, { active: null },
    h("section", { key: "hero", className: "kp-wrap kp-hero" },
      h("div", null,
        h("div", { className: "kp-hero__kicker" }, markets.map((m) => h("span", { key: m.kicker, className: "kp-hero__pill" }, h("i", { style: { background: m.dot } }), m.kicker))),
        h("h1", { className: "kp-hero__title" }, tx("Dokunma değil, kapanış.")),
        h("p", { className: "kp-hero__lead" }, tx("Kapanış, kripto, BIST ve ABD hisseleri için kişisel karar destek panelidir. Kuralları kod sayar, sinyali yalnız mum kapanınca verir, yapay zekâ yalnız açıklar. İşlem yapmaz.")),
        h("div", { className: "kp-hero__actions" },
          h(K.Button, { variant: "primary", href: "/kayit" }, tx("Ücretsiz hesap aç")),
          h(K.Button, { variant: "secondary", href: "/giris" }, tx("Giriş yap"))),
        h("p", { className: "kp-hero__note" }, tx("Google ya da e-posta ile giriş · aracı kurum şifresi istemez"))),
      h(HeroVisual, null)),
    h("section", { key: "mk", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      SecHead(tx("Piyasalar"), tx("Üç piyasa, aynı kurallar"), tx("Her piyasa kendi para biriminde ve kendi vadesinde; kapanış teyidi hepsinde aynı.")),
      h("div", { className: "kp-grid kp-g-3" }, markets.map((m) => h(K.FeatureCard, { key: m.kicker, kicker: m.kicker, dot: m.dot, title: m.title, items: m.items }, m.text))))),
    h("section", { key: "how", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      SecHead(tx("Nasıl çalışır"), tx("Dört adım, hepsi senin kontrolünde"), null),
      h(K.StepList, { steps: HOW() }))),
    h("section", { key: "rules", className: "kp-band" }, h("div", { className: "kp-wrap", style: { paddingTop: "2rem", paddingBottom: "2rem" } },
      h("div", { className: "kp-sec__kicker" }, tx("Kurallar kodda")),
      h(K.RuleStrip, { items: RULES() }),
      h("a", { href: "/kurallar", className: "kp-link", style: { display: "inline-block", marginTop: "0.5rem" } }, tx("Kuralların hepsi")))),
    h("section", { key: "tg", className: "kp-sec" }, h("div", { className: "kp-wrap kp-two" },
      h("div", null,
        SecHead("Telegram", tx("Sonuç telefonuna da gelsin"), tx("Panele bakmadığın an da analiz sonucunu kaçırma. Bağlamak bir komut.")),
        h("ul", { className: "kp-bullets" },
          check(tx("İstediğin analizin sonucu tek mesajda: karar, gerekçe, seviyeler.")),
          check(tx("Yalnız senin sonuçların; başkasının analizi sana gelmez.")),
          check([tx("Bağlamak için panelden kod al, bota "), h("span", { key: "c", className: "kp-cmd" }, "/bagla KP-XXXXXXXX"), tx(" gönder.")]))),
      h(K.MessagePreview, { time: tx("Bugün 18:12") },
        h("div", { className: "kp-msg__row" }, h("b", null, tx("THYAO · Günlük")), h(K.DecisionBadge, { decision: "BEKLE" })),
        h("p", null, tx("Kapanış ₺312,50. Direnç ₺318,00 üstünde günlük kapanış yok; fitil sayılmadı.")),
        h("p", null, tx("R/R 2,1 · senin stopun: ₺296,00.")),
        h("p", { className: "kp-note" }, tx("Yatırım tavsiyesi değildir. Bot işlem yapmaz."))))),
    h("section", { key: "trust", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      SecHead(tx("Güven"), tx("Verin ve paran sende kalır"), null),
      h("div", { className: "kp-grid kp-g-4" },
        h(K.FeatureCard, { icon: "lock", title: tx("Şifren bizde değil") }, tx("Google ya da e-posta + doğrulama koduyla girersin. Şifreler Kapanış’ta tutulmaz.")),
        h(K.FeatureCard, { icon: "key", title: tx("Kendi yapay zekâ anahtarın") }, tx("İstersen DeepSeek ya da NVIDIA anahtarını eklersin. Şifreli saklanır, yalnız son 4 hanesi görünür.")),
        h(K.FeatureCard, { icon: "download", title: tx("Verin senin"), footer: h("a", { href: "/gizlilik", className: "kp-link" }, tx("Gizlilik ve KVKK")) }, tx("Tüm verini tek tıkla indirir, hesabını istediğin an silersin.")),
        h(K.FeatureCard, { icon: "shield", title: tx("İşlem yapmaz") }, tx("Aracı kuruma bağlanmaz, emir göndermez, borsa şifresi istemez."))),
      h("div", { style: { marginTop: "1.5rem" } }, h(K.Callout, { tone: "info", title: tx("Yatırım tavsiyesi değildir") }, tx("Kapanış kurallarını açıklar ve sayar; karar ve işlem her zaman senin."))))),
    h(CTA, { key: "cta" }));
}

export function Features() {
  useLang();
  const rows = [
    { id: 1, f: tx("Vade"), k: tx("Kısa ve orta (spot)"), b: tx("Orta ve uzun"), a: tx("Orta ve uzun") },
    { id: 2, f: tx("Sinyal mumu"), k: tx("15 dk · 4 saat kapanışı"), b: tx("Günlük kapanış"), a: tx("Günlük · haftalık kapanış") },
    { id: 3, f: tx("Para birimi"), k: "$ (USDT)", b: "₺", a: "$" },
    { id: 4, f: tx("Özel kurallar"), k: tx("BTC kapısı, likidite, duygu"), b: tx("BIST 100’e göre güç, tavan/boşluk, tam adet"), a: tx("Bilanço takvimi, gap riski") },
  ];
  return h(SiteShell, { active: "ozellikler" },
    PageHero(tx("Özellikler"), tx("Bir panel, üç piyasa"), tx("Portföyünü takip et, grafiğe bak, kapanışla analiz al. Hepsi Türkçe, büyük yazıyla, koyu ya da açık temada.")),
    h("section", { key: "f", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      h("div", { className: "kp-grid kp-g-3" },
        h(K.FeatureCard, { icon: "portfolio", title: tx("Portföyüm"), items: [tx("Pozisyon başına alış, son kapanış, değer, K/Z"), tx("Stop ve hedef; stop yalnız yükselir"), tx("“Sattım” ile kapanış kaydı, nakit takibi")] }),
        h(K.FeatureCard, { icon: "chart", title: tx("Grafik & Analiz"), items: [tx("Mum grafiği, SMA 20/50/200, RSI 14, hacim"), tx("Tek düğme: “Analiz et”"), tx("Kurallara göre yapay zekâ açıklaması")] }),
        h(K.FeatureCard, { icon: "macro", title: tx("Makro"), items: [tx("Risk rejimi ve piyasa göstergeleri"), tx("TCMB, TÜİK, ABD veri takvimi"), tx("Korku-açgözlülük endeksi")] }),
        h(K.FeatureCard, { icon: "send", title: "Telegram", items: [tx("Analiz sonucu telefona"), tx("Kendi alarmların: fiyat ya da RSI kapanışı"), tx("/bagla KOD ile tek adımda bağlama")] }),
        h(K.FeatureCard, { icon: "key", title: tx("Kendi anahtarın"), items: [tx("DeepSeek ya da NVIDIA anahtarı"), tx("Günlük analiz hakkın artar"), tx("Şifreli saklanır, istediğinde silinir")] }),
        h(K.FeatureCard, { icon: "account", title: tx("Okunaklı arayüz"), items: [tx("Tarayıcı yakınlaştırmasıyla uyumlu"), tx("Koyu ve açık tema"), tx("Renk yalnız anlam için")] })))),
    h("section", { key: "t", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      SecHead(tx("Karşılaştırma"), tx("Piyasaya göre ne değişir"), null),
      h(K.DataTable, { rows, rowKey: "id", columns: [
        { key: "f", label: tx("Özellik"), render: (r) => h("b", null, r.f) },
        { key: "k", label: tx("Kripto") }, { key: "b", label: "BIST" }, { key: "a", label: tx("ABD") }] }))),
    h(CTA, { key: "cta" }));
}

export function How() {
  useLang();
  const HOW_ = HOW();
  const steps = [
    { ...HOW_[0], extra: h("div", { className: "kp-tile", style: { maxWidth: "26rem" } }, h("span", { className: "kp-tile__label" }, tx("Örnek kayıt")), h("span", { className: "kp-tile__val" }, tx("THYAO · 120 adet · ₺281,20 · stop ₺296,00"))) },
    { ...HOW_[1], extra: h("div", { className: "kp-note" }, tx("Son mum henüz kapanmamış olabilir; grafik bunu her zaman yazar.")) },
    { ...HOW_[2], extra: h("div", { style: { display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center" } }, h(K.Button, { variant: "primary", href: "/kayit" }, tx("Analiz et")), h(K.QuotaMeter, { used: 2, limit: 5, ownLimit: 50 })) },
    { ...HOW_[3], extra: h(K.MessagePreview, { time: tx("Bugün 18:12") }, h("div", { className: "kp-msg__row" }, h("b", null, tx("BTC · 4 saat")), h(K.DecisionBadge, { decision: "AL" })), h("p", null, tx("Kapanış $64.250 direncin üstünde."))) },
  ];
  return h(SiteShell, { active: "nasil-calisir" },
    PageHero(tx("Nasıl çalışır"), tx("Sen eklersin, kod sayar, kapanış konuşur"), tx("Kapanış hiçbir şeyi senin yerine yapmaz. Bilgiyi düzenler, kuralları sayar ve sonucu düz Türkçeyle yazar.")),
    h("section", { key: "s", className: "kp-sec" }, h("div", { className: "kp-wrap" }, h(K.StepList, { layout: "column", steps }))),
    h("section", { key: "r", className: "kp-sec" }, h("div", { className: "kp-wrap kp-two" },
      h("div", null, SecHead(tx("Analiz ne içerir"), tx("Bir karar, gerekçesiyle"), null),
        h("ul", { className: "kp-bullets" },
          check([h("b", { key: "b" }, tx("Bot kararı: ")), tx("AL, BEKLE, PAS ya da TUT. Bir rozettir; düğme değildir.")]),
          check([h("b", { key: "b" }, tx("Kurallar: ")), tx("kapanış teyidi, trend, hacim, R/R; her biri nedeniyle.")]),
          check([h("b", { key: "b" }, tx("Seviyeler: ")), tx("destek, direnç, R/R; kodla hesaplanır.")]),
          check([h("b", { key: "b" }, tx("Açıklama: ")), tx("yapay zekâ modelinin adıyla, kısa bir yorum.")]))),
      h(K.GateList, { items: [
        { status: "gecti", rule: tx("Kapanış teyidi"), detail: tx("4 saatlik mum $64.100 direncinin üstünde kapandı") },
        { status: "gecti", rule: tx("Hacim"), detail: tx("Ortalamanın 1,6 katı") },
        { status: "uyari", rule: tx("Duygu"), blocking: false, detail: tx("Korku-açgözlülük 68: ilk kademe küçük") },
        { status: "kaldi", rule: tx("Makro"), detail: tx("ABD enflasyon verisine 1 saat var: yeni giriş yok") }] }))),
    h(CTA, { key: "cta" }));
}

export function Rules() {
  useLang();
  const rule = (n, title, text, visual) => h("section", { key: n, className: "kp-sec" }, h("div", { className: "kp-wrap kp-two" },
    h("div", null, h("div", { className: "kp-sec__kicker" }, tx("Kural") + " " + n), h("h2", { className: "kp-sec__title" }, title), h("div", { className: "kp-prose", style: { marginTop: "1rem" } }, text)),
    visual));
  const ladder = h("div", { className: "kp-card", style: { display: "flex", flexDirection: "column", gap: "0.75rem" } },
    h("div", { className: "kp-card__title" }, tx("THYAO · stop geçmişi (örnek)")),
    [[tx("22 Eyl"), "₺290,00", tx("Alış günü"), "gecti"], [tx("24 Eyl"), "₺296,00", tx("Yükseltildi"), "gecti"], [tx("25 Eyl"), "₺300,00", tx("Yükseltildi"), "gecti"], [tx("25 Eyl"), "₺288,00", tx("Reddedildi: stop aşağı çekilemez"), "kaldi"]].map((r, i) =>
      h("div", { key: i, className: "kp-tile", style: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" } },
        h("span", null, h("span", { className: "kp-tile__label" }, r[0] + " · "), h("b", { style: r[3] === "kaldi" ? { textDecoration: "line-through", color: "var(--text-3)" } : null }, r[1])),
        h("span", { className: r[3] === "kaldi" ? "kp-num-down" : "kp-muted" }, r[2]))));
  return h(SiteShell, { active: "kurallar" },
    PageHero(tx("Kurallar"), tx("Kurallar kodda, pazarlık yok"), tx("Her kural her analizde aynı sırayla sayılır. Bir kural kalırsa karar AL olamaz; eksik veri geçti sayılmaz.")),
    rule(1, tx("Kapanış teyidi"), [h("p", { key: 1 }, tx("Sinyal yalnız mum "), h("b", null, tx("kapandığında")), tx(" sayılır. Mum içinde seviyeyi delen fitil ya da iğne sinyal değildir.")), h("p", { key: 2 }, tx("Kripto 15 dk ve 4 saat, BIST ve ABD günlük kapanışla değerlendirilir. Son mum kapanmadıysa grafik bunu yazar."))], h(K.CloseRuleDiagram, null)),
    rule(2, tx("Goalpost yasağı"), [h("p", { key: 1 }, tx("Açık pozisyonda stop "), h("b", null, tx("yalnız yukarı")), tx(" taşınır. “Biraz daha bekleyeyim” diye stopu aşağı çekmek engellenir.")), h("p", { key: 2 }, tx("Panelde “Stopu yükselt” vardır; stopu düşüren bir düğme yoktur."))], ladder),
    rule(3, tx("Sayıları kod hesaplar"), [h("p", { key: 1 }, tx("R/R, stop mesafesi, hacim oranı, rejim skoru ve kapı sonuçları kodda hesaplanır.")), h("p", { key: 2 }, tx("Yapay zekâ bu sayıları "), h("b", null, tx("değiştirmez")), tx("; yalnız sade bir dille açıklar. Modelin adı her yorumda yazar."))],
      h(K.AiNote, { model: "DeepSeek V4.1 Flash", time: "18:12" }, h("p", null, tx("Direnç ₺318,00. Kapanış bunun üstünde olmadığı için kod BEKLE dedi; ben bu kararı değiştiremem.")))),
    rule(4, tx("İşlem yok"), [h("p", { key: 1 }, tx("Kapanış hiçbir aracı kuruma ya da borsaya bağlanmaz. Emir göndermez, kaldıraç kullanmaz, borsa şifresi istemez.")), h("p", { key: 2 }, tx("Alım ve satışı sen yaparsın; istersen panele kaydedersin."))],
      h(K.Callout, { tone: "info", title: tx("Yatırım tavsiyesi değildir") }, tx("Kapanış bir karar destek aracıdır. Sonuçlar bilgilendirme amaçlıdır."))));
}

export function Faq() {
  useLang();
  const groups = [
    [tx("Genel"), [
      { q: tx("Ücretli mi?"), a: [h("p", { key: 1 }, tx("Hayır, hesap ücretsiz. Sitenin ortak yapay zekâ anahtarıyla her gün sınırlı sayıda analiz hakkın var.")), h("p", { key: 2 }, tx("Kendi anahtarını eklersen hakkın artar; o anahtarın ücreti sağlayıcıyla senin aranda."))] },
      { q: tx("Hangi piyasalar var?"), a: h("p", null, tx("Kripto (yalnız spot), BIST ve ABD hisseleri. Kaldıraç, vadeli ve açığa satış yok.")) },
      { q: tx("Bot benim yerime işlem yapar mı?"), a: [h("p", { key: 1 }, h("b", null, tx("Hayır.")), tx(" Kapanış hiçbir aracı kuruma ya da borsaya bağlanmaz, emir göndermez, aracı kurum şifreni istemez.")), h("p", { key: 2 }, tx("Alım ve satışı sen yaparsın; istersen panele kaydedersin."))] },
      { q: tx("Neden mum kapanışını bekliyor?"), a: h("p", null, tx("Mum içindeki fitiller çoğu zaman geri döner. Kapanış teyidi yanlış kırılımları eler; bu yüzden sinyal yalnız mum kapanınca sayılır.")) },
      { q: tx("Stopumu neden aşağı çekemiyorum?"), a: h("p", null, tx("Goalpost yasağı: açık pozisyonda stop yalnız yukarı taşınır. Zararı büyütmeyi önlemek için bu kural kodda.")) },
    ]],
    [tx("Hesap ve gizlilik"), [
      { q: tx("Kendi API anahtarımı neden gireyim?"), a: [h("p", { key: 1 }, tx("Ortak anahtarla günlük analiz hakkın sınırlı. Kendi DeepSeek ya da NVIDIA anahtarınla hakkın artar ve analizin senin anahtarınla çalışır.")), h("p", { key: 2 }, tx("Anahtar şifreli saklanır, ekranda yalnız son 4 hanesi görünür, istediğin an silersin. Anahtarın başkasının analizinde kullanılmaz."))] },
      { q: tx("Portföyümü kim görür?"), a: [h("p", { key: 1 }, tx("Portföyün yalnız senin hesabına bağlıdır; başka kullanıcılar görmez. Analiz sonucun yalnız sana ve bağladıysan kendi Telegram’ına gider.")), h("p", { key: 2 }, tx("Sistem yöneticisinin veritabanına teknik erişimi vardır. Verini istediğin an indirip hesabını silebilirsin."))] },
      { q: tx("Verilerimi nasıl silerim?"), a: h("p", null, tx("Hesap & Telegram → Hesabımı sil. Onay için SİL yazarsın; portföyün, analizlerin ve anahtarların kalıcı olarak silinir.")) },
    ]],
    ["Telegram", [
      { q: tx("Telegram’ı nasıl bağlarım?"), a: [h("p", { key: 1 }, tx("Panelde Hesap & Telegram → “Telegram’ı bağla”ya bas. Çıkan tek kullanımlık kodu 10 dakika içinde Kapanış botuna gönder:")), h("p", { key: 2 }, h("span", { className: "kp-cmd" }, "/bagla KP-XXXXXXXX"))] },
      { q: tx("Telegram’a ne gelir?"), a: h("p", null, tx("Panelden istediğin analizlerin sonuçları, Alarmlarım sayfasında kurduğun fiyat/RSI alarmları ve portföyündeki pozisyonların stop/hedef uyarıları (hepsi kapanışla). Başka kullanıcılarınki gelmez.")) },
    ]],
  ];
  return h(SiteShell, { active: "sss" },
    PageHero(tx("SSS"), tx("Sık sorulan sorular"), h("span", null, tx("Bulamadığın bir şey varsa "), h("a", { href: "/iletisim", className: "kp-link" }, tx("iletişim sayfasından")), tx(" yaz."))),
    h("section", { key: "q", className: "kp-sec", style: { paddingTop: 0 } }, h("div", { className: "kp-wrap", style: { display: "flex", flexDirection: "column", gap: "2.5rem" } },
      groups.map((g, i) => h("div", { key: g[0] }, h("h2", { className: "kp-card__title", style: { marginBottom: "0.5rem" } }, g[0]), h(K.FaqList, { id: "g" + i, items: g[1], defaultOpen: i === 0 ? 0 : -1 }))))),
    h(CTA, { key: "cta" }));
}

// Mevcut içerik sayfaları (İletişim, Gizlilik, Koşullar) aynı site çerçevesinde
export function SitePage({ children }) {
  return h(SiteShell, { active: null }, h("div", { className: "kp-wrap" }, children));
}

export function Terms() {
  useLang();
  const items = [
    [tx("Ne sunuyoruz"), tx("Kapanış bir karar destek aracıdır: kripto, BIST ve ABD hisseleri için kuralları kodla sayar, sonucu açıklar. Yatırım tavsiyesi vermez.")],
    [tx("İşlem yok"), tx("Kapanış hiçbir aracı kuruma ya da borsaya bağlanmaz, emir göndermez, aracı kurum şifresi istemez. Alım ve satış kararı ve sorumluluğu sana aittir.")],
    [tx("Veri"), tx("Fiyatlar ücretsiz kaynaklardan gelir ve gecikmeli ya da eksik olabilir. Emir fiyatını her zaman aracı kurumundan kontrol et.")],
    [tx("Hesap"), tx("Hesabını başkasıyla paylaşma. Kendi API anahtarını girersen o anahtarın kullanım ücreti sağlayıcıyla senin aranda. Hesabını istediğin an silebilirsin.")],
    [tx("Kullanım sınırı"), tx("Ortak yapay zekâ kapasitesi sınırlıdır; günlük analiz hakları değişebilir. Kötüye kullanımda hesap kapatılabilir.")],
    [tx("Değişiklik"), tx("Bu koşullar güncellenebilir; güncel metin her zaman bu sayfadadır.")],
  ];
  return h(SitePage, null,
    h("section", { className: "kp-sec" },
      h("div", { className: "kp-sec__head" }, h("div", { className: "kp-sec__kicker" }, tx("Yasal")), h("h1", { className: "kp-hero__title", style: { fontSize: "2.75rem" } }, tx("Kullanım koşulları"))),
      h("div", { className: "kp-prose", style: { maxWidth: "48rem" } },
        items.map(([t, b]) => h("div", { key: t, style: { marginBottom: "1.5rem" } }, h("h2", { className: "kp-card__title" }, t), h("p", null, b))),
        h("p", { className: "kp-note" }, tx("Son güncelleme: 27 Eylül 2026 · "), h("a", { href: "/gizlilik", className: "kp-link" }, tx("Gizlilik ve KVKK"))))));
}

export function NotFound() {
  useLang();
  return h(SiteShell, { active: null }, PageHero("404", tx("Bu sayfa yok"), tx("Adres yanlış yazılmış ya da sayfa kaldırılmış olabilir.")),
    h("section", { className: "kp-sec" }, h("div", { className: "kp-wrap kp-cta__actions" },
      h(K.Button, { variant: "primary", href: "/" }, tx("Ana sayfa")), h(K.Button, { variant: "secondary", href: "/app" }, tx("Panele git")))));
}
