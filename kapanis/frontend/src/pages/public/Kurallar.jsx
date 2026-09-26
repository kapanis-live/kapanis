import { PublicHero } from "@/pages/public/Ozellikler";
import { Check, Ban } from "lucide-react";

const ALLOW = [
  { title: "Kapanışla teyit", text: "Bir seviye ancak ilgili mum o seviyenin üstünde/altında kapanırsa geçerli sayılır. Fitil, dokunuş ya da anlık delme sinyal değildir." },
  { title: "Goalpost kuralı", text: "Açık pozisyonda stop yalnızca kâr yönüne (lehe) çekilebilir. Zarar riskini artıracak şekilde geri çekilemez; sistem buna izin vermez." },
  { title: "R/R eşiği", text: "Risk/ödül oranı 2.0'ın altındaki kurulumlar otomatik pas geçilir. Eşik altı kurulumlar KARAR mesajına dönüşmez." },
  { title: "Bayat veriyle karar yok", text: "Veri tazeliği her ekranda rozetle işaretlenir. Veri bayatsa (stale) karar üretilmez, mevcut karar 'güncellenmeli' olarak işaretlenir." },
  { title: "Tek risk birimi", text: "Her işlemde risk, hesabın önceden belirlenmiş sabit yüzdesini geçemez. Pozisyon boyutu bu kurala göre hesaplanır." },
  { title: "Şeffaf gerekçe", text: "Her KARAR mesajı; giriş, stop, hedef, R/R ve panellerin gerekçesini içerir. Kara kutu yoktur." },
];

const FORBID = [
  "'Kesin kazanç', 'garanti getiri' gibi ifadeler kullanılmaz.",
  "Kaldıraç teşvik edilmez; 'kaldıraç butonu' yoktur.",
  "Getiri vaadi verilmez; geçmiş performans gelecek için gösterge sayılmaz.",
  "Duyguyla, teyitsiz veya bayat veriyle işlem açılmaz.",
];

export default function Kurallar() {
  return (
    <div>
      <PublicHero
        eyebrow="Kurallar"
        title="Kurallar tercih değil, çerçevedir"
        subtitle="Karar motoru bu ilkeler etrafında çalışır ve istisna yapmaz. Şeffaflık için hepsi burada."
      />
      <section className="mx-auto max-w-4xl px-5 py-16">
        <div className="grid gap-4 sm:grid-cols-2">
          {ALLOW.map((r, i) => (
            <div key={r.title} className="rounded-xl border border-hairline bg-surface p-5" data-testid={`kural-allow-${i}`}>
              <div className="flex items-center gap-2">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-up/15">
                  <Check className="h-3.5 w-3.5 text-up" />
                </div>
                <h3 className="text-sm font-semibold text-t-1">{r.title}</h3>
              </div>
              <p className="mt-2 text-sm leading-relaxed text-t-2">{r.text}</p>
            </div>
          ))}
        </div>

        <div className="mt-12 rounded-xl border border-down/30 bg-down/5 p-6">
          <h2 className="flex items-center gap-2 text-base font-semibold text-t-1">
            <Ban className="h-4 w-4 text-down" /> Yapılmayanlar
          </h2>
          <ul className="mt-4 space-y-2">
            {FORBID.map((f, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-t-2" data-testid={`kural-forbid-${i}`}>
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-down" />
                {f}
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
