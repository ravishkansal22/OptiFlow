import React from 'react';
import { ArrowRight, Minus, TrendingDown, TrendingUp } from 'lucide-react';
import { cn } from '../components/ui';
import { num, pct, usd } from '../lib/format';
import type { SnapshotRow } from '../lib/network';

const formatValue = (value: number, format: SnapshotRow['format']) => {
  switch (format) {
    case 'pct':
      return pct(value, 1);
    case 'minutes':
      return `${value.toFixed(1)} min`;
    case 'usd':
      return usd(value);
    default:
      return num(value);
  }
};

const formatChange = (value: number, format: SnapshotRow['format']) => {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  const magnitude = Math.abs(value);
  switch (format) {
    case 'pct':
      return `${sign}${magnitude.toFixed(1)} pts`;
    case 'minutes':
      return `${sign}${magnitude.toFixed(1)} min`;
    case 'usd':
      return `${sign}${usd(magnitude)}`;
    default:
      return `${sign}${num(magnitude)}`;
  }
};

/**
 * One measure, before and after. The arrow direction is the raw movement; the
 * colour says whether that movement is good for this particular measure, which
 * is not the same thing for cost as it is for coverage.
 */
export const DeltaRow: React.FC<{ row: SnapshotRow; className?: string }> = ({ row, className }) => {
  const { delta: d, format, label } = row;
  const unchanged = Math.abs(d.change) < 1e-9;
  const Icon = unchanged ? Minus : d.change > 0 ? TrendingUp : TrendingDown;
  const tone = unchanged ? 'text-faint' : d.better ? 'text-pass' : 'text-danger';

  return (
    <div className={cn('rounded-lg border border-line bg-surface px-3.5 py-3', className)}>
      <div className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">{label}</div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="num text-sm text-muted line-through decoration-faint/60">
          {formatValue(d.before, format)}
        </span>
        <ArrowRight className="h-3 w-3 shrink-0 text-faint" />
        <span
          className={cn(
            'num font-display text-xl font-medium leading-none tracking-tight',
            unchanged ? 'text-ink' : tone
          )}
        >
          {formatValue(d.after, format)}
        </span>
      </div>
      <div className={cn('mt-1.5 flex items-center gap-1 text-2xs font-medium', tone)}>
        <Icon className="h-3 w-3" />
        {unchanged ? 'unchanged' : formatChange(d.change, format)}
      </div>
    </div>
  );
};

/** The whole measured comparison, laid out as a grid of before/after cells. */
export const SnapshotComparison: React.FC<{
  rows: SnapshotRow[];
  className?: string;
}> = ({ rows, className }) => (
  <div className={cn('grid gap-3 sm:grid-cols-2 lg:grid-cols-3', className)}>
    {rows.map((row) => (
      <DeltaRow key={row.key} row={row} />
    ))}
  </div>
);

/** A single headline figure with a caption, used beside the comparison grid. */
export const HeadlineStat: React.FC<{
  label: string;
  value: string;
  hint?: string;
  tone?: 'accent' | 'pass' | 'danger' | 'warn' | 'neutral';
  className?: string;
}> = ({ label, value, hint, tone = 'neutral', className }) => (
  <div className={cn('rounded-lg border border-line bg-sunken px-3.5 py-3', className)}>
    <div className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">{label}</div>
    <div
      className={cn(
        'num mt-1 font-display text-xl font-medium leading-none tracking-tight',
        tone === 'accent'
          ? 'text-accent'
          : tone === 'pass'
            ? 'text-pass'
            : tone === 'danger'
              ? 'text-danger'
              : tone === 'warn'
                ? 'text-warn'
                : 'text-ink'
      )}
    >
      {value}
    </div>
    {hint && <p className="mt-1.5 text-2xs leading-relaxed text-muted">{hint}</p>}
  </div>
);
