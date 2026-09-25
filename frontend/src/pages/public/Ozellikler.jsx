import { motion } from "framer-motion";
import {
  Bell, Activity, Wallet, Globe2, Receipt, LineChart, FlaskConical, ShieldCheck, Gauge, Layers,
} from "lucide-react";

const FEATURES = [
  { icon: Activity, title: "Sinyaller & 4 panelli analiz", text: "Her kurulum trend, momentum, yapı ve hacim panelleriyle ayrı ayrı puanlanır; bot kararı gerekçesiyle görünür." },
  { icon: Bell, title: "Alarmlar + canlı R/R", text: "Alarm kurarken R/R oranı anında hesaplanır ve eşiklere göre kırmızı/sarı/yeşil renklenir." },
  { icon: Wallet, title: "Pozisyonlar & goalpost", text: "Açık pozisyonda stop yalnızca lehe çekilir; riske doğru çekilmeye çalışılırsa buton pasifleşir." },
  { icon: Globe2, title: "Makro rejim skalası", text: "-5…+5 rejim skalası, bayat veri rozeti ve 'klasik DXY değil' etiketiyle alt dolar endeksi." },
  { icon: Receipt, title: "Maliyet & tarife şeridi", text: "24 saatlik tarife şeridi ve saat bazında bot çalıştırma maliyeti." },
  { icon: LineChart, title: "Vadeli veriler", text: "Funding, açık pozisyon, long/short oranı ve COT yüzdeliği tek bakışta." },
  { icon: FlaskConical, title: "Backtest", text: "Strateji metrikleri: kazanma oranı, profit factor, beklenti (R) ve maksimum düşüş." },
  { icon: ShieldCheck, title: "Kurala bağlı karar", text: "İstisnasız kurallar; kapanış teyidi olmadan sinyal geçerli sayılmaz." },
];

const fade = { hidden: { opacity: 0, y: 14 }, show: (i = 0) => ({ opacity: 1, y: 0, transition: { duration: 0.4, delay: i * 0.05 } }) };

export function PublicHero({ eyebrow, title, subtitle }) {
  return (
    <section className="border-b border-hairline">
      <div className="mx-auto max-w-6xl px-5 py-14 md:py-20">
        {eyebrow && <div className="mb-3 text-xs font-semibold uppercase tracking-widest text-t-3">{eyebrow}</div>}
        <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">{title}</h1>
        {subtitle && <p className="mt-4 max-w-xl text-base text-t-2">{subtitle}</p>}
      </div>
    </section>
  );
}

export default function Ozellikler() {
  return (
    <div>
      <PublicHero
        eyebrow="Özellikler"
        title="Karar için gereken her şey, tek panelde"
        subtitle="Gürültüyü değil, kapanışla teyit edilmiş kurulumları görürsün. Analizden maliyete kadar tüm akış şeffaf."
      />
      <section className="mx-auto max-w-6xl px-5 py-16">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => {
            const Icon = f.icon;
            return (
              <motion.div
                key={f.title}
                variants={fade}
                initial="hidden"
                whileInView="show"
                viewport={{ once: true, margin: "-40px" }}
                custom={i}
                className="rounded-xl border border-hairline bg-surface p-5"
                data-testid={`feature-card-${i}`}
              >
                <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg border border-hairline bg-black text-t-1">
                  <Icon className="h-4 w-4" />
                </div>
                <h3 className="text-sm font-semibold text-t-1">{f.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-t-2">{f.text}</p>
              </motion.div>
            );
          })}
        </div>

        <div className="mt-12 grid gap-4 sm:grid-cols-3">
          {[
            { icon: Gauge, k: "Kapanış teyidi", v: "Fitil değil, mum." },
            { icon: Layers, k: "4 panel", v: "Her sinyalde ayrı puan." },
            { icon: ShieldCheck, k: "0 getiri vaadi", v: "Sadece kural ve şeffaflık." },
          ].map((s) => {
            const Icon = s.icon;
            return (
              <div key={s.k} className="flex items-center gap-3 rounded-xl border border-hairline bg-surface p-4">
                <Icon className="h-5 w-5 text-t-2" />
                <div>
                  <div className="text-sm font-semibold text-t-1">{s.k}</div>
                  <div className="text-xs text-t-2">{s.v}</div>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
