import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { useData } from "@/lib/useData";
import { DataView } from "@/components/DataView";
import { EmptyState } from "@/components/states";
import { chartHref } from "@/components/AssetLogo";
import api, { formatApiErrorDetail } from "@/lib/api";
import { curOf, logo, MARKET_UI, relDay, splitAi, priceFmt } from "@/lib/dsmap";

const code = (s) => String(s || "").split("/")[0].replace(/\.(IS|US)$/i, "");
const num = (id) => String(id || "").replace(/^(sig|dec)_/, "");
const DECISION = (v) => {
  const s = String(v || "").toUpperCase();
  if (s.includes("AL")) return "AL";
  if (s.includes("BEKLE")) return "BEKLE";
  if (s.includes("TUT")) return "TUT";
  return "PAS";
};

// Botun kapı kuralları: yeni kayıtlar {kural, durum, detay}, eskiler "✅ Kural: detay" metni
function gateItems(gate) {
  const rules = gate?.kurallar || [];
  return rules.map((r) => {
    if (typeof r === "string") {
      const status = r.startsWith("✅") ? "gecti" : r.startsWith("❌") ? "kaldi" : "uyari";
      const body = r.replace(/^\S+\s*/, "");
      const [rule, ...rest] = body.split(":");
      return { status, rule: rule.trim(), detail: rest.join(":").trim() };
    }
    return { status: r.durum || "uyari", rule: r.kural, detail: r.detay, blocking: r.durum === "uyari" ? false : undefined };
  });
}

const OUTCOME = { hedef: ["Hedefe gitti", "up"], stop: ["İptal seviyesine gitti", "down"], "açık": ["Henüz sonuçlanmadı"], "veri yok": ["Veri yok"] };

export default function Signals() {
  const navigate = useNavigate();
  const sq = useData("signals", "/signals");
  const dq = useData("decisions", "/decisions");
  const [sel, setSel] = useState(null);
  const [filter, setFilter] = useState("Tümü");
  const [done, setDone] = useState({});

  const items = useMemo(() => {
    const decs = Object.fromEntries((dq.data || []).map((d) => [num(d.id), d]));
    return (sq.data || []).map((s) => {
      const d = decs[num(s.id)];
      const a = s.analysis || {};
      const gate = gateItems(a.gate);
      const passed = gate.filter((g) => g.status === "gecti").length;
      const verdict = d?.verdict || a.user_action;
      const state = done[num(s.id)] || (d?.status === "pending" ? "bekliyor" : verdict === "Aldım" ? "aldim" : verdict === "Pas" ? "pas"
        : a.gate && (a.gate.ok === false || a.gate.gecti === false) ? "kapi" : d ? "doldu" : "izleniyor");
      return {
        id: s.id, symbol: code(s.symbol), name: MARKET_UI[s.market]?.label || s.market, logo: logo(code(s.symbol), s.market),
        decision: DECISION(a.bot_decision?.verdict), time: relDay(s.created_at), score: gate.length ? `${passed}/${gate.length}` : "—",
        state, raw: s, dec: d, gate, cur: curOf(s.currency),
      };
    });
  }, [sq.data, dq.data, done]);

  useEffect(() => {
    if (!sel && items.length) setSel((items.find((i) => i.state === "bekliyor") || items[0]).id);
  }, [items, sel]);

  const pendingCount = items.filter((i) => i.state === "bekliyor").length;
  const shown = items.filter((i) => filter === "Tümü" || (filter === "Bekleyen" ? i.state === "bekliyor" : filter === "Aldım" ? i.state === "aldim" : i.state === "pas"));
  const cur = items.find((i) => i.id === sel);

  const act = async (item, verdict) => {
    if (verdict === "Aldım" && item.decision !== "AL" && !window.confirm(`Bot bu sinyalde ${item.decision} dedi. Gerçekten aldın mı?`)) return;
    setDone((s) => ({ ...s, [num(item.id)]: verdict === "Aldım" ? "aldim" : "pas" }));
    try {
      await api.post(`/decisions/${item.dec.id}/action`, { verdict });
      toast.success(`"${verdict}" kaydı bota iletildi.`);
    } catch (err) {
      setDone((s) => { const n = { ...s }; delete n[num(item.id)]; return n; });
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || "Kaydedilemedi.");
    }
  };

  return (
    <DataView query={sq} loadingText="Sinyaller yükleniyor...">
      {() => (
        <div className="kp-page">
          <K.PageHeader controls={false} title="Sinyaller"
            subtitle={`${pendingCount ? `${pendingCount} karar bekliyor` : "Bekleyen karar yok"} · son ${items.length} sinyal`} />
          <p className="kp-note" style={{ margin: "0 0 1rem" }}>
            Sinyaller 30 dakikada bir destek/direnç taramasından gelir (kripto, BIST, ABD): kod her kurulumu AL ya da PAS diye
            işaretler, nedenleri kartta yazar. Bu seviye kuralları geçmiş veri testinde kazandırmadı; sonuçları burada canlı
            tutulur. Test edilen kurallar Stratejiler sayfasında. Karar senin; bot işlem yapmaz.
          </p>
          {!items.length ? <EmptyState text="Henüz sinyal yok. Alarmlar kapanışla tetiklenince burada görünür." /> : (
            <>
              <K.Segmented ariaLabel="Sinyal filtresi" value={filter} onChange={setFilter}
                options={[{ value: "Tümü", label: "Tümü" }, { value: "Bekleyen", label: `Bekleyen (${pendingCount})` }, { value: "Aldım", label: "Aldım" }, { value: "Pas", label: "Pas" }]} />
              <div className="kp-grid kp-split-l">
                {shown.length ? <K.SignalList items={shown} value={sel} onSelect={setSel} /> : <p className="kp-note">Bu filtrede sinyal yok.</p>}
                {cur && <Detail item={cur} onAct={act} onChart={() => navigate(chartHref(cur.symbol, cur.raw.market))} />}
              </div>
            </>
          )}
        </div>
      )}
    </DataView>
  );
}

