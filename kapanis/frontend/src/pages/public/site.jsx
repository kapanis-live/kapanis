// Tanıtım sitesi: Claude Design "Kapanış" sistemi (Site sayfaları). Metinler sistemin gerçekte yaptığıyla uyumlu:
// kullanıcıya Telegram'dan analiz sonuçları ve kendi alarmları (fiyat/RSI kapanışı, pozisyon stop/hedef) gider.
import { createElement as h, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { K, U } from "@/ds";

// Site içindeki /... linkleri (başlık, alt bilgi, düğmeler) sayfa yenilemeden açılsın
export function SiteShell({ active, children }) {
  const navigate = useNavigate();
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
    h("h2", { className: "kp-cta__title" }, "Portföyünü ekle, kapanışı bekle."),
    h("div", { className: "kp-cta__actions" }, h(K.Button, { variant: "primary", href: "/kayit" }, "Ücretsiz hesap aç"), h(K.Button, { variant: "secondary", href: "/giris" }, "Giriş yap"))));
}
const check = (content) => h("li", null, h(K.Icon, { name: "check", size: 18, stroke: 2.25 }), h("span", null, ...[].concat(content)));

const MARKETS = [
  { kicker: "Kripto", dot: "var(--cat-2)", title: "Yalnız spot", text: "Binance fiyatlarıyla BTC, ETH ve diğer spot pariteler.", items: ["15 dk ve 4 saatlik mum kapanışı", "Kaldıraç, vadeli, açığa satış yok", "Dolar bazında K/Z"] },
  { kicker: "BIST", dot: "var(--cat-1)", title: "Orta ve uzun vade", text: "BIST hisseleri, günlük kapanış ve BIST 100 karşılaştırması.", items: ["Günlük kapanış teyidi", "BIST 100’e göre güç, maliyet sonrası R/R", "Tam adet, TL bazında K/Z"] },
  { kicker: "ABD", dot: "var(--cat-3)", title: "Hisseler", text: "ABD hisseleri, dolar bazında takip.", items: ["Günlük ve haftalık kapanış", "Bilanço takvimi uyarısı", "Dolar bazında K/Z"] },
];
const RULES = [
  { icon: "chart", title: "Kapanış teyidi", detail: "Sinyal yalnız mum kapanışıyla sayılır. Fitil ve iğne sayılmaz." },
  { icon: "stopup", title: "Goalpost yasağı", detail: "Açık pozisyonda stop yalnız yukarı taşınır, asla aşağı çekilmez." },
  { icon: "code", title: "Sayıları kod hesaplar", detail: "R/R, stop, hacim ve kurallar kodda. Yapay zekâ yalnız açıklar." },
  { icon: "shield", title: "İşlem yok", detail: "Emir göndermez, kaldıraç yok, aracı kurum şifresi istemez." },
];
const HOW = [
  { title: "Portföyünü ekle", detail: "Aldığın kodu, adedi, alış fiyatını ve stopunu gir. Hedef isteğe bağlı." },
  { title: "Grafiğe bak", detail: "Mum grafiği, SMA 20/50/200, RSI ve hacim; İstanbul saatiyle." },
  { title: "“Analiz et”e bas", detail: "Kod son kapanmış mumla kuralları sayar, yapay zekâ sonucu açıklar." },
  { title: "Sonuç panelde", detail: "İstersen aynı sonuç Telegram’dan da gelir." },
];

function HeroVisual() {
  const c = useMemo(() => U.demoCandles("THYAO", "1d", 312.5, 60), []);
  return h("div", { className: "kp-card", style: { display: "flex", flexDirection: "column", gap: "1rem" } },
    h("div", { className: "kp-sighead" },
      h("div", { className: "kp-sighead__id" }, h(K.Ticker, { symbol: "THYAO", name: "Günlük · örnek", logo: { code: "THYAO", market: "BIST" } }),
        h("span", { style: { fontSize: "1.625rem", fontWeight: 700 } }, "₺312,50")),
      h(K.DecisionBadge, { decision: "BEKLE", size: "lg" })),
    h(K.MiniChart, { candles: c, height: 150, symbol: "THYAO" }),
    h("div", { className: "kp-tile", style: { gap: "0.375rem" } },
      h("span", { className: "kp-tile__label" }, "Sonuç"),
      h("span", { style: { fontWeight: 600 } }, "Direnç ₺318,00. Günlük mum bunun üstünde KAPANMADAN sinyal sayılmaz.")),
    h(K.GateList, { summary: false, items: [
      { status: "gecti", rule: "Trend", detail: "Fiyat SMA 50 ve SMA 200 üstünde" },
      { status: "uyari", rule: "Kapanış teyidi", detail: "Fitil ₺319,40’a çıktı, kapanış ₺312,50: sayılmadı" },
      { status: "gecti", rule: "R/R (maliyet sonrası)", detail: "2,1 · eşik 1,5" },
    ] }),
    h("p", { className: "kp-note" }, "Örnek analiz · yatırım tavsiyesi değildir"));
}

