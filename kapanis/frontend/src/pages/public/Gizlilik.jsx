import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API } from "@/lib/api";
import { useLang } from "@/lib/i18n";

// Gizlilik ve KVKK aydınlatma metni. Yalnız sistemin gerçekten topladığı veriyi anlatır.
// Hukuki danışmanlık değildir: yayına almadan önce bir uzmana kontrol ettirilmeli.
const SECTIONS = [
  ["Kim işliyor?", (c) => <>Kapanış'ı işleten kişi veri sorumlusudur. İletişim: {c ? <a className="text-info underline" href={`mailto:${c}`}>{c}</a> : <Link className="text-info underline" to="/iletisim">İletişim sayfası</Link>}.</>],
  ["Hangi veriler?", () => (
    <ul className="list-disc space-y-1 pl-5">
      <li><b>Hesap:</b> e-posta adresin ve adın. Giriş, Clerk üzerinden yapılır; şifren Kapanış'ta tutulmaz. Google ile girersen Google'ın verdiği e-posta ve ad kullanılır.</li>
      <li><b>Portföy:</b> Portföyüm sayfasına kendin yazdığın alışlar, satışlar, stop/hedef ve nakit.</li>
      <li><b>Analiz:</b> istediğin analizler (kod, piyasa, zaman ve cevap metni).</li>
      <li><b>Telegram (isteğe bağlı):</b> hesabını bağlarsan Telegram sohbet kimliğin ve kullanıcı adın.</li>
      <li><b>API anahtarı (isteğe bağlı):</b> kendi yapay zekâ anahtarını girersen şifrelenmiş olarak saklanır; ekranda yalnız son 4 hanesi görünür.</li>
    </ul>
  )],
  ["Ne için?", () => <>Hesabını açmak, portföyünü sana göstermek, istediğin analizi üretip sana (ve bağladıysan Telegram'ına) iletmek, kötüye kullanımı ve maliyeti sınırlamak (günlük analiz sınırı). Veriler reklam için kullanılmaz ve satılmaz.</>],
  ["Kimlerle paylaşılıyor?", () => (
    <ul className="list-disc space-y-1 pl-5">
      <li><b>Clerk</b> (giriş hizmeti): e-posta ve giriş bilgileri.</li>
      <li><b>MongoDB Atlas</b> (veritabanı, Frankfurt): hesabın, portföyün, analizlerin.</li>
      <li><b>Barındırma sağlayıcısı</b> (sunucu, Avrupa): verinin işlendiği makine.</li>
      <li><b>Yapay zekâ sağlayıcısı</b> (DeepSeek ya da NVIDIA): analiz için yalnız piyasa verisi ve istediğin kodlar gönderilir; e-postan ve portföyün gönderilmez.</li>
      <li><b>Telegram</b>: yalnız bağladıysan, sana gönderilen mesajlar.</li>
    </ul>
  )],
  ["Ne kadar süre?", () => <>Hesabın açık kaldığı sürece. Hesabını sildiğinde portföyün, analizlerin, istek kayıtların ve Clerk'teki giriş hesabın silinir.</>],
  ["Hakların", () => <>Verilerini görme ve indirme (Hesap → Verilerimi indir), düzeltme (Portföyüm), silme (Hesap → Hesabımı sil), Telegram bağlantısını ve API anahtarını istediğin an kaldırma. KVKK kapsamındaki diğer talepler için yukarıdaki iletişim adresine yazabilirsin.</>],
  ["Önemli", () => <>Kapanış yatırım tavsiyesi vermez, işlem yapmaz ve senden aracı kurum ya da borsa şifresi istemez.</>],
];

// English text of the same notice (shown when the visitor chose English). Same facts, same order.
const SECTIONS_EN = [
  ["Who processes the data?", (c) => <>The person who runs Kapanış is the data controller. Contact: {c ? <a className="text-info underline" href={`mailto:${c}`}>{c}</a> : <Link className="text-info underline" to="/iletisim">Contact page</Link>}.</>],
  ["Which data?", () => (
    <ul className="list-disc space-y-1 pl-5">
      <li><b>Account:</b> your e-mail address and name. Sign-in is done through Clerk; your password is not kept at Kapanış. If you sign in with Google, the e-mail and name given by Google are used.</li>
      <li><b>Portfolio:</b> the buys, sells, stop / target and cash you enter yourself on the My Portfolio page.</li>
      <li><b>Analysis:</b> the analyses you ask for (ticker, market, time and the answer text).</li>
      <li><b>Telegram (optional):</b> if you link your account, your Telegram chat id and user name.</li>
      <li><b>API key (optional):</b> if you enter your own AI key it is stored encrypted; only its last 4 characters are shown.</li>
    </ul>
  )],
  ["What for?", () => <>To open your account, to show you your portfolio, to produce the analysis you ask for and deliver it to you (and to your Telegram, if linked), and to limit abuse and cost (the daily analysis limit). The data is not used for advertising and is not sold.</>],
  ["Who is it shared with?", () => (
    <ul className="list-disc space-y-1 pl-5">
      <li><b>Clerk</b> (sign-in service): e-mail and sign-in details.</li>
      <li><b>MongoDB Atlas</b> (database, Frankfurt): your account, portfolio and analyses.</li>
      <li><b>Hosting provider</b> (server, Europe): the machine where the data is processed.</li>
      <li><b>AI provider</b> (DeepSeek or NVIDIA): only market data and the tickers you ask for are sent for an analysis; your e-mail and portfolio are not sent.</li>
      <li><b>Telegram</b>: only if you linked it, the messages sent to you.</li>
    </ul>
  )],
  ["For how long?", () => <>As long as your account is open. When you delete your account, your portfolio, analyses, request records and your sign-in account at Clerk are deleted.</>],
  ["Your rights", () => <>To see and download your data (Account → Download my data), to correct it (My Portfolio), to delete it (Account → Delete my account), and to remove the Telegram link and the API key at any time. For other requests under the Turkish data protection law (KVKK), write to the contact address above.</>],
  ["Important", () => <>Kapanış gives no investment advice, does not trade and does not ask you for a broker or exchange password.</>],
];

export default function Gizlilik() {
  const { t, lang } = useLang();
  const [contact, setContact] = useState("");
  useEffect(() => {
    fetch(`${API}/auth/config`).then((r) => r.json()).then((c) => setContact(c.iletisim || "")).catch(() => {});
  }, []);
  return (
    <section className="mx-auto max-w-3xl px-5 py-14">
      <h1 className="text-3xl font-extrabold tracking-tight text-t-1 sm:text-4xl">{t("Gizlilik ve KVKK aydınlatma metni")}</h1>
      <p className="mt-3 text-t-2">{t("Kapanış hangi veriyi neden tutar, kimlerle paylaşır ve haklarını nasıl kullanırsın.")}</p>
      <div className="mt-10 space-y-8">
        {(lang === "en" ? SECTIONS_EN : SECTIONS).map(([title, body]) => (
          <div key={title}>
            <h2 className="text-lg font-bold text-t-1">{title}</h2>
            <div className="mt-2 text-[0.9375rem] leading-relaxed text-t-2">{body(contact)}</div>
          </div>
        ))}
      </div>
      <p className="mt-10 text-xs text-t-3">{t("Son güncelleme: 27 Eylül 2026")}</p>
    </section>
  );
}
