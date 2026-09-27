import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { relDay } from "@/lib/dsmap";
import { PageHeader } from "@/components/PanelLayout";
import api, { formatApiErrorDetail } from "@/lib/api";
import { useData, LIVE } from "@/lib/useData";

const empty = { name: "", fk_max: "", momentum_min: "", quality_min: "" };
const numberOrNull = (s) => (String(s).trim() === "" ? null : U.parseTr(String(s)));

const pct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}%${U.fmtNum(Math.abs(v), 2)}`);
const tone = (v) => (v == null ? "" : v >= 0 ? "kp-num-up" : "kp-num-down");

// Geçmiş sonuçlar: her taramada seçilenlerin o günden bu yana getirisi, BIST 100 ile yan yana (ileriye dönük kayıt)
function History({ id }) {
  const q = useData(["strategy-history", id], `/strategies/${encodeURIComponent(id)}/history`);
  const runs = q.data?.kosular || [];
  if (q.isLoading) return <p className="kp-note">Geçmiş yükleniyor…</p>;
  if (!runs.length) return <p className="kp-note">Henüz tarama yok. İlk taramadan sonra seçilen hisselerin o günden bu yana sonucu burada izlenir.</p>;
  return (
    <div className="mt-3">
      <K.DataTable rows={runs} rowKey="id" columns={[
        { key: "zaman", label: "Tarama", render: (r) => relDay(r.zaman) },
        { key: "secilen", label: "Seçilenler", render: (r) => r.secilen.map((p) => p.kod).join(", ") || "yok" },
        { key: "ortalama_getiri", label: "O günden bu yana", num: true, strong: true, render: (r) => <span className={tone(r.ortalama_getiri)}>{pct(r.ortalama_getiri)}</span> },
        { key: "xu100_getiri", label: "BIST 100", num: true, render: (r) => <span className={tone(r.xu100_getiri)}>{pct(r.xu100_getiri)}</span> },
      ]} />
      <p className="kp-note">{q.data?.not}</p>
    </div>
  );
}

export default function Strategies() {
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState(null);
  const qc = useQueryClient();
  const q = useData("strategies", "/strategies", LIVE);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const save = async () => {
    if (!form.name.trim()) return toast.error("Stratejiye bir ad ver.");
    if (["fk_max", "momentum_min", "quality_min"].some((key) => form[key] !== "" && !Number.isFinite(numberOrNull(form[key]))))
      return toast.error("Koşullar sayı olmalı.");
    setBusy("save");
    try {
      await api.post("/strategies", { name: form.name, rules: {
        fk_max: numberOrNull(form.fk_max), momentum_min: numberOrNull(form.momentum_min), quality_min: numberOrNull(form.quality_min) } });
      setForm(empty);
      qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success("Strateji kaydedildi.");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  const run = async (id) => {
    setBusy(id);
    try {
      await api.post(`/strategies/${encodeURIComponent(id)}/run`);
      toast.success("BIST 100 taraması başladı. Sonuç Son Analizlerim'e ve bağlı Telegram'a gelecek.");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  const remove = async (id) => {
    setBusy(id);
    try {
      await api.delete(`/strategies/${encodeURIComponent(id)}`);
      qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success("Strateji silindi.");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(""); }
  };
  return <div className="kp-page">
    <PageHeader title="Strateji Kurucu" subtitle="BIST 100 içinde kalite, değer ve 3 aylık göreli momentum koşullarını birleştir." />
    <div className="kp-grid kp-split-l">
      <K.Card title="Yeni strateji">
        <div className="grid gap-3">
          <K.Field label="Ad"><K.TextInput value={form.name} onChange={set("name")} placeholder="Örn. Altın Vuruş" maxLength={40} /></K.Field>
          <K.Field label="F/K bu değerden küçük" hint="boş bırakırsan filtrelenmez"><K.TextInput inputMode="decimal" value={form.fk_max} onChange={set("fk_max")} placeholder="10" /></K.Field>
          <K.Field label="3 aylık getiri BIST 100'den en az %" hint="eksi değer de girilebilir"><K.TextInput inputMode="decimal" value={form.momentum_min} onChange={set("momentum_min")} placeholder="0" /></K.Field>
          <K.Field label="Kalite puanı en az" hint="0–100; getiri olasılığı değildir"><K.TextInput inputMode="decimal" value={form.quality_min} onChange={set("quality_min")} placeholder="70" /></K.Field>
          <K.Button variant="primary" disabled={!!busy} onClick={save}>Stratejiyi kaydet</K.Button>
        </div>
        <p className="kp-note">Bilanço sürprizi koşulu için yayın tarihiyle eşleşen güvenilir geçmiş veri gerekir; henüz seçim olarak açılmadı. Tarama gerçek emir vermez.</p>
      </K.Card>
      <K.Card title="Kayıtlı stratejiler">
        {q.isLoading ? <p className="kp-note">Yükleniyor…</p> : !q.data?.length ?
          <p className="kp-note">Henüz strateji kaydetmedin.</p> : <div className="flex flex-col gap-3">{q.data.map((s) =>
            <div key={s.id} className="rounded-lg border border-hairline p-3">
              <b className="text-t-1">{s.name}</b>
              <p className="my-2 text-sm text-t-2">{[
                s.rules.fk_max != null && `F/K < ${s.rules.fk_max}`,
                s.rules.momentum_min != null && `Göreli 3 ay ≥ %${s.rules.momentum_min}`,
                s.rules.quality_min != null && `Kalite ≥ ${s.rules.quality_min}`,
              ].filter(Boolean).join(" · ") || "Filtre yok; kalite ve momentum birlikte sıralanır."}</p>
              <div className="flex flex-wrap gap-2">
                <K.Button variant="primary" disabled={!!busy} onClick={() => run(s.id)}>{busy === s.id ? "İşleniyor…" : "BIST 100'ü tara"}</K.Button>
                <K.Button variant="ghost" onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? "Geçmişi gizle" : "Geçmiş sonuçlar"}</K.Button>
                <K.Button variant="ghost" disabled={!!busy} onClick={() => remove(s.id)}>Sil</K.Button>
              </div>
              {open === s.id && <History id={s.id} />}
              <p className="mb-0 mt-2 text-xs text-t-3">Telegram: /tara {s.name}</p>
            </div>)}</div>}
        <Link to="/app/analizlerim" className="mt-4 inline-block font-semibold text-info">Son Analizlerim →</Link>
      </K.Card>
    </div>
  </div>;
}