export function Home() {
  return h(SiteShell, { active: null },
    h("section", { key: "hero", className: "kp-wrap kp-hero" },
      h("div", null,
        h("div", { className: "kp-hero__kicker" }, MARKETS.map((m) => h("span", { key: m.kicker, className: "kp-hero__pill" }, h("i", { style: { background: m.dot } }), m.kicker))),
        h("h1", { className: "kp-hero__title" }, "Dokunma değil, kapanış."),
        h("p", { className: "kp-hero__lead" }, "Kapanış, kripto, BIST ve ABD hisseleri için kişisel karar destek panelidir. Kuralları kod sayar, sinyali yalnız mum kapanınca verir, yapay zekâ yalnız açıklar. İşlem yapmaz."),
        h("div", { className: "kp-hero__actions" },
          h(K.Button, { variant: "primary", href: "/kayit" }, "Ücretsiz hesap aç"),
          h(K.Button, { variant: "secondary", href: "/giris" }, "Giriş yap")),
        h("p", { className: "kp-hero__note" }, "Google ya da e-posta ile giriş · aracı kurum şifresi istemez")),
      h(HeroVisual, null)),
    h("section", { key: "mk", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      SecHead("Piyasalar", "Üç piyasa, aynı kurallar", "Her piyasa kendi para biriminde ve kendi vadesinde; kapanış teyidi hepsinde aynı."),
      h("div", { className: "kp-grid kp-g-3" }, MARKETS.map((m) => h(K.FeatureCard, { key: m.kicker, kicker: m.kicker, dot: m.dot, title: m.title, items: m.items }, m.text))))),
    h("section", { key: "how", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      SecHead("Nasıl çalışır", "Dört adım, hepsi senin kontrolünde", null),
      h(K.StepList, { steps: HOW }))),
    h("section", { key: "rules", className: "kp-band" }, h("div", { className: "kp-wrap", style: { paddingTop: "2rem", paddingBottom: "2rem" } },
      h("div", { className: "kp-sec__kicker" }, "Kurallar kodda"),
      h(K.RuleStrip, { items: RULES }),
      h("a", { href: "/kurallar", className: "kp-link", style: { display: "inline-block", marginTop: "0.5rem" } }, "Kuralların hepsi"))),
    h("section", { key: "tg", className: "kp-sec" }, h("div", { className: "kp-wrap kp-two" },
      h("div", null,
        SecHead("Telegram", "Sonuç telefonuna da gelsin", "Panele bakmadığın an da analiz sonucunu kaçırma. Bağlamak bir komut."),
        h("ul", { className: "kp-bullets" },
          check("İstediğin analizin sonucu tek mesajda: karar, gerekçe, seviyeler."),
          check("Yalnız senin sonuçların; başkasının analizi sana gelmez."),
          check(["Bağlamak için panelden kod al, bota ", h("span", { key: "c", className: "kp-cmd" }, "/bagla KP-XXXXXXXX"), " gönder."]))),
      h(K.MessagePreview, { time: "Bugün 18:12" },
        h("div", { className: "kp-msg__row" }, h("b", null, "THYAO · Günlük"), h(K.DecisionBadge, { decision: "BEKLE" })),
        h("p", null, "Kapanış ₺312,50. Direnç ₺318,00 üstünde günlük kapanış yok; fitil sayılmadı."),
        h("p", null, "R/R 2,1 · senin stopun: ₺296,00."),
        h("p", { className: "kp-note" }, "Yatırım tavsiyesi değildir. Bot işlem yapmaz.")))),
    h("section", { key: "trust", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      SecHead("Güven", "Verin ve paran sende kalır", null),
      h("div", { className: "kp-grid kp-g-4" },
        h(K.FeatureCard, { icon: "lock", title: "Şifren bizde değil" }, "Google ya da e-posta + doğrulama koduyla girersin. Şifreler Kapanış’ta tutulmaz."),
        h(K.FeatureCard, { icon: "key", title: "Kendi yapay zekâ anahtarın" }, "İstersen DeepSeek ya da NVIDIA anahtarını eklersin. Şifreli saklanır, yalnız son 4 hanesi görünür."),
        h(K.FeatureCard, { icon: "download", title: "Verin senin", footer: h("a", { href: "/gizlilik", className: "kp-link" }, "Gizlilik ve KVKK") }, "Tüm verini tek tıkla indirir, hesabını istediğin an silersin."),
        h(K.FeatureCard, { icon: "shield", title: "İşlem yapmaz" }, "Aracı kuruma bağlanmaz, emir göndermez, borsa şifresi istemez.")),
      h("div", { style: { marginTop: "1.5rem" } }, h(K.Callout, { tone: "info", title: "Yatırım tavsiyesi değildir" }, "Kapanış kurallarını açıklar ve sayar; karar ve işlem her zaman senin.")))),
    h(CTA, { key: "cta" }));
}

