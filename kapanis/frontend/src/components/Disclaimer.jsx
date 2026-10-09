import { useLang } from "@/lib/i18n";

export function Disclaimer({ className = "" }) {
  const { t } = useLang();
  return (
    <p data-testid="legal-disclaimer"
      className={`mt-10 border-t border-hairline pb-2 pt-5 text-center text-[0.9375rem] text-t-3 ${className}`}>
      {t("Yatırım tavsiyesi değildir. Bot işlem yapmaz.")}
    </p>
  );
}
