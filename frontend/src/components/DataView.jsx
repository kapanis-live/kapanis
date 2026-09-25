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

export function StatCard({ label, value, sub, tone, testid }) {
  const toneCls = tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "wait" ? "text-wait" : "text-t-1";
  return (
    <div className="rounded-xl border border-hairline bg-surface p-4" data-testid={testid}>
      <div className="text-xs text-t-2">{label}</div>
      <div className={`num mt-1.5 text-xl font-bold ${toneCls}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-t-3">{sub}</div>}
    </div>
  );
}

export function Panel({ title, action, children, className = "", testid }) {
  return (
    <section className={`rounded-xl border border-hairline bg-surface ${className}`} data-testid={testid}>
      {(title || action) && (
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3.5">
          {title && <h2 className="text-sm font-semibold text-t-1">{title}</h2>}
          {action}
        </div>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}
