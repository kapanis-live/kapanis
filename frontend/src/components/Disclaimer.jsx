import { TEXTS } from "@/lib/texts";

export function Disclaimer({ className = "" }) {
  return (
    <p
      data-testid="legal-disclaimer"
      className={`text-xs leading-relaxed text-t-3 border-t border-hairline pt-4 ${className}`}
    >
      <span className="text-t-2 font-medium">Yasal uyarı — </span>
      {TEXTS.disclaimer}
    </p>
  );
}
