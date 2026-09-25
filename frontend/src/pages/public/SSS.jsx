import { PublicHero } from "@/pages/public/Ozellikler";
import {
  Accordion, AccordionContent, AccordionItem, AccordionTrigger,
} from "@/components/ui/accordion";

const FAQ = [
  { q: "Kapanış ne demek, neden dokunuş yetmez?", a: "Bir seviyeye dokunmak (fitil) çoğu zaman sahte kırılımdır. Kapanış, ilgili mumun o seviyenin üstünde/altında kapanmasıdır ve teyit sağlar. Sistem yalnızca kapanışı sinyal sayar." },
  { q: "Bot benim yerime işlem açıyor mu?", a: "Hayır. Bot analiz eder ve KARAR mesajı üretir; Aldım/Pas kararını sen verirsin. Panelde yaptığın işlemler bota iletilir ve 'bota iletildi' rozetiyle beklemede görünür." },
  { q: "Goalpost kuralı nedir?", a: "Açık pozisyonda stop yalnızca lehe (kâr yönüne) çekilebilir. Riski artıracak şekilde geri çekilemez. Panelde stop'u aşağı çekmeye çalışırsan buton pasifleşir ve backend isteği reddeder." },
  { q: "R/R eşiği nasıl çalışır?", a: "Alarm ve karar formunda R/R canlı hesaplanır; 2.0 altı kırmızı, 1.5–2.0 sarı, 2.0 ve üzeri yeşil renklenir. 2.0 altındaki kurulumlar otomatik pas geçilir." },
  { q: "'Klasik DXY değil' etiketi ne anlama geliyor?", a: "Makro sayfasındaki alt dolar endeksi standart DXY değildir; likidite ağırlıklı, farklı bir hesaplama kullanır. Bu yüzden ayrıca etiketlenir." },
  { q: "Bayat veri rozeti neyi gösterir?", a: "Veri kaynağı güncel değilse ilgili ekranda 'bayat veri' rozeti çıkar. Bayat veriyle yeni karar üretilmez." },
  { q: "Bu bir yatırım tavsiyesi mi?", a: "Hayır. Kapanış bir karar çerçevesi ve analiz aracıdır; yatırım tavsiyesi vermez. Tüm kararların sorumluluğu kullanıcıya aittir." },
  { q: "Getiri garantisi var mı?", a: "Hayır. 'Kesin kazanç' veya garanti getiri gibi ifadeler kullanılmaz. Kripto varlıklar yüksek risklidir ve kayıp mümkündür." },
];

export default function SSS() {
  return (
    <div>
      <PublicHero
        eyebrow="SSS"
        title="Sık sorulan sorular"
        subtitle="Kapanış'ın nasıl çalıştığına dair en çok merak edilenler."
      />
      <section className="mx-auto max-w-3xl px-5 py-16">
        <Accordion type="single" collapsible className="w-full" data-testid="faq-accordion">
          {FAQ.map((item, i) => (
            <AccordionItem key={i} value={`item-${i}`} className="border-hairline">
              <AccordionTrigger className="text-left text-sm font-medium text-t-1 hover:no-underline" data-testid={`faq-q-${i}`}>
                {item.q}
              </AccordionTrigger>
              <AccordionContent className="text-sm leading-relaxed text-t-2">
                {item.a}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </section>
    </div>
  );
}