export function Features() {
  const rows = [
    { id: 1, f: "Vade", k: "Kısa ve orta (spot)", b: "Orta ve uzun", a: "Orta ve uzun" },
    { id: 2, f: "Sinyal mumu", k: "15 dk · 4 saat kapanışı", b: "Günlük kapanış", a: "Günlük · haftalık kapanış" },
    { id: 3, f: "Para birimi", k: "$ (USDT)", b: "₺", a: "$" },
    { id: 4, f: "Özel kurallar", k: "BTC kapısı, likidite, duygu", b: "BIST 100’e göre güç, tavan/boşluk, tam adet", a: "Bilanço takvimi, gap riski" },
  ];
  return h(SiteShell, { active: "ozellikler" },
    PageHero("Özellikler", "Bir panel, üç piyasa", "Portföyünü takip et, grafiğe bak, kapanışla analiz al. Hepsi Türkçe, büyük yazıyla, koyu ya da açık temada."),
    h("section", { key: "f", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      h("div", { className: "kp-grid kp-g-3" },
        h(K.FeatureCard, { icon: "portfolio", title: "Portföyüm", items: ["Pozisyon başına alış, son kapanış, değer, K/Z", "Stop ve hedef; stop yalnız yükselir", "“Sattım” ile kapanış kaydı, nakit takibi"] }),
        h(K.FeatureCard, { icon: "chart", title: "Grafik & Analiz", items: ["Mum grafiği, SMA 20/50/200, RSI 14, hacim", "Tek düğme: “Analiz et”", "Kurallara göre yapay zekâ açıklaması"] }),
        h(K.FeatureCard, { icon: "macro", title: "Makro", items: ["Risk rejimi ve piyasa göstergeleri", "TCMB, TÜİK, ABD veri takvimi", "Korku-açgözlülük endeksi"] }),
        h(K.FeatureCard, { icon: "send", title: "Telegram", items: ["Analiz sonucu telefona", "Kendi alarmların: fiyat ya da RSI kapanışı", "/bagla KOD ile tek adımda bağlama"] }),
        h(K.FeatureCard, { icon: "key", title: "Kendi anahtarın", items: ["DeepSeek ya da NVIDIA anahtarı", "Günlük analiz hakkın artar", "Şifreli saklanır, istediğinde silinir"] }),
        h(K.FeatureCard, { icon: "account", title: "Okunaklı arayüz", items: ["Tarayıcı yakınlaştırmasıyla uyumlu", "Koyu ve açık tema", "Renk yalnız anlam için"] })))),
    h("section", { key: "t", className: "kp-sec" }, h("div", { className: "kp-wrap" },
      SecHead("Karşılaştırma", "Piyasaya göre ne değişir", null),
      h(K.DataTable, { rows, rowKey: "id", columns: [
        { key: "f", label: "Özellik", render: (r) => h("b", null, r.f) },
        { key: "k", label: "Kripto" }, { key: "b", label: "BIST" }, { key: "a", label: "ABD" }] }))),
    h(CTA, { key: "cta" }));
}

