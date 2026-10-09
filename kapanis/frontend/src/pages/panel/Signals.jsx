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
import { useLang, translate, currentLang } from "@/lib/i18n";

const tx = (s, v) => translate(currentLang(), s, v);

const code = (s) => String(s || "").split("/")[0].replace(/\.(IS|US)$/i, "");
const num = (id) => String(id || "").replace(/^(sig|dec)_/, "");
const DECISION = (v) => {
  const s = String(v || "").toUpperCase();
  if (s.includes("BİLGİ") || s.includes("BILGI")) return "BİLGİ";   // seviye taraması: öneri değil
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

const OUTCOME = (k) => {
  if (k === "hedef") return [tx("Hedefe gitti"), "up"];
  if (k === "stop") return [tx("İptal seviyesine gitti"), "down"];
  if (k === "açık") return [tx("Henüz sonuçlanmadı")];
  if (k === "veri yok") return [tx("Veri yok")];
  return [k];
};

export default function Signals() {
  const { t } = useLang();
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
        : a.gate && (a.gate.ok === false || a.gate.gecti === false) ? "kapi" : DECISION(a.bot_decision?.verdict) === "BİLGİ" ? "bilgi" : d ? "doldu" : "izleniyor");
      return {
        id: s.id, symbol: code(s.symbol),         name: t(MARKET_UI[s.market]?.label || s.market), logo: logo(code(s.symbol), s.market),
        decision: DECISION(a.bot_decision?.verdict), time: relDay(s.created_at), score: gate.length ? `${passed}/${gate.length}` : "—",
        state, raw: s, dec: d, gate, cur: curOf(s.currency),
      };
    });
  }, [sq.data, dq.data, done, t]);

  useEffect(() => {
    if (!sel && items.length) setSel((items.find((i) => i.state === "bekliyor") || items[0]).id);
  }, [items, sel]);

  const pendingCount = items.filter((i) => i.state === "bekliyor").length;
  const shown = items.filter((i) => filter === "Tümü" || (filter === "Bekleyen" ? i.state === "bekliyor" : filter === "Aldım" ? i.state === "aldim" : i.state === "pas"));
  const cur = items.find((i) => i.id === sel);

  const act = async (item, verdict) => {
    if (verdict === "Aldım" && item.decision !== "AL" && !window.confirm(t("Bot bu sinyalde {d} dedi. Gerçekten aldın mı?", { d: t(item.decision) }))) return;
    setDone((s) => ({ ...s, [num(item.id)]: verdict === "Aldım" ? "aldim" : "pas" }));
    try {
      await api.post(`/decisions/${item.dec.id}/action`, { verdict });
      toast.success(t("\"{v}\" kaydı bota iletildi.", { v: t(verdict) }));
    } catch (err) {
      setDone((s) => { const n = { ...s }; delete n[num(item.id)]; return n; });
      toast.error(formatApiErrorDetail(err.response?.data?.detail) || t("Kaydedilemedi."));
    }
  };

  return (
    <DataView query={sq} loadingText={t("Sinyaller yükleniyor...")}>
      {() => (
        <div className="kp-page">
          <K.PageHeader controls={false} title={t("Sinyaller")}
            subtitle={`${pendingCount ? t("{n} karar bekliyor", { n: pendingCount }) : t("Bekleyen karar yok")} · ${t("son {n} sinyal", { n: items.length })}`} />
          <p className="kp-note" style={{ margin: "0 0 1rem" }}>
            {t("Liste 30 dakikada bir destek/direnç taramasından gelir (kripto, BIST, ABD). Bu kayıtlar ")}
            <b>{t("bilgi")}</b>
            {t("dir, AL önerisi değil: seviye kuralları geçmiş veri testinde kazandırmadı. Kod her kurulumun kurallarını tek tek kontrol eder ve sonucunu izler; bir kural testten geçerse o zaman AL etiketi alır. Test edilen kurallar Stratejiler sayfasında.")}
          </p>
          {!items.length ? <EmptyState text={t("Henüz sinyal yok. Alarmlar kapanışla tetiklenince burada görünür.")} /> : (
            <>
              <K.Segmented ariaLabel={t("Sinyal filtresi")} value={filter} onChange={setFilter}
                options={[{ value: "Tümü", label: t("Tümü") }, { value: "Bekleyen", label: t("Bekleyen ({n})", { n: pendingCount }) }, { value: "Aldım", label: t("Aldım") }, { value: "Pas", label: t("Pas") }]} />
              <div className="kp-grid kp-split-l">
                {shown.length ? <K.SignalList items={shown} value={sel} onSelect={setSel} /> : <p className="kp-note">{t("Bu filtrede sinyal yok.")}</p>}
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
  const { t } = useLang();
  const s = item.raw;
  const a = s.analysis || {};
  const d = item.dec || {};
  const out = a.outcome;
  const ai = splitAi(a.text);
  const levels = [
    [t("Giriş (sinyal kapanışı)"), d.entry], [t("İptal seviyesi"), d.stop], [t("Hedef"), d.target],
  ];
  const oc = out ? OUTCOME(out.sonuc) : null;
  return (
    <div className="kp-col">
      <K.Card>
        <div className="kp-sighead">
          <div className="kp-sighead__id">
            <K.Ticker symbol={item.symbol} name={item.name} logo={item.logo} size="lg" />
          </div>
          <K.DecisionBadge decision={item.decision} size="lg" />
        </div>
        <p className="kp-note" style={{ margin: "0.75rem 0 1.25rem" }}>{item.time} · {s.timeframe} {t("mum kapanışı")} · {s.type}</p>
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
            <span className="kp-actions__note">{t("Karar senin. Kendi yaptığın işlemi kaydet; bot işlem yapmaz.")}</span>
            <K.Button variant="secondary" onClick={() => onAct(item, "Pas")}>{t("Pas")}</K.Button>
            <K.Button variant="primary" onClick={() => onAct(item, "Aldım")}>{t("Aldım")}</K.Button>
          </div>
        </K.Card>
      )}
      {item.gate.length > 0 && (
        <K.Card title={t("Kod kapısı")} actions={<K.Button variant="ghost" onClick={onChart}>{t("Grafiği aç")}</K.Button>}>
          <K.GateList items={item.gate} />
          <p className="kp-note">{t("Her kural kodda kontrol edilir. Engelleyici bir kural kalırsa karar AL olamaz; eksik ya da eski veri “doğrulanamadı” sayılır ve kalır.")}</p>
        </K.Card>
      )}
      {out && (
        <K.OutcomeBox rows={[
          { label: t("Sonuç"), value: oc[0], tone: oc[1] },
          ...(out.cikis != null ? [{ label: t("Çıkış (kapanış)"), value: priceFmt(out.cikis, item.cur) }] : []),
          ...(out.mum != null ? [{ label: t("Süre"), value: `${out.mum} ${t("mum")}` }] : []),
          ...(out.R != null ? [{ label: t("Sonuç (R)"), value: `${out.R >= 0 ? "+" : "−"}${U.fmtNum(Math.abs(out.R), 2)} R`, tone: out.R >= 0 ? "up" : "down" }] : []),
        ]} note={t("Kapanışlarla hesaplanır: iğne (fitil) sayılmaz.")} />
      )}
      {ai.body && (
        <K.AiNote model={ai.model || t("Yapay zekâ")} time={item.time}>
          {ai.body.split(/\n{2,}/).map((p, i) => <p key={i} style={{ whiteSpace: "pre-wrap" }}>{p}</p>)}
        </K.AiNote>
      )}
    </div>
  );
}
