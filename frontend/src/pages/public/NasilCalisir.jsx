import { PublicHero } from "@/pages/public/Ozellikler";
import { motion } from "framer-motion";
import { Radar, Layers, Clock3, GitCommitVertical, ShieldCheck, RefreshCw } from "lucide-react";

const STEPS = [
  { icon: Radar, title: "1 · Tarama", text: "Bot, tanımlı kural setine göre piyasayı sürekli tarar. Kriterleri karşılamayan her şey elenir; amaç gürültüyü değil kurulumu yakalamak." },
  { icon: Layers, title: "2 · 4 panelli analiz", text: "Aday kurulum dört ayrı pencerede puanlanır: trend (1D), momentum (4H), yapı (1H) ve hacim. Panellerin uyumu kararın gücünü belirler." },
  { icon: Clock3, title: "3 · Kapanış teyidi", text: "Seviyeye dokunmak sinyal değildir. İlgili mumun kapanışı beklenir; fitille tetiklenen sahte kırılımlar ayıklanır." },
  { icon: GitCommitVertical, title: "4 · KARAR mesajı", text: "Teyit gelirse bot; giriş, stop, hedef ve R/R içeren net bir KARAR üretir. R/R eşiğin altındaysa kurulum otomatik pas geçilir." },
  { icon: ShieldCheck, title: "5 · Senin onayın", text: "Panelde ve Telegram'da Aldım/Pas seçersin. Karar senindir; bot yalnızca kurala bağlı çerçeveyi sunar." },
  { icon: RefreshCw, title: "6 · Takip & goalpost", text: "Pozisyon açılınca stop yalnızca lehe çekilebilir. Riske doğru geri çekme denemesi kural motoru tarafından engellenir." },
];

const fade = { hidden: { opacity: 0, x: -12 }, show: (i = 0) => ({ opacity: 1, x: 0, transition: { duration: 0.4, delay: i * 0.06 } }) };

export default function NasilCalisir() {
  return (
    <div>
      <PublicHero
        eyebrow="Nasıl çalışır"
        title="Taramadan karara, altı adım"
        subtitle="Her sinyal aynı yoldan geçer. Süreç şeffaftır; hiçbir adım atlanmaz."
      />
      <section className="mx-auto max-w-3xl px-5 py-16">
        <div className="relative border-l border-hairline pl-8">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            return (
              <motion.div
                key={s.title}
                variants={fade}
                initial="hidden"
                whileInView="show"
                viewport={{ once: true, margin: "-40px" }}
                custom={i}
                className="relative pb-10 last:pb-0"
                data-testid={`how-step-${i}`}
              >
                <div className="absolute -left-[41px] flex h-6 w-6 items-center justify-center rounded-full border border-hairline bg-ink text-t-1">
                  <Icon className="h-3 w-3" />
                </div>
                <h3 className="text-base font-semibold text-t-1">{s.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-t-2">{s.text}</p>
              </motion.div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
