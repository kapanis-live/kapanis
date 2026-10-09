import { useMemo, useState } from "react";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { useData } from "@/lib/useData";
import api, { formatApiErrorDetail } from "@/lib/api";
import { baseCode } from "@/lib/portfolio";
import { translate, currentLang } from "@/lib/i18n";
import { useLang } from "@/lib/i18n";

const tx = (s, v) => translate(currentLang(), s, v);

// Kripto Danışman: Telegram'daki /danis ve /firsat tara ile aynı kod (danisman.py). Emir göndermez.
const plain = (t) => String(t || "").replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, "").trim();

function Result({ text }) {
  return (
    <pre className="mt-4 whitespace-pre-wrap text-[0.9375rem] leading-relaxed text-t-2" style={{ fontFamily: "inherit" }}>
      {plain(text)}
    </pre>
  );
}

async function ask(fn, setBusy, setText) {
  setBusy(true);
  try {
    const r = await fn();
    setText(r.data.text);
  } catch (e) {
    toast.error(formatApiErrorDetail(e.response?.data?.detail) || tx("Danışman cevap vermedi."));
  } finally {
    setBusy(false);
  }
}

export default function Advisor() {
  const { t } = useLang();
  const extras = useData("extras", "/extras");
  // Eldeki kriptolar: taramada "portföyde" işaretlenir, tek coin raporunda TUT/KORU/AZALT için kullanılır
  const held = useMemo(() => (extras.data?.portfoy || []).filter((g) => g.piyasa === "KRIPTO")
    .map((g) => ({ code: baseCode(g.ad), value: g.deger, average: g.adet ? g.maliyet / g.adet : null })), [extras.data]);
  const [portfolio, setPortfolio] = useState("");
  const [code, setCode] = useState("");
  const [scan, setScan] = useState("");
  const [report, setReport] = useState("");
  const [scanning, setScanning] = useState(false);
  const [asking, setAsking] = useState(false);

  const size = () => {
    if (!portfolio.trim()) return undefined;
    const v = U.parseTr(portfolio);
    if (!(v > 0)) {
      toast.error(t("Portföy tutarı pozitif bir sayı olmalı (USDT)."));
      return null;
    }
    return v;
  };
  const runScan = () => {
    const portfolio_usdt = size();
    if (portfolio_usdt === null) return;
    ask(() => api.get("/advisor/opportunities", { params: { portfolio_usdt, holdings: held.map((h) => h.code).slice(0, 8).join(",") } }),
      setScanning, setScan);
  };
  const runReport = () => {
    const symbol = code.trim().toUpperCase().replace("/", "").replace(/USDT$/, "");
    const portfolio_usdt = size();
    if (!symbol || portfolio_usdt === null) {
      if (!symbol) toast.error(t("Coin kodunu yaz (ör. BTC, HYPE)."));
      return;
    }
    const mine = held.find((h) => h.code === symbol);
    ask(() => (mine?.average
      ? api.post("/advisor/analyze", { symbol, portfolio_usdt, position_usdt: mine.value, average_price: mine.average,
        holdings: held.map((h) => h.code).slice(0, 8) })
      : api.get(`/advisor/${encodeURIComponent(symbol)}`, { params: { portfolio_usdt } })), setAsking, setReport);
  };

  return (
    <div className="kp-page">
      <K.PageHeader controls={false} title={t("Kripto Danışman")}
        subtitle={t("USDT pariteleri, kapanmış 15m/1h/4h/1d mumlarla: trend, destek/direnç, kırılım, stop ve pozisyon tutarı. Emir göndermez.")} />
      <K.Card title={t("Portföy büyüklüğü")}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <K.Field label={t("Kripto portföyün (USDT)")} hint={t("boş bırakırsan pozisyon tutarı hesaplanmaz")}>
            <K.TextInput prefix="$" inputMode="decimal" value={portfolio} placeholder="287" onChange={(e) => setPortfolio(e.target.value)} />
          </K.Field>
        </div>
        <p className="kp-note">
          {held.length ? t("Portföyündeki kriptolar: {k}. Taramada işaretlenir; tek coin raporunda elindeki için TUT/KORU/AZALT denir.", { k: held.map((h) => h.code).join(", ") })
            : t("Portföyünde kripto yok: raporlar yeni giriş gözüyle yazılır.")}
        </p>
      </K.Card>
      <K.Card title={t("Fırsat taraması")} actions={<K.Button variant="primary" disabled={scanning} onClick={runScan}>{scanning ? t("Taranıyor…") : t("Şimdi tara")}</K.Button>}>
        {scanning && <p className="kp-note">{t("En çok işlem gören pariteler aynı analizden geçiyor; bir dakikaya yakın sürebilir.")}</p>}
        {scan ? <Result text={scan} /> : !scanning && <p className="kp-note">{t("Borsadaki en çok işlem gören USDT pariteleri taranır, en fazla 10 kurulum sıralanır. Telegram'da: /firsat tara.")}</p>}
      </K.Card>
      <K.Card title={t("Tek coin raporu")}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <K.Field label="Coin"><K.TextInput value={code} placeholder="BTC, SOL, HYPE" onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runReport()} /></K.Field>
          <div className="flex items-end"><K.Button variant="primary" disabled={asking} onClick={runReport}>{asking ? t("Hesaplanıyor…") : t("Danış")}</K.Button></div>
        </div>
        {report && <Result text={report} />}
      </K.Card>
      <p className="kp-note">
        {t("Karar desteğidir, yatırım tavsiyesi değildir. Danışmanın gün içi kuralları geçmiş veride sınanmış bir üstünlük göstermedi; seviyeler ve risk hesabı içindir, “al” garantisi değildir. Her rapor araştırma kaydına yazılır.")}
      </p>
    </div>
  );
}
