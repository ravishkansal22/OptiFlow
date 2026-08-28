import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, FileSearch, RefreshCw } from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState, Meter, Segmented, Spinner, cn } from '../components/ui';
import { getProvenanceTrace } from '../services/api';
import { clockTime, num, titleCase } from '../lib/format';
import type { AgentTraceEvent, CriticReport, MireyeCallRecord, TraceStatus } from '../types';

type Tab = 'audit' | 'evidence' | 'trace';

export interface AuditPanelProps {
  report: CriticReport | null;
  flags: string[];
  trace: AgentTraceEvent[];
}

export const AuditPanel: React.FC<AuditPanelProps> = ({ report, flags, trace }) => {
  const [tab, setTab] = useState<Tab>('audit');

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-medium tracking-tight text-ink">
Our checks
          </h2>
          <p className="mt-0.5 text-xs text-muted">
We check our own answer before showing it to you.
          </p>
        </div>
        <Segmented<Tab>
          value={tab}
          onChange={setTab}
          options={[
            { value: 'audit', label: 'Findings' },
            { value: 'evidence', label: 'Map lookups' },
            { value: 'trace', label: `Steps ${trace.length}` },
          ]}
        />
      </div>

      {tab === 'audit' && <AuditTab report={report} flags={flags} />}
      {tab === 'evidence' && <EvidenceTab />}
      {tab === 'trace' && <TraceTab trace={trace} />}
    </div>
  );
};

/* ------------------------------------------------------------------ audit */

const AuditTab: React.FC<{ report: CriticReport | null; flags: string[] }> = ({ report, flags }) => {
  if (!report) {
    // Only reachable before the first audit; fall back to the flat flag list.
    return flags.length ? (
      <FindingList
        title="Reported issues"
        subtitle="Raised before a full audit report was available."
        items={flags}
        tone="warn"
        emptyLabel=""
      />
    ) : (
      <Card>
        <EmptyState
          icon={<FileSearch className="h-5 w-5" />}
          title="No audit on record"
          body="The critic agent runs after every optimisation and after every disruption recovery."
        />
      </Card>
    );
  }

  // Read both lists off the report rather than the flat `critic_flags` field:
  // the backend refreshes the report after a disruption recovery but leaves
  // `critic_flags` holding the pre-disruption audit, which would show stale
  // violations here.
  const violations = report.constraint_violations;
  const evidenceFlags = report.flags.filter((f) => !violations.includes(f));

  return (
    <div className="space-y-5">
      <Card className={cn('border-l-[3px]', report.passed ? 'border-l-pass' : 'border-l-warn')}>
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="flex items-start gap-3.5">
            <span
              className={cn(
                'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border',
                report.passed
                  ? 'border-pass/25 bg-pass-soft text-pass'
                  : 'border-warn/25 bg-warn-soft text-warn'
              )}
            >
              {report.passed ? <CheckCircle2 className="h-4.5 w-4.5" /> : <AlertTriangle className="h-4.5 w-4.5" />}
            </span>
            <div>
              <h3 className="font-display text-lg font-medium tracking-tight text-ink">
                {report.passed ? 'Everything checks out' : 'A few things to look at'}
              </h3>
              <p className="mt-1 max-w-lg text-xs leading-relaxed text-muted">
                {report.passed
                  ? 'Every warehouse we picked is backed by real map data, and nothing is over its limit.'
                  : 'The plan works, but read the points below before you spend money.'}
              </p>
            </div>
          </div>
          <div className="min-w-[13rem] flex-1">
            <div className="flex items-baseline justify-between">
              <span className="text-2xs uppercase tracking-[0.06em] text-faint">Backed by real data</span>
              <span className="num text-sm font-medium text-ink">{report.evidence_coverage_pct.toFixed(1)}%</span>
            </div>
            <Meter
              value={report.evidence_coverage_pct}
              max={100}
              tone={report.evidence_coverage_pct >= 95 ? 'pass' : 'warn'}
              className="mt-2"
            />
          </div>
        </div>

        <div className="mt-5 grid gap-3 border-t border-line pt-4 sm:grid-cols-4">
          <AuditStat label="Limits broken" value={violations.length} tone={violations.length ? 'danger' : 'pass'} />
          <AuditStat label="Data warnings" value={evidenceFlags.length} tone={evidenceFlags.length ? 'warn' : 'pass'} />
          <AuditStat label="Out-of-date lookups" value={report.stale_provenance_count} tone={report.stale_provenance_count ? 'warn' : 'pass'} />
          <AuditStat label="Missing lookups" value={report.missing_provenance_count} tone={report.missing_provenance_count ? 'danger' : 'pass'} />
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <FindingList
          title="Limits broken"
          subtitle="Places where the plan asks for more than is available."
          items={violations}
          tone="danger"
          emptyLabel="Nothing is over its limit."
        />
        <FindingList
          title="Data warnings"
          subtitle="Numbers we could not fully confirm."
          items={evidenceFlags}
          tone="warn"
          emptyLabel="Every number traces back to a real lookup."
        />
      </div>
    </div>
  );
};

