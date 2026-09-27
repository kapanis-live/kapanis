import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { K, U } from "@/ds";
import { PageHeader } from "@/components/PanelLayout";
import { useData } from "@/lib/useData";
import api, { formatApiErrorDetail } from "@/lib/api";

const CUR = (p) => (p.piyasa === "BIST" ? "TRY" : "USD");
const money = (v, cur) => (v == null ? "—" : U.fmtPrice(v, cur, 2));

// Etkilenen pozisyonlar: planın dokunduğu ve dokunmadığı her açık pozisyon, stopa kadar risk şimdi → plan sonrası
function Affected({ rows, selected }) {
  if (!rows?.length) return null;
  // TL ve $ ayrı toplanır
  const sums = {};
  rows.forEach((r) => {
    const c = CUR(r);
    sums[c] = sums[c] || { now: 0, after: 0 };
    sums[c].now += r.risk_simdi ?? 0;
    sums[c].after += (selected.includes(r.id) ? r.risk_sonra : r.risk_simdi) ?? 0;
  });
  const totals = Object.entries(sums).map(([c, t]) => `${money(t.now, c)} → ${money(t.after, c)}`).join(" · ");
  return (
    <K.Card title={`Etkilenen pozisyonlar (${rows.length})`}>
      <K.DataTable rows={rows} rowKey="id" columns={[
        { key: "kod", label: "Kod", render: (r) => <b>{r.kod}</b> },
        { key: "fiyat", label: "Son kapanış", num: true, render: (r) => money(r.fiyat, CUR(r)) },
        { key: "stop", label: "Stop", num: true, render: (r) => (r.onerilen_stop != null && selected.includes(r.id)
          ? <span>{money(r.eski_stop, CUR(r))} → <b>{money(r.onerilen_stop, CUR(r))}</b></span> : money(r.eski_stop, CUR(r))) },
        { key: "risk", label: "Stopa kadar risk", num: true, render: (r) => {
          const now = r.risk_simdi, next = selected.includes(r.id) ? r.risk_sonra : now;
          if (now == null && next == null) return r.eski_stop == null ? "stop yok" : "—";
          return next !== now ? <span>{money(now, CUR(r))} → <b className="kp-num-up">{money(next, CUR(r))}</b></span> : money(now, CUR(r));
        } },
        { key: "o", label: "Öneri", render: (r) => (r.onerilen_stop != null ? "stop yükseltme" : r.fiyat == null ? "fiyat alınamadı" : "değişiklik yok") },
      ]} />
      <p className="kp-note">Stopa kadar risk: son kapanıştan stopa düşüşte adet × fark; stopu olmayan pozisyonun riski sayılamaz.
        Seçtiklerinle toplam: {totals}. Stop fiyatı satışın o fiyattan gerçekleşeceğini garanti etmez:
        piyasa boşlukla açılırsa satış daha düşükten olabilir.</p>
    </K.Card>
  );
}

