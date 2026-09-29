export function Logo({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <rect width="64" height="64" rx="16" className="fill-accent-800" />
      <path d="M32 12c-8 10-14 18-14 25a14 14 0 0 0 28 0c0-7-6-15-14-25z" fill="#f0fdf4" />
      <path d="M32 30v20M32 40l-6-5M32 44l6-5" stroke="#166534" strokeWidth="3" strokeLinecap="round" fill="none" />
    </svg>
  );
}