const FindingList: React.FC<{
  title: string;
  subtitle: string;
  items: string[];
  tone: 'danger' | 'warn';
  emptyLabel: string;
}> = ({ title, subtitle, items, tone, emptyLabel }) => (
  <Card>
    <CardHeader
      title={title}
      subtitle={subtitle}
      action={<Badge tone={items.length ? tone : 'pass'}>{items.length}</Badge>}
    />
    {items.length === 0 ? (
      <p className="mt-4 flex items-center gap-2 text-xs text-muted">
        <CheckCircle2 className="h-3.5 w-3.5 text-pass" />
        {emptyLabel}
      </p>
    ) : (
      <ul className="mt-4 max-h-72 space-y-2 overflow-y-auto">
        {items.map((f, i) => (
          <li
            key={i}
            className={cn(
              'rounded-lg border px-3 py-2.5 text-xs leading-relaxed',
              tone === 'danger'
                ? 'border-danger/20 bg-danger-soft text-danger'
                : 'border-warn/20 bg-warn-soft text-warn'
            )}
          >
            {f}
          </li>
        ))}
      </ul>
    )}
  </Card>
);

const AuditStat: React.FC<{ label: string; value: number; tone: 'pass' | 'warn' | 'danger' }> = ({
  label,
  value,
  tone,
}) => (
  <div className="rounded-lg border border-line bg-sunken px-3.5 py-3">
    <div
      className={cn(
        'num font-display text-xl font-medium leading-none',
        value === 0 ? 'text-ink' : tone === 'danger' ? 'text-danger' : 'text-warn'
      )}
    >
      {value}
    </div>
    <div className="mt-1 text-2xs text-muted">{label}</div>
  </div>
);

/* --------------------------------------------------------------- evidence */

