import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { LogoMark } from "@/components/Logo";
import { formatPrice } from "@/lib/format";
import { RRPill } from "@/components/bits";
import {
  ArrowRight, Check, X, ShieldCheck, Layers, Clock3, Ban, Radar, GitCommitVertical,
} from "lucide-react";

const fade = {
  hidden: { opacity: 0, y: 14 },
  show: (i = 0) => ({ opacity: 1, y: 0, transition: { duration: 0.4, delay: i * 0.08, ease: "easeOut" } }),
};

function MiniChart() {
  const pts = [40, 42, 38, 45, 44, 50, 48, 56, 60, 58, 66, 72];
  const max = Math.max(...pts), min = Math.min(...pts);
  const path = pts
    .map((p, i) => {
      const x = (i / (pts.length - 1)) * 240;
      const y = 96 - ((p - min) / (max - min)) * 80 - 6;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox="0 0 240 96" className="w-full" preserveAspectRatio="none" height="96">
      <line x1="0" y1="30" x2="240" y2="30" stroke="#F5C518" strokeDasharray="3 3" strokeWidth="0.8" opacity="0.7" />
      <line x1="0" y1="60" x2="240" y2="60" stroke="#2196F3" strokeDasharray="3 3" strokeWidth="0.8" opacity="0.7" />
      <path d={path} fill="none" stroke="#26A69A" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function TelegramMockup() {
  return (
    <div className="w-full max-w-sm rounded-2xl border border-hairline bg-surface shadow-2xl" data-testid="telegram-mockup">
      {/* başlık */}
      <div className="flex items-center gap-3 border-b border-hairline px-4 py-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-black text-t-1 border border-hairline">
          <LogoMark size={18} />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-t-1">Kapanış Bot</div>
          <div className="text-xs text-up">çevrimiçi</div>
        </div>
      </div>

      <div className="space-y-3 p-4">
        {/* 1) grafik mesajı */}
        <motion.div variants={fade} initial="hidden" animate="show" custom={0} className="max-w-[85%] rounded-2xl rounded-tl-sm border border-hairline bg-black p-3">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-semibold text-t-1">BTC/USDT · 4H</span>
            <span className="num text-t-2">{formatPrice(84350)}</span>
          </div>
          <MiniChart />
          <div className="mt-2 flex items-center gap-3 text-[10px] text-t-2">
            <span className="inline-flex items-center gap-1"><span className="inline-block h-[2px] w-3 bg-sma20" />SMA20</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-[2px] w-3 bg-sma50" />SMA50</span>
          </div>
          <div className="mt-1 text-right text-[10px] text-t-3">14:22</div>
        </motion.div>

        {/* 2) KARAR mesajı */}
        <motion.div variants={fade} initial="hidden" animate="show" custom={1} className="max-w-[85%] rounded-2xl rounded-tl-sm border border-hairline bg-black p-3">
          <div className="mb-2 inline-flex items-center rounded bg-t-1 px-2 py-0.5 text-[11px] font-bold tracking-wide text-black">
            KARAR
          </div>
          <div className="space-y-1 text-sm text-t-1">
            <div>84 350 direnci <span className="text-up">kapanışla</span> kırıldı.</div>
            <div className="num text-xs text-t-2">Giriş {formatPrice(84350)} · Stop {formatPrice(82900)} · Hedef {formatPrice(88200)}</div>
          </div>
          <div className="mt-2"><RRPill rr={2.66} /></div>
          <div className="mt-1 text-right text-[10px] text-t-3">14:23</div>
        </motion.div>

        {/* 3) Aldım / Pas butonları */}
        <motion.div variants={fade} initial="hidden" animate="show" custom={2} className="flex gap-2">
          <button className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-up/15 py-2.5 text-sm font-semibold text-up transition-colors duration-150 hover:bg-up/25" data-testid="mockup-aldim">
            <Check className="h-4 w-4" /> Aldım
          </button>
          <button className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-down/15 py-2.5 text-sm font-semibold text-down transition-colors duration-150 hover:bg-down/25" data-testid="mockup-pas">
            <X className="h-4 w-4" /> Pas
          </button>
        </motion.div>
      </div>
    </div>
  );
}

const JOURNEY = [
  { icon: Radar, title: "Tarama", text: "Bot piyasayı kural setine göre tarar; gürültüyü eler." },
  { icon: Layers, title: "4 panelli analiz", text: "Trend, momentum, yapı ve hacim ayrı ayrı puanlanır." },
  { icon: Clock3, title: "Kapanış teyidi", text: "Fitil değil, mum kapanışı beklenir. Dokunma sayılmaz." },
  { icon: GitCommitVertical, title: "KARAR mesajı", text: "Giriş, stop, hedef ve R/R ile net bir karar üretilir." },
  { icon: ShieldCheck, title: "Sen onaylarsın", text: "Aldım/Pas senin kararın. Kural motoru sadece yol gösterir." },
];

const RULES = [
  { title: "Kapanışla teyit", text: "Seviyeye dokunmak yetmez; kapanış olmadan sinyal geçerli değildir." },
  { title: "Goalpost kuralı", text: "Açık pozisyonda stop yalnızca lehe çekilir; riske doğru geri çekilemez." },
  { title: "R/R eşiği", text: "R/R 2.0 altındaki kurulumlar otomatik pas geçilir." },
  { title: "Bayat veriyle karar yok", text: "Veri tazeliği rozetle işaretlenir; bayatsa karar üretilmez." },
];

export default function Home() {
  return (
    <div>
      {/* HERO */}
      <section className="border-b border-hairline">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-5 py-16 md:py-24 lg:grid-cols-2">
          <motion.div variants={fade} initial="hidden" animate="show">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-hairline bg-surface px-3 py-1 text-xs text-t-2">
              <span className="h-1.5 w-1.5 rounded-full bg-up" /> Kurala bağlı karar akışı
            </div>
            <h1 className="text-4xl font-extrabold leading-[1.05] tracking-tight sm:text-5xl lg:text-6xl">
              Dokunma değil,<br /><span className="text-t-1">kapanış.</span>
            </h1>
            <p className="mt-5 max-w-md text-base text-t-2">
              Seviyeye değmek bir şey ifade etmez. Kapanışla teyit edilen, kurallara bağlı ve şeffaf bir karar akışı.
              Bot analiz eder, kararı sen verirsin.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Button asChild size="lg" data-testid="hero-cta-panel">
                <Link to="/giris">Panele gir <ArrowRight className="h-4 w-4" /></Link>
              </Button>
              <Button asChild size="lg" variant="outline" className="border-hairline text-t-1 hover:bg-secondary" data-testid="hero-cta-how">
                <Link to="/nasil-calisir">Nasıl çalışır</Link>
              </Button>
            </div>
            <p className="mt-6 inline-flex items-center gap-2 text-xs text-t-3">
              <Ban className="h-3.5 w-3.5" /> Getiri vaadi yok. Kaldıraç teşviki yok. Yatırım tavsiyesi değildir.
            </p>
          </motion.div>

          <motion.div variants={fade} initial="hidden" animate="show" custom={1} className="flex justify-center lg:justify-end">
            <TelegramMockup />
          </motion.div>
        </div>
      </section>

      {/* Bir sinyalin yolculuğu */}
      <section className="border-b border-hairline">
        <div className="mx-auto max-w-6xl px-5 py-16">
          <h2 className="text-lg font-bold md:text-xl">Bir sinyalin yolculuğu</h2>
          <p className="mt-1 max-w-lg text-sm text-t-2">Bir kurulumun taramadan senin kararına kadar geçtiği beş adım.</p>

          <div className="mt-10 grid gap-4 md:grid-cols-5">
            {JOURNEY.map((s, i) => {
              const Icon = s.icon;
              return (
                <motion.div
                  key={s.title}
                  variants={fade}
                  initial="hidden"
                  whileInView="show"
                  viewport={{ once: true, margin: "-40px" }}
                  custom={i}
                  className="relative rounded-xl border border-hairline bg-surface p-4"
                  data-testid={`journey-step-${i}`}
                >
                  <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg border border-hairline bg-black text-t-1">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="text-xs font-semibold text-t-3">{String(i + 1).padStart(2, "0")}</div>
                  <div className="mt-0.5 text-sm font-semibold text-t-1">{s.title}</div>
                  <p className="mt-1 text-xs leading-relaxed text-t-2">{s.text}</p>
                </motion.div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Kural kartları */}
      <section>
        <div className="mx-auto max-w-6xl px-5 py-16">
          <h2 className="text-lg font-bold md:text-xl">Kurallar, tercih değil</h2>
          <p className="mt-1 max-w-lg text-sm text-t-2">Karar motoru bu ilkeler etrafında çalışır; istisna yapmaz.</p>

          <div className="mt-10 grid gap-4 sm:grid-cols-2">
            {RULES.map((r, i) => (
              <motion.div
                key={r.title}
                variants={fade}
                initial="hidden"
                whileInView="show"
                viewport={{ once: true, margin: "-40px" }}
                custom={i}
                className="rounded-xl border border-hairline bg-surface p-5"
                data-testid={`rule-card-${i}`}
              >
                <div className="flex items-center gap-2">
                  <Check className="h-4 w-4 text-up" />
                  <h3 className="text-sm font-semibold text-t-1">{r.title}</h3>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-t-2">{r.text}</p>
              </motion.div>
            ))}
          </div>

          <div className="mt-10 flex flex-wrap items-center gap-3">
            <Button asChild variant="outline" className="border-hairline text-t-1 hover:bg-secondary">
              <Link to="/kurallar">Tüm kuralları oku <ArrowRight className="h-4 w-4" /></Link>
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}
