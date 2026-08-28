import React, { useCallback, useEffect, useState } from 'react';
import { Check, Play, RefreshCw, Trash2, X } from 'lucide-react';
import { Button, Card, CardHeader, Spinner, cn } from '../components/ui';
import {
  API_BASE,
  ApiError,
  getDataSource,
  getHealth,
  getNetworkState,
  getProvenanceTrace,
  getRegion,
  getScenarios,
  resetBackend,
} from '../services/api';
import { DataSourceBanner } from '../components/DataSourceBanner';
import { num } from '../lib/format';
import type { DataSource, NetworkStateResponse } from '../types';
import type { ConnectionStatus } from '../services/websocket';

interface ProbeResult {
  method: string;
  path: string;
  status: 'idle' | 'running' | 'ok' | 'fail';
  httpStatus?: number;
  ms?: number;
  bytes?: number;
  error?: string;
  /** Short human summary of what came back, built from the payload itself. */
  summary?: string;
}

/** Read-only endpoints, safe to call repeatedly. */
const READ_PROBES: {
  method: string;
  path: string;
  call: () => Promise<unknown>;
  describe: (data: any) => string;
}[] = [
  {
    method: 'GET',
    path: '/api/health',
    call: getHealth,
    describe: (d) =>
      `status=${d.status}, cache=${d.mireye_cache_count}, ws_clients=${d.active_ws_clients}`,
  },
  {
    method: 'GET',
    path: '/api/state',
    call: getNetworkState,
    describe: (d: NetworkStateResponse) =>
      `candidates=${d.candidates?.length ?? 0}, frontier=${d.frontier?.length ?? 0}, ` +
      `warehouses=${d.graph?.warehouses?.length ?? 0}, customers=${d.graph?.customers?.length ?? 0}, ` +
      `trace=${d.trace_events?.length ?? 0}`,
  },
  {
    method: 'GET',
    path: '/api/provenance-trace',
    call: getProvenanceTrace,
    describe: (d) => `call_count=${d.call_count}, returned=${d.history?.length ?? 0}`,
  },
  {
    method: 'GET',
    path: '/api/data-source',
    call: getDataSource,
    describe: (d: DataSource) =>
      `live=${d.live_values}, simulated=${d.simulated_values}, key=${d.api_key_configured}`,
  },
  {
    method: 'GET',
    path: '/api/region',
    call: getRegion,
    describe: (d) =>
      `region=${d.region_name}, sites=${d.candidate_warehouses?.length ?? 0}, ` +
      `customers=${d.customers?.length ?? 0}, hazards=${d.hazard_zones?.length ?? 0}`,
  },
  {
    method: 'GET',
    path: '/api/scenarios',
    call: getScenarios,
    describe: (d) => `ready=${d.ready}, scenarios=${d.scenarios?.length ?? 0}`,
  },
];

/** Endpoints that mutate server state — listed, but only run on request. */
const WRITE_ENDPOINTS = [
  { method: 'POST', path: '/api/analyze', note: 'Dispatched by Setup.' },
  { method: 'POST', path: '/api/optimize', note: 'Dispatched by Candidates.' },
  { method: 'POST', path: '/api/run', note: 'Whole pipeline in one call; not used by the app.' },
  { method: 'POST', path: '/api/disrupt', note: 'Dispatched by Stress test.' },
  { method: 'POST', path: '/api/recover', note: 'Dispatched by the recovery button.' },
  { method: 'POST', path: '/api/restore', note: 'Dispatched by "run another scenario".' },
  { method: 'POST', path: '/api/switch-solution', note: 'Dispatched by the frontier chart.' },
  { method: 'POST', path: '/api/ask', note: 'Dispatched from the Ask panel.' },
  { method: 'POST', path: '/api/evaluate-sites', note: 'Dispatched by standalone site screening.' },
  { method: 'WS', path: '/ws/trace', note: 'Held open by the app while it runs.' },
];

export interface BackendPanelProps {
  connection: ConnectionStatus;
  traceCount: number;
  state: NetworkStateResponse | null;
}