const EvidenceTab: React.FC = () => {
  const [data, setData] = useState<{ call_count: number; history: MireyeCallRecord[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getProvenanceTrace());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the evidence log.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const stats = useMemo(() => {
    const rows = data?.history ?? [];
    const cached = rows.filter((r) => r.cached).length;
    const latencies = rows.map((r) => Number(r.latency_ms ?? 0)).filter((n) => n > 0);
    const byEndpoint = new Map<string, number>();
    rows.forEach((r) => {
      const key = String(r.endpoint ?? 'unknown');
      byEndpoint.set(key, (byEndpoint.get(key) ?? 0) + 1);
    });
    return {
      shown: rows.length,
      cached,
      cacheRate: rows.length ? (cached / rows.length) * 100 : 0,
      avgLatency: latencies.length ? latencies.reduce((a, b) => a + b, 0) / latencies.length : 0,
      endpoints: [...byEndpoint.entries()].sort((a, b) => b[1] - a[1]),
    };
  }, [data]);

  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Card>
          <CardHeader
            title="Map lookups"
            subtitle="Every time we asked the map service for data."
            action={
              <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
                <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
                Refresh
              </Button>
            }
          />
          <div className="mt-4 grid grid-cols-2 gap-3">
            <AuditStat label="Calls all-time" value={data?.call_count ?? 0} tone="pass" />
            <AuditStat label="In the log below" value={stats.shown} tone="pass" />
          </div>
          {/* The backend only retains the most recent 100 calls, so every rate
              below describes that window rather than the all-time total. */}
          <p className="mt-3 text-2xs text-faint">
            Rates below cover the {stats.shown} most recent calls the backend still retains.
          </p>
          <div className="mt-3 space-y-3">
            <div>
              <div className="flex items-baseline justify-between">
                <span className="text-2xs text-muted">Served from cache</span>
                <span className="num text-xs font-medium text-ink">
                  {stats.cached} of {stats.shown} · {stats.cacheRate.toFixed(0)}%
                </span>
              </div>
              <Meter value={stats.cacheRate} max={100} tone="accent" className="mt-1.5" />
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-2xs text-muted">Mean latency</span>
              <span className="num text-xs font-medium text-ink">{stats.avgLatency.toFixed(0)} ms</span>
            </div>
          </div>

          {stats.endpoints.length > 0 && (
            <div className="mt-5 border-t border-line pt-4">
              <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">By endpoint</p>
              <ul className="mt-2.5 space-y-2">
                {stats.endpoints.slice(0, 6).map(([ep, count]) => (
                  <li key={ep} className="flex items-center gap-3">
                    <span className="num min-w-0 flex-1 truncate font-mono text-2xs text-muted" title={ep}>
                      {ep}
                    </span>
                    <span className="num shrink-0 text-2xs font-medium text-ink">{count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        <Card flush>
          <div className="border-b border-line px-5 py-3.5">
            <CardHeader
              title="Call log"
              subtitle={`Most recent ${stats.shown} calls, newest first.`}
            />
          </div>
          <div className="max-h-[30rem] overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-16 text-xs text-muted">
                <Spinner className="h-3.5 w-3.5" /> Loading the evidence log…
              </div>
            ) : error ? (
              <EmptyState icon={<Database className="h-5 w-5" />} title="Could not load" body={error} />
            ) : !data?.history.length ? (
              <EmptyState
                icon={<Database className="h-5 w-5" />}
                title="No calls recorded"
                body="Lookups appear here as soon as a study runs."
              />
            ) : (
              <ul className="divide-y divide-line">
                {[...data.history].reverse().map((r, i) => (
                  <li key={i} className="px-5 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <span className="num min-w-0 truncate font-mono text-2xs text-ink" title={String(r.endpoint)}>
                        {String(r.endpoint ?? 'unknown')}
                      </span>
                      <div className="flex shrink-0 items-center gap-2">
                        <Badge tone={r.cached ? 'neutral' : 'accent'}>{r.cached ? 'cache' : 'live'}</Badge>
                        {r.latency_ms != null && (
                          <span className="num font-mono text-2xs text-faint">
                            {Number(r.latency_ms).toFixed(0)}ms
                          </span>
                        )}
                      </div>
                    </div>
                    {r.params && Object.keys(r.params).length > 0 && (
                      <p className="num mt-1 truncate font-mono text-2xs text-faint">
                        {Object.entries(r.params)
                          .slice(0, 4)
                          .map(([k, v]) => `${k}=${typeof v === 'number' ? Number(v).toFixed(4) : String(v)}`)
                          .join('  ')}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ trace */

const STATUS_TONE: Record<TraceStatus, string> = {
  start: 'bg-info',
  progress: 'bg-accent',
  complete: 'bg-pass',
  warning: 'bg-warn',
  error: 'bg-danger',
};

const TraceTab: React.FC<{ trace: AgentTraceEvent[] }> = ({ trace }) => {
  const [agent, setAgent] = useState<string>('all');

  const agents = useMemo(() => [...new Set(trace.map((e) => e.agent_name))], [trace]);
  const visible = useMemo(
    () => (agent === 'all' ? trace : trace.filter((e) => e.agent_name === agent)),
    [trace, agent]
  );

  if (!trace.length) {
    return (
      <Card>
        <EmptyState
          icon={<FileSearch className="h-5 w-5" />}
          title="No activity recorded"
          body="Agent activity streams here live while a study runs."
        />
      </Card>
    );
  }

  return (
    <Card flush>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <CardHeader title="Agent activity" subtitle={`${visible.length} of ${trace.length} events`} />
        <div className="flex flex-wrap gap-1.5">
          <FilterChip active={agent === 'all'} onClick={() => setAgent('all')}>
            All
          </FilterChip>
          {agents.map((a) => (
            <FilterChip key={a} active={agent === a} onClick={() => setAgent(a)}>
              {a.replace(/ Agent$/, '').replace('Reporting / Narrator', 'Narrator')}
            </FilterChip>
          ))}
        </div>
      </div>
      <ol className="max-h-[34rem] divide-y divide-line overflow-y-auto">
        {[...visible].reverse().map((e) => (
          <li key={e.event_id} className="flex items-start gap-3 px-5 py-3">
            <span className={cn('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', STATUS_TONE[e.status] ?? 'bg-faint')} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-2xs font-medium text-ink">{e.agent_name}</span>
                <span className="num font-mono text-2xs text-faint">{titleCase(e.action)}</span>
                {e.timestamp && (
                  <span className="num ml-auto font-mono text-2xs text-faint">{clockTime(e.timestamp)}</span>
                )}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted">{e.message}</p>
              {e.provenance && (
                <p className="num mt-1 truncate font-mono text-2xs text-faint">
                  {e.provenance.endpoint} · #{e.provenance.response_hash?.slice(0, 10)} ·{' '}
                  {e.provenance.cached ? 'cache' : 'live'} · {num(e.provenance.latency_ms)}ms
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
};

const FilterChip: React.FC<{ active: boolean; onClick: () => void; children: React.ReactNode }> = ({
  active,
  onClick,
  children,
}) => (
  <button
    onClick={onClick}
    className={cn(
      'rounded-md border px-2 py-1 text-2xs font-medium transition-colors focus-ring',
      active
        ? 'border-accent/30 bg-accent-soft text-accent'
        : 'border-line bg-surface text-muted hover:text-ink'
    )}
  >
    {children}
  </button>
);