function Detail({ item, onAct, onChart }) {
  const s = item.raw;
  const a = s.analysis || {};
  const d = item.dec || {};
  const out = a.outcome;
  const ai = splitAi(a.text);
  const levels = [
    ["Giriş (sinyal kapanışı)", d.entry], ["İptal seviyesi", d.stop], ["Hedef", d.target],
  ];
  const oc = out ? OUTCOME[out.sonuc] || [out.sonuc] : null;
  return (
    <div className="kp-col">
      <K.Card>
        <div className="kp-sighead">
          <div className="kp-sighead__id">
            <K.Ticker symbol={item.symbol} name={item.name} logo={item.logo} size="lg" />
          </div>
          <K.DecisionBadge decision={item.decision} size="lg" />
        </div>
        <p className="kp-note" style={{ margin: "0.75rem 0 1.25rem" }}>{item.time} · {s.timeframe} mum kapanışı · {s.type}</p>
        <div className="kp-levels">
          {levels.map(([label, v]) => (
            <div key={label} className="kp-tile"><span className="kp-tile__label">{label}</span><span className="kp-tile__val">{v == null ? "—" : priceFmt(v, item.cur)}</span></div>
          ))}
          <div className="kp-tile"><span className="kp-tile__label">R/R</span><span className="kp-tile__val">{d.rr == null ? "—" : U.fmtNum(d.rr, 2)}</span></div>
        </div>
      </K.Card>
      {item.state === "bekliyor" && (
        <K.Card>
          <div className="kp-actions">
            <span className="kp-actions__note">Karar senin. Kendi yaptığın işlemi kaydet; bot işlem yapmaz.</span>
            <K.Button variant="secondary" onClick={() => onAct(item, "Pas")}>Pas</K.Button>
            <K.Button variant="primary" onClick={() => onAct(item, "Aldım")}>Aldım</K.Button>
          </div>
        </K.Card>
      )}
      {item.gate.length > 0 && (
        <K.Card title="Kod kapısı" actions={<K.Button variant="ghost" onClick={onChart}>Grafiği aç</K.Button>}>
          <K.GateList items={item.gate} />
          <p className="kp-note">Her kural kodda kontrol edilir. Engelleyici bir kural kalırsa karar AL olamaz; eksik ya da eski veri “doğrulanamadı” sayılır ve kalır.</p>
        </K.Card>
      )}
      {out && (
        <K.OutcomeBox rows={[
          { label: "Sonuç", value: oc[0], tone: oc[1] },
          ...(out.cikis != null ? [{ label: "Çıkış (kapanış)", value: priceFmt(out.cikis, item.cur) }] : []),
          ...(out.mum != null ? [{ label: "Süre", value: `${out.mum} mum` }] : []),
          ...(out.R != null ? [{ label: "Sonuç (R)", value: `${out.R >= 0 ? "+" : "−"}${U.fmtNum(Math.abs(out.R), 2)} R`, tone: out.R >= 0 ? "up" : "down" }] : []),
        ]} note="Kapanışlarla hesaplanır: iğne (fitil) sayılmaz." />
      )}
      {ai.body && (
        <K.AiNote model={ai.model || "Yapay zekâ"} time={item.time}>
          {ai.body.split(/\n{2,}/).map((p, i) => <p key={i} style={{ whiteSpace: "pre-wrap" }}>{p}</p>)}
        </K.AiNote>
      )}
    </div>
  );
}