export default function Crisis() {
  const qc = useQueryClient();
  const portfolio = useData("my-portfolio", "/portfolio");
  const latest = useData("risk-proposal", "/risk/proposals/latest");
  const [proposal, setProposal] = useState(null);
  const [selected, setSelected] = useState([]);
  const [busy, setBusy] = useState(false);
  const plan = proposal || latest.data;
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["my-portfolio"] });
    qc.invalidateQueries({ queryKey: ["risk-proposal"] });
  };
  const run = async (fn, success) => {
    setBusy(true);
    try { await fn(); toast.success(success); refresh(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail) || "İşlem yapılamadı."); }
    finally { setBusy(false); }
  };
  const create = () => run(async () => {
    const { data } = await api.post("/risk/proposals");
    setProposal(data);
    setSelected([]);
  }, "Kriz planı hazır. Değişiklikleri inceleyip uygulayabilirsin.");
  const apply = () => run(async () => {
    await api.post(`/risk/proposals/${encodeURIComponent(plan.id)}/apply`, { position_ids: selected });
    setProposal(null);
  }, "Seçtiğin değişiklikler kaydedildi.");
  const restore = () => run(() => api.post("/risk/restore-target"), "Önceki risk hedefin geri yüklendi. Stoplar korunuyor.");
  const toggle = (id) => setSelected((xs) => xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]);
  const d = portfolio.data;
  return <div className="kp-page">
    <PageHeader title="Kriz planı" subtitle="Portföyündeki olası risk azaltmalarını incele; değişiklikler ancak sen uygulayınca kaydedilir." />
    {d?.risk_mode === "defansif" && <K.Callout tone="warn" title="Defansif mod açık">
      Risk hedefin %{U.fmtNum(d.risk_target_pct, 2)}. <K.Button variant="secondary" disabled={busy} onClick={restore}>Önceki hedefe dön</K.Button>
    </K.Callout>}
    <K.Card title="Risk hedefi">
      <p className="text-t-2">Şu an: <b>%{U.fmtNum(d?.risk_target_pct ?? 1, 2)}</b>. Kriz planı bunu yarıya indirmeyi önerir.</p>
      <p className="kp-note">Bu hedef yalnız panelde tuttuğun bir risk ayarıdır; emir, satış veya aracı kurum işlemi yapmaz.</p>
      <K.Button variant="primary" disabled={busy || portfolio.isLoading} onClick={create}>{busy ? "Hazırlanıyor…" : "Yeni kriz planı hazırla"}</K.Button>
    </K.Card>
    {plan?.id && <K.Card title="Önerilen değişiklikler">
      <p className="text-t-2">Risk hedefi: %{U.fmtNum(plan.old_target_pct, 2)} → <b>%{U.fmtNum(plan.new_target_pct, 2)}</b></p>
      <p className="kp-note">Kârda olan pozisyonlar için stop önerileri aşağıda. Hangilerinin yükseltileceğini sen seçersin. Stop emri burada gönderilmez ve gerçekleşecek satış fiyatını garanti etmez.</p>
      {plan.suggestions?.length ? <div className="flex flex-col gap-2">
        {plan.suggestions.map((s) => <label key={s.id} className="flex cursor-pointer items-center gap-3 rounded-lg border border-hairline p-3">
          <input type="checkbox" checked={selected.includes(s.id)} onChange={() => toggle(s.id)} />
          <span><b>{s.kod}</b> · kapanış {U.fmtPrice(s.fiyat, s.piyasa === "BIST" ? "TRY" : "USD")} · stop {s.eski_stop == null ? "yok" : U.fmtNum(s.eski_stop, 2)} → <b>{U.fmtNum(s.onerilen_stop, 2)}</b></span>
        </label>)}
      </div> : <p className="kp-note">Yükseltilecek stop bulunamadı. Risk hedefini yine de düşürebilirsin.</p>}
      <K.Callout tone="warn" title="Uygulamadan önce: neyi geri alabilirsin?">
        Risk hedefi sonradan “Önceki hedefe dön” ile geri alınır. Yükseltilen stop <b>geri alınamaz</b>: kural gereği
        açık pozisyonda stop yalnız yukarı taşınır. Hiçbir şey otomatik değişmez; yalnız seçtiklerin kaydedilir. Emir gönderilmez.
      </K.Callout>
      <div className="mt-4 flex flex-wrap gap-2">
        <K.Button variant="primary" disabled={busy} onClick={apply}>{selected.length ? `Hedefi düşür ve ${selected.length} stopu yükselt` : "Yalnız risk hedefini düşür"}</K.Button>
        <Link to="/app/portfoyum"><K.Button variant="ghost">Portföyü gör</K.Button></Link>
      </div>
    </K.Card>}
    {plan?.id && <Affected rows={plan.affected} selected={selected} />}
  </div>;
}