export const BackendPanel: React.FC<BackendPanelProps> = ({ connection, traceCount, state }) => {
  const [probes, setProbes] = useState<ProbeResult[]>(
    READ_PROBES.map((p) => ({ method: p.method, path: p.path, status: 'idle' }))
  );
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState<Date | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [dataSource, setDataSource] = useState<DataSource | null>(null);
  const [resetting, setResetting] = useState(false);
  const [resetNote, setResetNote] = useState<string | null>(null);

  const wipeEverything = useCallback(async () => {
    setResetting(true);
    setResetNote(null);
    try {
      const res = await resetBackend();
      // Clear anything this browser is holding as well, so nothing survives.
      let localCleared = 0;
      try {
        for (const key of Object.keys(localStorage)) {
          if (key.startsWith('optiflow-')) {
            localStorage.removeItem(key);
            localCleared += 1;
          }
        }
        sessionStorage.clear();
      } catch {
        /* storage unavailable */
      }
      setResetNote(
        `Cleared ${res.removed.memory_entries} cached values, ${res.removed.call_history} call records ` +
          `and ${localCleared} browser keys. Reload to start clean.`
      );
      setDataSource(await getDataSource());
    } catch (err) {
      setResetNote(err instanceof Error ? err.message : 'Reset failed.');
    } finally {
      setResetting(false);
    }
  }, []);

  const runProbes = useCallback(async () => {
    setRunning(true);
    setProbes(READ_PROBES.map((p) => ({ method: p.method, path: p.path, status: 'running' })));

    const results: ProbeResult[] = [];
    for (const probe of READ_PROBES) {
      const started = performance.now();
      try {
        const data = await probe.call();
        results.push({
          method: probe.method,
          path: probe.path,
          status: 'ok',
          httpStatus: 200,
          ms: Math.round(performance.now() - started),
          bytes: new Blob([JSON.stringify(data)]).size,
          summary: probe.describe(data),
        });
      } catch (err) {
        results.push({
          method: probe.method,
          path: probe.path,
          status: 'fail',
          httpStatus: err instanceof ApiError ? err.status : undefined,
          ms: Math.round(performance.now() - started),
          error: err instanceof Error ? err.message : String(err),
        });
      }
      setProbes([...results, ...READ_PROBES.slice(results.length).map((p) => ({
        method: p.method,
        path: p.path,
        status: 'running' as const,
      }))]);
    }

    try {
      setDataSource(await getDataSource());
    } catch {
      /* the probe list already reports this endpoint failing */
    }

    setLastRun(new Date());
    setRunning(false);
  }, []);

  useEffect(() => {
    runProbes();
  }, [runProbes]);

  const allOk = probes.every((p) => p.status === 'ok');
  const anyFail = probes.some((p) => p.status === 'fail');

  return (
    <div className="space-y-5">
      <DataSourceBanner data={dataSource} />

      <Card
        className={cn(
          'border-l-[3px]',
          anyFail ? 'border-l-danger' : allOk ? 'border-l-pass' : 'border-l-line'
        )}
      >
        <CardHeader
          title="Connection"
          subtitle={
            <>
              Requests go to{' '}
              <span className="num font-mono text-ink">{API_BASE || window.location.origin}</span>
              {!API_BASE && ' (same origin, proxied to the backend)'}.
            </>
          }
          action={
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={runProbes} disabled={running}>
                <RefreshCw className={cn('h-3.5 w-3.5', running && 'animate-spin')} />
                Re-test
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={wipeEverything}
                loading={resetting}
                title="Clear every cached value, the call log, the network state and this browser's stored data"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear all data
              </Button>
            </div>
          }
        />

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <StatusTile
            label="HTTP endpoints"
            value={anyFail ? 'Failing' : allOk ? 'Reachable' : 'Testing'}
            tone={anyFail ? 'danger' : allOk ? 'pass' : 'neutral'}
          />
          <StatusTile
            label="Trace socket"
            value={connection === 'open' ? 'Connected' : connection === 'connecting' ? 'Connecting' : 'Disconnected'}
            tone={connection === 'open' ? 'pass' : connection === 'connecting' ? 'warn' : 'danger'}
          />
          <StatusTile label="Events received" value={num(traceCount)} tone="neutral" />
        </div>

        {resetNote && (
          <p className="mt-3 rounded-lg border border-line bg-sunken px-3 py-2 text-2xs leading-relaxed text-muted">
            {resetNote}
          </p>
        )}

        {lastRun && (
          <p className="num mt-3 font-mono text-2xs text-faint">
            last tested {lastRun.toLocaleTimeString('en-US', { hour12: false })}
          </p>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card flush>
          <div className="border-b border-line px-5 py-3.5">
            <CardHeader title="Read endpoints" subtitle="Called live when this tab opens." />
          </div>
          <ul className="divide-y divide-line">
            {probes.map((p) => (
              <li key={p.path} className="px-5 py-3.5">
                <div className="flex items-center gap-2.5">
                  <StatusIcon status={p.status} />
                  <span className="num font-mono text-2xs text-muted">{p.method}</span>
                  <span className="num min-w-0 flex-1 truncate font-mono text-xs text-ink">
                    {p.path}
                  </span>
                  {p.ms != null && (
                    <span className="num shrink-0 font-mono text-2xs text-faint">{p.ms}ms</span>
                  )}
                  {p.bytes != null && (
                    <span className="num shrink-0 font-mono text-2xs text-faint">
                      {formatBytes(p.bytes)}
                    </span>
                  )}
                </div>
                {p.summary && (
                  <p className="num mt-1.5 pl-7 font-mono text-2xs leading-relaxed text-muted">
                    {p.summary}
                  </p>
                )}
                {p.error && (
                  <p className="mt-1.5 pl-7 text-2xs leading-relaxed text-danger">
                    {p.httpStatus ? `${p.httpStatus} — ` : ''}
                    {p.error}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </Card>

        <Card flush>
          <div className="border-b border-line px-5 py-3.5">
            <CardHeader
              title="Write endpoints"
              subtitle="These change server state, so they are exercised by the app rather than probed here."
            />
          </div>
          <ul className="divide-y divide-line">
            {WRITE_ENDPOINTS.map((e) => (
              <li key={e.path} className="flex items-center gap-2.5 px-5 py-3.5">
                <Play className="h-3 w-3 shrink-0 text-faint" />
                <span className="num font-mono text-2xs text-muted">{e.method}</span>
                <span className="num min-w-0 flex-1 truncate font-mono text-xs text-ink">
                  {e.path}
                </span>
                <span className="shrink-0 text-2xs text-faint">{e.note}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card flush>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          <CardHeader
            title="Raw state"
            subtitle="The exact JSON body of the last /api/state response held by the app."
          />
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setShowRaw((v) => !v)}>
              {showRaw ? 'Hide' : 'Show'}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigator.clipboard?.writeText(JSON.stringify(state, null, 2))}
              disabled={!state}
            >
              Copy
            </Button>
          </div>
        </div>
        {showRaw ? (
          <pre className="num max-h-[32rem] overflow-auto px-5 py-4 font-mono text-2xs leading-relaxed text-muted">
            {state ? JSON.stringify(state, null, 2) : 'No state loaded.'}
          </pre>
        ) : (
          <div className="grid gap-3 px-5 py-4 sm:grid-cols-3 lg:grid-cols-6">
            <KeyCount label="candidates" value={state?.candidates?.length ?? 0} />
            <KeyCount label="frontier" value={state?.frontier?.length ?? 0} />
            <KeyCount label="warehouses" value={state?.graph?.warehouses?.length ?? 0} />
            <KeyCount label="customers" value={state?.graph?.customers?.length ?? 0} />
            <KeyCount label="edges" value={state?.graph?.edges?.length ?? 0} />
            <KeyCount label="disruption_log" value={state?.disruption_log?.length ?? 0} />
          </div>
        )}
      </Card>
    </div>
  );
};

/* ---------------------------------------------------------------- pieces */

const StatusIcon: React.FC<{ status: ProbeResult['status'] }> = ({ status }) => {
  if (status === 'running') return <Spinner className="h-3.5 w-3.5 shrink-0 text-accent" />;
  if (status === 'ok')
    return (
      <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-pass text-white">
        <Check className="h-2 w-2" strokeWidth={4} />
      </span>
    );
  if (status === 'fail')
    return (
      <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-danger text-white">
        <X className="h-2 w-2" strokeWidth={4} />
      </span>
    );
  return <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-line" />;
};

const StatusTile: React.FC<{
  label: string;
  value: string;
  tone: 'pass' | 'warn' | 'danger' | 'neutral';
}> = ({ label, value, tone }) => (
  <div className="rounded-lg border border-line bg-sunken px-3.5 py-3">
    <div className="text-2xs uppercase tracking-[0.06em] text-faint">{label}</div>
    <div
      className={cn(
        'num mt-1 font-display text-lg font-medium leading-none',
        tone === 'pass'
          ? 'text-pass'
          : tone === 'warn'
            ? 'text-warn'
            : tone === 'danger'
              ? 'text-danger'
              : 'text-ink'
      )}
    >
      {value}
    </div>
  </div>
);

const KeyCount: React.FC<{ label: string; value: number }> = ({ label, value }) => (
  <div>
    <div className="num font-display text-xl font-medium leading-none text-ink">{value}</div>
    <div className="num mt-1 font-mono text-2xs text-faint">{label}</div>
  </div>
);

const formatBytes = (b: number) =>
  b >= 1_048_576 ? `${(b / 1_048_576).toFixed(1)}MB` : b >= 1024 ? `${Math.round(b / 1024)}KB` : `${b}B`;
