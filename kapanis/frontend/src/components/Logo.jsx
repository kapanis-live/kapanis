// Logo: iki çizgi arasından geçen bir ok — "kapıdan kapanışla geçmek".
export function LogoMark({ size = 28, className = "" }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" className={className} aria-hidden="true">
      {/* iki dikey çizgi (kapı) */}
      <line x1="6" y1="4" x2="6" y2="28" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <line x1="26" y1="4" x2="26" y2="28" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      {/* aradan geçen ok */}
      <line x1="2" y1="16" x2="24" y2="16" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M19 10 L26 16 L19 22" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

export function Logo({ withText = true, size = 28, className = "" }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`} data-testid="brand-logo">
      <LogoMark size={size} className="text-t-1" />
      {withText && (
        <span className="font-extrabold tracking-tight text-t-1 text-lg leading-none">
          Kapanış
        </span>
      )}
    </span>
  );
}
