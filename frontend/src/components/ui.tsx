import React from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export const cn = (...parts: any[]) => twMerge(clsx(parts));

/* ------------------------------------------------------------------ Card */

export const Card: React.FC<React.HTMLAttributes<HTMLDivElement> & { flush?: boolean }> = ({
  className,
  flush,
  children,
  ...rest
}) => (
  <div
    className={cn(
      'rounded-xl border border-line bg-surface shadow-card',
      !flush && 'p-5',
      className
    )}
    {...rest}
  >
    {children}
  </div>
);

export const CardHeader: React.FC<{
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}> = ({ title, subtitle, action, className }) => (
  <div className={cn('flex items-start justify-between gap-4', className)}>
    <div className="min-w-0">
      <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
      {subtitle && <p className="mt-0.5 text-xs leading-relaxed text-muted">{subtitle}</p>}
    </div>
    {action && <div className="shrink-0">{action}</div>}
  </div>
);

/* ---------------------------------------------------------------- Button */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-white border-transparent hover:brightness-110 active:brightness-95 shadow-card disabled:bg-strong disabled:text-faint',
  secondary:
    'bg-surface text-ink border-line hover:bg-sunken hover:border-strong active:bg-line',
  ghost: 'bg-transparent text-muted border-transparent hover:bg-sunken hover:text-ink',
  danger: 'bg-danger text-white border-transparent hover:brightness-110 active:brightness-95',
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5 rounded-lg',
  md: 'h-9 px-4 text-[13px] gap-2 rounded-lg',
  lg: 'h-11 px-6 text-sm gap-2 rounded-xl',
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'secondary',
  size = 'md',
  loading,
  className,
  disabled,
  children,
  ...rest
}) => (
  <button
    className={cn(
      'inline-flex select-none items-center justify-center border font-medium transition-all duration-150 focus-ring',
      'disabled:cursor-not-allowed disabled:opacity-60',
      BUTTON_VARIANTS[variant],
      BUTTON_SIZES[size],
      className
    )}
    disabled={disabled || loading}
    {...rest}
  >
    {loading && <Spinner className="h-3.5 w-3.5" />}
    {children}
  </button>
);

export const Spinner: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={cn('animate-spin', className)} viewBox="0 0 24 24" fill="none" aria-hidden>
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.22" />
    <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
  </svg>
);

/* ------------------------------------------------------------------ Badge */

export type Tone = 'neutral' | 'accent' | 'pass' | 'warn' | 'danger' | 'info';

const TONES: Record<Tone, string> = {
  neutral: 'bg-sunken text-muted border-line',
  accent: 'bg-accent-soft text-accent border-accent/25',
  pass: 'bg-pass-soft text-pass border-pass/25',
  warn: 'bg-warn-soft text-warn border-warn/25',
  danger: 'bg-danger-soft text-danger border-danger/25',
  info: 'bg-info-soft text-info border-info/25',
};

export const Badge: React.FC<{
  tone?: Tone;
  className?: string;
  children: React.ReactNode;
  dot?: boolean;
}> = ({ tone = 'neutral', className, children, dot }) => (
  <span
    className={cn(
      'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-2xs font-medium leading-4',
      TONES[tone],
      className
    )}
  >
    {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
    {children}
  </span>
);

/* ------------------------------------------------------------------- Stat */

/** Static map: Tailwind cannot resolve interpolated class names at build time. */
const TEXT_TONES: Record<Tone, string> = {
  neutral: 'text-ink',
  accent: 'text-accent',
  pass: 'text-pass',
  warn: 'text-warn',
  danger: 'text-danger',
  info: 'text-info',
};

export const Stat: React.FC<{
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: Tone;
  className?: string;
}> = ({ label, value, hint, tone = 'neutral', className }) => (
  <div className={cn('min-w-0', className)}>
    <div className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">{label}</div>
    <div
      className={cn(
        'num mt-1 truncate font-display text-2xl font-medium leading-none tracking-tight',
        TEXT_TONES[tone]
      )}
    >
      {value}
    </div>
    {hint && <div className="mt-1.5 truncate text-xs text-muted">{hint}</div>}
  </div>
);

/* ------------------------------------------------------------------ Meter */

export const Meter: React.FC<{
  value: number;
  max?: number;
  tone?: Tone;
  className?: string;
}> = ({ value, max = 1, tone = 'accent', className }) => {
  const filled = Math.max(0, Math.min(1, value / max));
  const barColor =
    tone === 'pass' ? 'bg-pass' : tone === 'warn' ? 'bg-warn' : tone === 'danger' ? 'bg-danger' : tone === 'info' ? 'bg-info' : 'bg-accent';
  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-sunken', className)}>
      <div
        className={cn('h-full rounded-full transition-[width] duration-500 ease-out', barColor)}
        style={{ width: `${filled * 100}%` }}
      />
    </div>
  );
};

