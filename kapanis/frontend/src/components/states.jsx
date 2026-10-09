import { Inbox, AlertTriangle } from "lucide-react";
import { TEXTS } from "@/lib/texts";
import { useLang } from "@/lib/i18n";

export function LoadingState({ text = TEXTS.loading.default, testid = "loading-state" }) {
  const { t } = useLang();
  text = t(text);
  return (
    // iskelet: sayfanın gri taslağı; veri gelince yerine oturur, sayfa zıplamaz
    <div data-testid={testid} aria-busy="true" aria-label={text} className="flex flex-col gap-4 py-2">
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(12rem, 1fr))" }}>
        {[0, 1, 2].map((i) => <div key={i} className="kp-skel h-24" />)}
      </div>
      <div className="kp-skel h-64" />
      <span className="sr-only">{text}</span>
    </div>
  );
}

export function EmptyState({ text = TEXTS.empty.generic, testid = "empty-state", children }) {
  const { t } = useLang();
  text = t(text);
  return (
    <div data-testid={testid} className="flex flex-col items-center justify-center gap-3 py-16 text-center animate-fade-in">
      <div className="flex h-11 w-11 items-center justify-center rounded-full border border-hairline bg-surface">
        <Inbox className="h-5 w-5 text-t-3" />
      </div>
      <p className="max-w-sm text-sm text-t-2">{text}</p>
      {children}
    </div>
  );
}

export function ErrorState({ text = TEXTS.error.default, onRetry, testid = "error-state" }) {
  const { t } = useLang();
  text = t(text);
  return (
    <div data-testid={testid} className="flex flex-col items-center justify-center gap-3 py-16 text-center animate-fade-in">
      <div className="flex h-11 w-11 items-center justify-center rounded-full border border-down/40 bg-down/10">
        <AlertTriangle className="h-5 w-5 text-down" />
      </div>
      <p className="max-w-sm text-sm text-t-2">{text}</p>
      {onRetry && (
        <button
          data-testid="error-retry-btn"
          onClick={onRetry}
          className="mt-1 rounded-md border border-hairline px-3 py-1.5 text-xs text-t-1 transition-colors duration-150 hover:bg-secondary"
        >
          {t(TEXTS.error.retry)}
        </button>
      )}
    </div>
  );
}

export function SkeletonRows({ rows = 4 }) {
  return (
    <div className="space-y-2" data-testid="skeleton-rows">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-12 rounded-md bg-surface animate-pulse" style={{ animationDelay: `${i * 60}ms` }} />
      ))}
    </div>
  );
}