export function How() {
  const steps = [
    { ...HOW[0], extra: h("div", { className: "kp-tile", style: { maxWidth: "26rem" } }, h("span", { className: "kp-tile__label" }, "Örnek kayıt"), h("span", { className: "kp-tile__val" }, "THYAO · 120 adet · ₺281,20 · stop ₺296,00")) },
    { ...HOW[1], extra: h("div", { className: "kp-note" }, "Son mum henüz kapanmamış olabilir; grafik bunu her zaman yazar.") },
    { ...HOW[2], extra: h("div", { style: { display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center" } }, h(K.Button, { variant: "primary", href: "/kayit" }, "Analiz et"), h(K.QuotaMeter, { used: 2, limit: 5, ownLimit: 50 })) },
    { ...HOW[3], extra: h(K.MessagePreview, { time: "Bugün 18:12" }, h("div", { className: "kp-msg__row" }, h("b", null, "BTC · 4 saat"), h(K.DecisionBadge, { decision: "AL" })), h("p", null, "Kapanış $64.250 direncin üstünde.")) },
  ];
  return h(SiteShell, { active: "nasil-calisir" },
    PageHero("Nasıl çalışır", "Sen eklersin, kod sayar, kapanış konuşur", "Kapanış hiçbir şeyi senin yerine yapmaz. Bilgiyi düzenler, kuralları sayar ve sonucu düz Türkçeyle yazar."),
    h("section", { key: "s", className: "kp-sec" }, h("div", { className: "kp-wrap" }, h(K.StepList, { layout: "column", steps }))),
    h("section", { key: "r", className: "kp-sec" }, h("div", { className: "kp-wrap kp-two" },
      h("div", null, SecHead("Analiz ne içerir", "Bir karar, gerekçesiyle", null),
        h("ul", { className: "kp-bullets" },
          check([h("b", { key: "b" }, "Bot kararı: "), "AL, BEKLE, PAS ya da TUT. Bir rozettir; düğme değildir."]),
          check([h("b", { key: "b" }, "Kurallar: "), "kapanış teyidi, trend, hacim, R/R; her biri nedeniyle."]),
          check([h("b", { key: "b" }, "Seviyeler: "), "destek, direnç, R/R; kodla hesaplanır."]),
          check([h("b", { key: "b" }, "Açıklama: "), "yapay zekâ modelinin adıyla, kısa bir yorum."]))),
      h(K.GateList, { items: [
        { status: "gecti", rule: "Kapanış teyidi", detail: "4 saatlik mum $64.100 direncinin üstünde kapandı" },
        { status: "gecti", rule: "Hacim", detail: "Ortalamanın 1,6 katı" },
        { status: "uyari", rule: "Duygu", blocking: false, detail: "Korku-açgözlülük 68: ilk kademe küçük" },
        { status: "kaldi", rule: "Makro", detail: "ABD enflasyon verisine 1 saat var: yeni giriş yok" }] }))),
    h(CTA, { key: "cta" }));
}

export function Rules() {
  const rule = (n, title, text, visual) => h("section", { key: n, className: "kp-sec" }, h("div", { className: "kp-wrap kp-two" },
    h("div", null, h("div", { className: "kp-sec__kicker" }, "Kural " + n), h("h2", { className: "kp-sec__title" }, title), h("div", { className: "kp-prose", style: { marginTop: "1rem" } }, text)),
    visual));
  const ladder = h("div", { className: "kp-card", style: { display: "flex", flexDirection: "column", gap: "0.75rem" } },
    h("div", { className: "kp-card__title" }, "THYAO · stop geçmişi (örnek)"),
    [["22 Eyl", "₺290,00", "Alış günü", "gecti"], ["24 Eyl", "₺296,00", "Yükseltildi", "gecti"], ["25 Eyl", "₺300,00", "Yükseltildi", "gecti"], ["25 Eyl", "₺288,00", "Reddedildi: stop aşağı çekilemez", "kaldi"]].map((r, i) =>
      h("div", { key: i, className: "kp-tile", style: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" } },
        h("span", null, h("span", { className: "kp-tile__label" }, r[0] + " · "), h("b", { style: r[3] === "kaldi" ? { textDecoration: "line-through", color: "var(--text-3)" } : null }, r[1])),
        h("span", { className: r[3] === "kaldi" ? "kp-num-down" : "kp-muted" }, r[2]))));
  return h(SiteShell, { active: "kurallar" },
    PageHero("Kurallar", "Kurallar kodda, pazarlık yok", "Her kural her analizde aynı sırayla sayılır. Bir kural kalırsa karar AL olamaz; eksik veri geçti sayılmaz."),
    rule(1, "Kapanış teyidi", [h("p", { key: 1 }, "Sinyal yalnız mum ", h("b", null, "kapandığında"), " sayılır. Mum içinde seviyeyi delen fitil ya da iğne sinyal değildir."), h("p", { key: 2 }, "Kripto 15 dk ve 4 saat, BIST ve ABD günlük kapanışla değerlendirilir. Son mum kapanmadıysa grafik bunu yazar.")], h(K.CloseRuleDiagram, null)),
    rule(2, "Goalpost yasağı", [h("p", { key: 1 }, "Açık pozisyonda stop ", h("b", null, "yalnız yukarı"), " taşınır. “Biraz daha bekleyeyim” diye stopu aşağı çekmek engellenir."), h("p", { key: 2 }, "Panelde “Stopu yükselt” vardır; stopu düşüren bir düğme yoktur.")], ladder),
    rule(3, "Sayıları kod hesaplar", [h("p", { key: 1 }, "R/R, stop mesafesi, hacim oranı, rejim skoru ve kapı sonuçları kodda hesaplanır."), h("p", { key: 2 }, "Yapay zekâ bu sayıları ", h("b", null, "değiştirmez"), "; yalnız sade bir dille açıklar. Modelin adı her yorumda yazar.")],
      h(K.AiNote, { model: "DeepSeek V4.1 Flash", time: "18:12" }, h("p", null, "Direnç ₺318,00. Kapanış bunun üstünde olmadığı için kod BEKLE dedi; ben bu kararı değiştiremem."))),
    rule(4, "İşlem yok", [h("p", { key: 1 }, "Kapanış hiçbir aracı kuruma ya da borsaya bağlanmaz. Emir göndermez, kaldıraç kullanmaz, borsa şifresi istemez."), h("p", { key: 2 }, "Alım ve satışı sen yaparsın; istersen panele kaydedersin.")],
      h(K.Callout, { tone: "info", title: "Yatırım tavsiyesi değildir" }, "Kapanış bir karar destek aracıdır. Sonuçlar bilgilendirme amaçlıdır.")));
}

export function Faq() {
  const groups = [
    ["Genel", [
      { q: "Ücretli mi?", a: [h("p", { key: 1 }, "Hayır, hesap ücretsiz. Sitenin ortak yapay zekâ anahtarıyla her gün sınırlı sayıda analiz hakkın var."), h("p", { key: 2 }, "Kendi anahtarını eklersen hakkın artar; o anahtarın ücreti sağlayıcıyla senin aranda.")] },
      { q: "Hangi piyasalar var?", a: h("p", null, "Kripto (yalnız spot), BIST ve ABD hisseleri. Kaldıraç, vadeli ve açığa satış yok.") },
      { q: "Bot benim yerime işlem yapar mı?", a: [h("p", { key: 1 }, h("b", null, "Hayır."), " Kapanış hiçbir aracı kuruma ya da borsaya bağlanmaz, emir göndermez, aracı kurum şifreni istemez."), h("p", { key: 2 }, "Alım ve satışı sen yaparsın; istersen panele kaydedersin.")] },
      { q: "Neden mum kapanışını bekliyor?", a: h("p", null, "Mum içindeki fitiller çoğu zaman geri döner. Kapanış teyidi yanlış kırılımları eler; bu yüzden sinyal yalnız mum kapanınca sayılır.") },
      { q: "Stopumu neden aşağı çekemiyorum?", a: h("p", null, "Goalpost yasağı: açık pozisyonda stop yalnız yukarı taşınır. Zararı büyütmeyi önlemek için bu kural kodda.") },
    ]],
    ["Hesap ve gizlilik", [
      { q: "Kendi API anahtarımı neden gireyim?", a: [h("p", { key: 1 }, "Ortak anahtarla günlük analiz hakkın sınırlı. Kendi DeepSeek ya da NVIDIA anahtarınla hakkın artar ve analizin senin anahtarınla çalışır."), h("p", { key: 2 }, "Anahtar şifreli saklanır, ekranda yalnız son 4 hanesi görünür, istediğin an silersin. Anahtarın başkasının analizinde kullanılmaz.")] },
      { q: "Portföyümü kim görür?", a: [h("p", { key: 1 }, "Portföyün yalnız senin hesabına bağlıdır; başka kullanıcılar görmez. Analiz sonucun yalnız sana ve bağladıysan kendi Telegram’ına gider."), h("p", { key: 2 }, "Sistem yöneticisinin veritabanına teknik erişimi vardır. Verini istediğin an indirip hesabını silebilirsin.")] },
      { q: "Verilerimi nasıl silerim?", a: h("p", null, "Hesap & Telegram → Hesabımı sil. Onay için SİL yazarsın; portföyün, analizlerin ve anahtarların kalıcı olarak silinir.") },
    ]],
    ["Telegram", [
      { q: "Telegram’ı nasıl bağlarım?", a: [h("p", { key: 1 }, "Panelde Hesap & Telegram → “Telegram’ı bağla”ya bas. Çıkan tek kullanımlık kodu 10 dakika içinde Kapanış botuna gönder:"), h("p", { key: 2 }, h("span", { className: "kp-cmd" }, "/bagla KP-XXXXXXXX"))] },
      { q: "Telegram’a ne gelir?", a: h("p", null, "Panelden istediğin analizlerin sonuçları, Alarmlarım sayfasında kurduğun fiyat/RSI alarmları ve portföyündeki pozisyonların stop/hedef uyarıları (hepsi kapanışla). Başka kullanıcılarınki gelmez.") },
    ]],
  ];
  return h(SiteShell, { active: "sss" },
    PageHero("SSS", "Sık sorulan sorular", h("span", null, "Bulamadığın bir şey varsa ", h("a", { href: "/iletisim", className: "kp-link" }, "iletişim sayfasından"), " yaz.")),
    h("section", { key: "q", className: "kp-sec", style: { paddingTop: 0 } }, h("div", { className: "kp-wrap", style: { display: "flex", flexDirection: "column", gap: "2.5rem" } },
      groups.map((g, i) => h("div", { key: g[0] }, h("h2", { className: "kp-card__title", style: { marginBottom: "0.5rem" } }, g[0]), h(K.FaqList, { id: "g" + i, items: g[1], defaultOpen: i === 0 ? 0 : -1 }))))),
    h(CTA, { key: "cta" }));
}

// Mevcut içerik sayfaları (İletişim, Gizlilik, Koşullar) aynı site çerçevesinde
export function SitePage({ children }) {
  return h(SiteShell, { active: null }, h("div", { className: "kp-wrap" }, children));
}

export function Terms() {
  const items = [
    ["Ne sunuyoruz", "Kapanış bir karar destek aracıdır: kripto, BIST ve ABD hisseleri için kuralları kodla sayar, sonucu açıklar. Yatırım tavsiyesi vermez."],
    ["İşlem yok", "Kapanış hiçbir aracı kuruma ya da borsaya bağlanmaz, emir göndermez, aracı kurum şifresi istemez. Alım ve satış kararı ve sorumluluğu sana aittir."],
    ["Veri", "Fiyatlar ücretsiz kaynaklardan gelir ve gecikmeli ya da eksik olabilir. Emir fiyatını her zaman aracı kurumundan kontrol et."],
    ["Hesap", "Hesabını başkasıyla paylaşma. Kendi API anahtarını girersen o anahtarın kullanım ücreti sağlayıcıyla senin aranda. Hesabını istediğin an silebilirsin."],
    ["Kullanım sınırı", "Ortak yapay zekâ kapasitesi sınırlıdır; günlük analiz hakları değişebilir. Kötüye kullanımda hesap kapatılabilir."],
    ["Değişiklik", "Bu koşullar güncellenebilir; güncel metin her zaman bu sayfadadır."],
  ];
  return h(SitePage, null,
    h("section", { className: "kp-sec" },
      h("div", { className: "kp-sec__head" }, h("div", { className: "kp-sec__kicker" }, "Yasal"), h("h1", { className: "kp-hero__title", style: { fontSize: "2.75rem" } }, "Kullanım koşulları")),
      h("div", { className: "kp-prose", style: { maxWidth: "48rem" } },
        items.map(([t, b]) => h("div", { key: t, style: { marginBottom: "1.5rem" } }, h("h2", { className: "kp-card__title" }, t), h("p", null, b))),
        h("p", { className: "kp-note" }, "Son güncelleme: 27 Eylül 2026 · ", h("a", { href: "/gizlilik", className: "kp-link" }, "Gizlilik ve KVKK")))));
}

export function NotFound() {
  return h(SiteShell, { active: null }, PageHero("404", "Bu sayfa yok", "Adres yanlış yazılmış ya da sayfa kaldırılmış olabilir."),
    h("section", { className: "kp-sec" }, h("div", { className: "kp-wrap kp-cta__actions" },
      h(K.Button, { variant: "primary", href: "/" }, "Ana sayfa"), h(K.Button, { variant: "secondary", href: "/app" }, "Panele git"))));
}
