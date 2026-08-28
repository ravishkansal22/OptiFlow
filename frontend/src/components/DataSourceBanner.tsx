import React from 'react';
import { CheckCircle2, CloudOff, KeyRound, Trash2, TriangleAlert } from 'lucide-react';
import { Badge, Button, Meter, cn } from './ui';
import { num } from '../lib/format';
import type { DataSource } from '../types';

/**
 * Answers one question directly: are the numbers on screen real?
 *
 * A value is "live" only when the Mireye API answered successfully. Anything
 * else came from the local simulation model, which substitutes fixed defaults.
 */
export const DataSourceBanner: React.FC<{
  data: DataSource | null;
  compact?: boolean;
  className?: string;
  /** When given, renders a control that wipes caches and stored state. */
  onReset?: () => void;
  resetting?: boolean;
}> = ({ data, compact, className, onReset, resetting }) => {
  if (!data) return null;

  const { api_key_configured, live_values, simulated_values, total_values, live_pct } = data;
  const anySimulated = simulated_values > 0;

  const tone = !api_key_configured
    ? 'sim'
    : total_values === 0
      ? 'idle'
      : anySimulated
        ? 'mixed'
        : 'live';

  const palette = {
    live: { border: 'border-l-pass', bg: 'bg-pass-soft', text: 'text-pass', icon: CheckCircle2 },
    mixed: { border: 'border-l-warn', bg: 'bg-warn-soft', text: 'text-warn', icon: TriangleAlert },
    sim: { border: 'border-l-warn', bg: 'bg-warn-soft', text: 'text-warn', icon: KeyRound },
    idle: { border: 'border-l-line', bg: 'bg-sunken', text: 'text-muted', icon: CloudOff },
  }[tone];

  const Icon = palette.icon;

  const headline = !api_key_configured
    ? 'No API key — every value is simulated'
    : total_values === 0
      ? 'No values fetched yet'
      : anySimulated
        ? `${num(simulated_values)} of ${num(total_values)} values are simulated`
        : `All ${num(total_values)} values came from the API`;

  if (compact) {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-2xs font-medium',
          anySimulated || !api_key_configured
            ? 'border-warn/30 bg-warn-soft text-warn'
            : 'border-pass/30 bg-pass-soft text-pass',
          className
        )}
        title={headline}
      >
        <Icon className="h-3 w-3" />
        {total_values === 0 ? 'no data yet' : `${live_pct.toFixed(0)}% live`}
      </span>
    );
  }

  return (
    <div
      className={cn(
        'rounded-xl border border-line border-l-[3px] bg-surface p-4 shadow-card',
        palette.border,
        className
      )}
    >
      <div className="flex items-start gap-3.5">
        <span
          className={cn(
            'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
            palette.bg,
            palette.text
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold tracking-tight text-ink">{headline}</h3>
            <Badge tone={api_key_configured ? 'pass' : 'warn'}>
              {api_key_configured ? 'key configured' : 'no key'}
            </Badge>
            {data.strict_live && <Badge tone="accent">strict mode</Badge>}
            {onReset && (
              <Button
                variant="secondary"
                size="sm"
                onClick={onReset}
                loading={resetting}
                className="ml-auto"
                title="Clear every cached value, the call log, the network state and this browser's stored data"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear all data
              </Button>
            )}
          </div>

          <p className="mt-1.5 text-xs leading-relaxed text-muted">
            {!api_key_configured ? (
              <>
                Set <span className="num font-mono text-ink">MIREYE_API_KEY</span> in{' '}
                <span className="num font-mono text-ink">.env</span> and restart. Until then every
                terrain, land-cover and flood value is produced by the local simulation model.
              </>
            ) : total_values === 0 ? (
              <>
                Nothing has been fetched since the last reset. Run a check or a study and this will
                report exactly how many values came from{' '}
                <span className="num font-mono text-ink">{data.base_url}</span>.
              </>
            ) : anySimulated ? (
              <>
                A value is simulated when the API call fails or times out. Those fall back to fixed
                defaults, so any verdict resting on them is not evidence.
                {data.last_live_error && (
                  <>
                    {' '}
                    Last failure: <span className="num font-mono text-ink">{data.last_live_error}</span>.
                  </>
                )}
              </>
            ) : (
              <>
                Every terrain, land-cover, flood and routing value served so far came from{' '}
                <span className="num font-mono text-ink">{data.base_url}</span>.
              </>
            )}
          </p>

          {total_values > 0 && (
            <>
              <Meter
                value={live_pct}
                max={100}
                tone={anySimulated ? 'warn' : 'pass'}
                className="mt-3"
              />
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-muted">
                <span className="num">
                  <span className="font-semibold text-pass">{num(live_values)}</span> live
                </span>
                <span className="num">
                  <span className={cn('font-semibold', anySimulated ? 'text-warn' : 'text-muted')}>
                    {num(simulated_values)}
                  </span>{' '}
                  simulated
                </span>
                <span className="num text-faint">{data.cached_entries} cached</span>
                <span className="num text-faint">
                  timeout {data.request_timeout_s}s · {data.max_attempts} attempts
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
