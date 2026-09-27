import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { K } from "@/ds";
import { PageHeader } from "@/components/PanelLayout";
import { useData, LIVE } from "@/lib/useData";
import { splitAi, relDay } from "@/lib/dsmap";

export default function MyAnalyses() {
  const [params, setParams] = useSearchParams();
  const q = useData("my-analyses", "/analyses", LIVE);
  const rows = q.data || [];
  const selected = useMemo(() => rows.find((r) => r.id === params.get("id")) || rows[0], [rows, params]);
  return <div className="kp-page">
    <PageHeader title="Son Analizlerim" subtitle="Telegram ve panelden istediğin analizler, yalnız kendi hesabında." />
    {q.isLoading ? <p className="kp-note">Analizler yükleniyor…</p> : q.isError ?
      <p className="kp-note">Analizler şu an alınamadı.</p> : !rows.length ?
      <K.EmptyState icon="chart" title="Henüz analiz yok">Grafik sayfasında bir kod seçip “Analiz et”e bas.</K.EmptyState> :
      <div className="kp-grid kp-split-l">
        <K.Card title={`Kayıtlı analizler (${rows.length})`}>
          <div className="flex flex-col gap-2">{rows.map((r) =>
            <button key={r.id} type="button" onClick={() => setParams({ id: r.id })}
              aria-current={selected?.id === r.id ? "true" : undefined}
              className={`rounded-lg border p-3 text-left ${selected?.id === r.id ? "border-strong bg-raised" : "border-hairline hover:bg-raised"}`}>
              <span className="block font-semibold text-t-1">{(r.kodlar || []).join(", ") || "Analiz"}</span>
              <span className="text-sm text-t-3">{r.piyasa || "Piyasa"} · {relDay(r.zaman)}</span>
            </button>)}</div>
        </K.Card>
        {selected && <K.Card title={(selected.kodlar || []).join(", ") || "Analiz"}>
          <p className="kp-note">{selected.piyasa} · {relDay(selected.zaman)}</p>
          <div className="whitespace-pre-wrap leading-relaxed text-t-1">{splitAi(selected.metin || "").body}</div>
          {(selected.kodlar || []).map((code) => <Link key={code} className="mr-3 mt-4 inline-block font-semibold text-info"
            to={`/app/grafik?kod=${encodeURIComponent(code)}&piyasa=${encodeURIComponent(selected.piyasa || "BIST")}`}>
            {code} grafiğini aç →
          </Link>)}
        </K.Card>}
      </div>}
  </div>;
}
