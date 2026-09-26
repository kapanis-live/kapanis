import { LoadingState, ErrorState } from "@/components/states";
import { formatApiErrorDetail } from "@/lib/api";

// react-query sonucunu sarar: yükleniyor / hata / veri.
export function DataView({ query, loadingText, children }) {
  if (query.isLoading) return <LoadingState text={loadingText} />;
  if (query.isError)
    return (
      <ErrorState
        text={formatApiErrorDetail(query.error?.response?.data?.detail) || query.error?.message}
        onRetry={() => query.refetch()}
      />
    );
  return children(query.data);
}

const TONE_TEXT = { up: "text-up", down: "text-down", wait: "text-wait", info: "text-info", brand: "text-brand" };

// Özet kartı: etiket 15px, değer 34px kalın, alt satır 15px
export function StatCard({ label, value, sub, tone, testid, icon: Icon, size = "md" }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-hairline bg-surface p-6" data-testid={testid}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[0.9375rem] font-medium text-t-2">{label}</span>
        {Icon && <Icon className="h-[1.125rem] w-[1.125rem] text-t-3" aria-hidden />}
      </div>
      <div className={`num font-bold leading-[1.1] tracking-[-0.01em] ${size === "sm" ? "text-[1.625rem]" : "text-[2.125rem]"} ${TONE_TEXT[tone] || "text-t-1"}`}>
        {value}
      </div>
      {sub && <div className="text-[0.9375rem] text-t-3">{sub}</div>}
    </div>
  );
}

export function Panel({ title, action, children, className = "", testid, bodyClass = "p-6" }) {
  return (
    <section className={`rounded-xl border border-hairline bg-surface ${className}`} data-testid={testid}>
      {(title || action) && (
        <div className="flex flex-wrap items-center justify-between gap-4 px-6 pt-5">
          {title && <h2 className="m-0 text-lg font-bold leading-snug text-t-1">{title}</h2>}
          {action}
        </div>
      )}
      <div className={(title || action) && bodyClass === "p-6" ? "px-6 pb-6 pt-4" : bodyClass}>{children}</div>
    </section>
  );
}