/* ------------------------------------------------------------- Empty state */

export const EmptyState: React.FC<{
  icon?: React.ReactNode;
  title: string;
  body?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}> = ({ icon, title, body, action, className }) => (
  <div className={cn('flex flex-col items-center justify-center px-6 py-16 text-center', className)}>
    {icon && (
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl border border-line bg-sunken text-faint">
        {icon}
      </div>
    )}
    <p className="text-sm font-semibold text-ink">{title}</p>
    {body && <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-muted">{body}</p>}
    {action && <div className="mt-5">{action}</div>}
  </div>
);

/* ---------------------------------------------------------------- Tooltip */

/** Lightweight hover label. Positioned above the trigger. */
export const Hint: React.FC<{ label: string; children: React.ReactNode; className?: string }> = ({
  label,
  children,
  className,
}) => (
  <span className={cn('group/hint relative inline-flex', className)}>
    {children}
    <span
      role="tooltip"
      className="pointer-events-none absolute bottom-[calc(100%+6px)] left-1/2 z-50 w-max max-w-[16rem] -translate-x-1/2 scale-95 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-2xs leading-relaxed text-ink opacity-0 shadow-pop transition-all duration-150 group-hover/hint:scale-100 group-hover/hint:opacity-100"
    >
      {label}
    </span>
  </span>
);

/* ----------------------------------------------------------------- Dialog */

export const Dialog: React.FC<{
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  wide?: boolean;
}> = ({ open, onClose, title, subtitle, children, wide }) => {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 sm:p-8">
      <div
        className="fixed inset-0 animate-fade-in bg-ink/25 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          'relative z-10 w-full animate-fade-up rounded-2xl border border-line bg-surface shadow-pop',
          wide ? 'max-w-3xl' : 'max-w-lg'
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h3 className="font-display text-lg font-medium leading-tight tracking-tight text-ink">{title}</h3>
            {subtitle && <p className="mt-1 text-xs text-muted">{subtitle}</p>}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close" className="-mr-1.5 -mt-1 px-2">
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </Button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------ Segmented */

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  className,
}: {
  value: T;
  options: { value: T; label: React.ReactNode }[];
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={cn('inline-flex rounded-lg border border-line bg-sunken p-0.5', className)}>
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'rounded-[6px] px-2.5 py-1 text-2xs font-medium transition-all duration-150 focus-ring',
            value === o.value
              ? 'bg-surface text-ink shadow-card'
              : 'text-muted hover:text-ink'
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------- Skeleton */

export const SkeletonBlock: React.FC<{ className?: string }> = ({ className }) => (
  <div className={cn('skeleton', className)} />
);

/* ------------------------------------------------------------------- Mark */

/** The OptiFlow glyph: a stacked-node network cube. */
export const Mark: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    viewBox="0 0 24 24"
    className={cn('h-5 w-5 text-accent', className)}
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden
  >
    <path d="M12 2 3 7v10l9 5 9-5V7z" />
    <path d="m3 7 9 5 9-5" />
    <path d="M12 12v10" />
  </svg>
);
