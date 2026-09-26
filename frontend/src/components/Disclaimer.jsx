export function Disclaimer({ className = "" }) {
  return (
    <p data-testid="legal-disclaimer"
      className={`mt-10 border-t border-hairline pb-2 pt-5 text-center text-[0.9375rem] text-t-3 ${className}`}>
      Yatırım tavsiyesi değildir. Bot işlem yapmaz.
    </p>
  );
}
