import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  analyzeNetwork,
  getDataSource,
  getHealth,
  getNetworkState,
  getRegion,
  getScenarios,
  optimizeNetwork,
  recoverNetwork,
  resetBackend,
  restoreNetwork,
  switchSolution,
  triggerDisruption,
} from '../services/api';
import { traceSocket, type ConnectionStatus } from '../services/websocket';
import type {
  AgentTraceEvent,
  DataSource,
  NetworkStateResponse,
  RegionInfo,
  RunParams,
  ScenarioDef,
} from '../types';
import { hasResults } from './domain';

/** Where the person is in the guided workflow. */
export type Stage =
  | 'setup'
  | 'analyze'
  | 'candidates'
  | 'optimize'
  | 'stress'
  | 'recovery'
  | 'insights';

export const STAGE_ORDER: Stage[] = [
  'setup',
  'analyze',
  'candidates',
  'optimize',
  'stress',
  'recovery',
  'insights',
];

/** Connection to the backend, independent of where the workflow stands. */
export type Phase = 'booting' | 'ready' | 'offline';

/** A long-running call the backend is working through right now. */
export type Busy = null | 'analyzing' | 'optimizing' | 'disrupting' | 'recovering' | 'restoring';

const MAX_TRACE = 600;

export interface OptiFlowStore {
  phase: Phase;
  stage: Stage;
  state: NetworkStateResponse | null;
  region: RegionInfo | null;
  scenarios: ScenarioDef[];
  trace: AgentTraceEvent[];
  connection: ConnectionStatus;
  /** Live-vs-simulated accounting for everything served so far. */
  dataSource: DataSource | null;
  error: string | null;
  busy: Busy;
  lastRunParams: Partial<RunParams> | null;
  resetting: boolean;
  /** True while a switch to another design on the frontier is in flight. */
  switching: boolean;
  /** Which stages the current backend state actually supports opening. */
  reachable: Record<Stage, boolean>;

  goTo: (stage: Stage) => void;
  /** Clears the workflow position back to a blank setup form. */
  startNew: () => void;

  analyze: (params: Partial<RunParams>) => Promise<void>;
  optimize: () => Promise<void>;
  disrupt: (scenario: string, params?: Record<string, unknown>) => Promise<void>;
  recover: () => Promise<void>;
  restore: () => Promise<void>;
  selectSolution: (solutionId: string) => Promise<void>;
  refresh: () => Promise<NetworkStateResponse | null>;
  refreshScenarios: () => Promise<void>;
  resetAll: () => Promise<string>;
  dismissError: () => void;
}

export function useOptiFlow(): OptiFlowStore {
  const [phase, setPhase] = useState<Phase>('booting');
  const [stage, setStage] = useState<Stage>('setup');
  const [state, setState] = useState<NetworkStateResponse | null>(null);
  const [region, setRegion] = useState<RegionInfo | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioDef[]>([]);
  const [trace, setTrace] = useState<AgentTraceEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionStatus>('closed');
  const [dataSource, setDataSource] = useState<DataSource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [lastRunParams, setLastRunParams] = useState<Partial<RunParams> | null>(null);
  const [resetting, setResetting] = useState(false);
  const [switching, setSwitching] = useState(false);

  // Read inside socket callbacks and the polling fallback, which are
  // registered once and would otherwise close over a stale value.
  const busyRef = useRef(busy);
  busyRef.current = busy;

  const refresh = useCallback(async (): Promise<NetworkStateResponse | null> => {
    getDataSource()
      .then(setDataSource)
      .catch(() => undefined);
    try {
      const data = await getNetworkState();
      setState(data);
      if (data.trace_events?.length) setTrace((prev) => mergeTrace(prev, data.trace_events));
      return data;
    } catch (err) {
      if (err instanceof ApiError && err.unreachable) setPhase('offline');
      throw err;
    }
  }, []);

  const refreshScenarios = useCallback(async () => {
    try {
      const res = await getScenarios();
      setScenarios(res.scenarios);
    } catch {
      /* the stress-test screen falls back to an explanation */
    }
  }, []);

  /* ------------------------------------------------------------- bootstrap */

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const health = await getHealth();
        if (health.data_source) setDataSource(health.data_source);
        const data = await getNetworkState();
        if (cancelled) return;
        setState(data);
        setTrace(data.trace_events ?? []);
        setPhase('ready');
        setStage(resumeStage(data));
        if (data.stage === 'analyzing') setBusy('analyzing');
        else if (data.stage === 'optimizing') setBusy('optimizing');
        else if (data.stage === 'recovering') setBusy('recovering');
      } catch (err) {
        if (cancelled) return;
        setPhase('offline');
        setError(err instanceof Error ? err.message : 'Could not reach the OptiFlow API.');
      }
    })();

    getRegion()
      .then((r) => !cancelled && setRegion(r))
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, []);

  /* ------------------------------------------------------- socket wiring */

  useEffect(() => {
    traceSocket.connect();

    const offStatus = traceSocket.onStatus(setConnection);

    const offTrace = traceSocket.onTrace((event) => {
      setTrace((prev) => {
        const next = prev.some((e) => e.event_id === event.event_id) ? prev : [...prev, event];
        return next.length > MAX_TRACE ? next.slice(next.length - MAX_TRACE) : next;
      });
    });

    const offSignal = traceSocket.onSignal(async (signal) => {
      if (signal.type === 'pipeline_error') {
        setError(String(signal.error ?? 'The pipeline failed.'));
        setBusy(null);
        // Back to the screen that can fix it.
        setStage(signal.phase === 'optimize' ? 'candidates' : 'setup');
        return;
      }

      if (signal.type === 'analysis_complete') {
        const data = await refresh().catch(() => null);
        setBusy(null);
        if (data?.graph) setStage('candidates');
        return;
      }

      if (signal.type === 'pipeline_complete') {
        const data = await refresh().catch(() => null);
        setBusy(null);
        refreshScenarios();
        if (data && hasResults(data)) setStage('optimize');
        else if (data) setStage('candidates');
        return;
      }

      if (signal.type === 'disruption_applied') {
        await refresh().catch(() => null);
        setBusy(null);
        setStage('stress');
        return;
      }

      if (signal.type === 'disruption_resolved') {
        await refresh().catch(() => null);
        setBusy(null);
        setStage('recovery');
        return;
      }

      if (signal.type === 'network_restored') {
        await refresh().catch(() => null);
        setBusy(null);
        refreshScenarios();
        setStage('stress');
        return;
      }

      if (signal.type === 'solution_switched') {
        await refresh().catch(() => null);
      }
    });

    return () => {
      offStatus();
      offTrace();
      offSignal();
    };
  }, [refresh, refreshScenarios]);

  /* ---------------------------------------------------------- safety net */

  // If the socket is down, poll while the backend is working so the UI still moves.
  useEffect(() => {
    if (!busy || connection === 'open') return;
    const id = window.setInterval(async () => {
      try {
        const data = await refresh();
        if (!data) return;
        if (busyRef.current === 'analyzing' && data.graph && data.stage !== 'analyzing') {
          setBusy(null);
          setStage(hasResults(data) ? 'optimize' : 'candidates');
        } else if (busyRef.current === 'optimizing' && data.stage !== 'optimizing') {
          setBusy(null);
          setStage(hasResults(data) ? 'optimize' : 'candidates');
        } else if (busyRef.current === 'recovering' && data.recovery_report) {
          setBusy(null);
          setStage('recovery');
        } else if (busyRef.current === 'disrupting' && data.impact_report) {
          setBusy(null);
          setStage('stress');
        }
      } catch {
        /* keep polling */
      }
    }, 4000);
    return () => window.clearInterval(id);
  }, [busy, connection, refresh]);

  // The scenario catalogue is built from the live graph, so it is re-read
  // whenever the network underneath it changes.
  useEffect(() => {
    if (state?.graph && (state.frontier?.length ?? 0) > 0) refreshScenarios();
  }, [state?.graph, state?.frontier?.length, refreshScenarios]);

  /* ------------------------------------------------------------- actions */

  const analyze = useCallback(async (params: Partial<RunParams>) => {
    setError(null);
    setLastRunParams(params);
    traceSocket.resetHistory();
    setTrace([]);
    setBusy('analyzing');
    setStage('analyze');
    try {
      await analyzeNetwork(params);
    } catch (err) {
      setBusy(null);
      setStage('setup');
      setError(err instanceof Error ? err.message : 'Could not start the analysis.');
    }
  }, []);

  const optimize = useCallback(async () => {
    setError(null);
    setBusy('optimizing');
    setStage('optimize');
    try {
      await optimizeNetwork();
    } catch (err) {
      setBusy(null);
      setStage('candidates');
      setError(err instanceof Error ? err.message : 'Could not start the optimisation.');
    }
  }, []);

  const disrupt = useCallback(
    async (scenario: string, params?: Record<string, unknown>) => {
      setError(null);
      setBusy('disrupting');
      try {
        await triggerDisruption(scenario, params);
        await refresh();
        setStage('stress');
      } catch (err) {
        setError(err instanceof Error ? err.message : 'The disruption simulation failed.');
      } finally {
        setBusy(null);
      }
    },
    [refresh]
  );

  const recover = useCallback(async () => {
    setError(null);
    setBusy('recovering');
    setStage('recovery');
    try {
      await recoverNetwork();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The recovery re-solve failed.');
      setStage('stress');
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  const restore = useCallback(async () => {
    setError(null);
    setBusy('restoring');
    try {
      await restoreNetwork();
      await refresh();
      await refreshScenarios();
      setStage('stress');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not restore the network.');
    } finally {
      setBusy(null);
    }
  }, [refresh, refreshScenarios]);

  const selectSolution = useCallback(
    async (solutionId: string) => {
      const previousId = state?.active_solution_id;
      // Optimistic: repaint against the new design immediately, then reconcile.
      setState((prev) => (prev ? { ...prev, active_solution_id: solutionId } : prev));
      setSwitching(true);
      try {
        await switchSolution(solutionId);
        await refresh();
      } catch (err) {
        setState((prev) =>
          prev ? { ...prev, active_solution_id: previousId ?? prev.active_solution_id } : prev
        );
        // A 404 means the frontier was replaced by a newer run while this plan
        // was on screen, so the id no longer exists. Refreshing fixes it.
        if (err instanceof ApiError && err.status === 404) {
          setError(
            'That design is no longer on the frontier — a newer run replaced it. ' +
              'The list has been refreshed.'
          );
        } else {
          setError(err instanceof Error ? err.message : 'Could not switch designs.');
        }
        await refresh().catch(() => undefined);
      } finally {
        setSwitching(false);
      }
    },
    [refresh, state?.active_solution_id]
  );

  const resetAll = useCallback(async (): Promise<string> => {
    setResetting(true);
    try {
      const res = await resetBackend();
      let localCleared = 0;
      try {
        for (const key of Object.keys(localStorage)) {
          if (key.startsWith('optiflow-') && key !== 'optiflow-theme') {
            localStorage.removeItem(key);
            localCleared += 1;
          }
        }
        sessionStorage.clear();
      } catch {
        /* storage unavailable */
      }
      traceSocket.resetHistory();
      setTrace([]);
      setLastRunParams(null);
      setState(null);
      setScenarios([]);
      setDataSource(await getDataSource().catch(() => null));
      setStage('setup');
      return (
        `Cleared ${res.removed.memory_entries} cached values, ` +
        `${res.removed.call_history} call records and ${localCleared} browser keys.`
      );
    } finally {
      setResetting(false);
    }
  }, []);

  const goTo = useCallback((next: Stage) => {
    setError(null);
    setStage(next);
  }, []);

  const startNew = useCallback(() => {
    setError(null);
    setStage('setup');
  }, []);

  const dismissError = useCallback(() => setError(null), []);

  const reachable = useMemo(() => stageReach(state, busy), [state, busy]);

  return {
    phase,
    stage,
    state,
    region,
    scenarios,
    trace,
    connection,
    dataSource,
    error,
    busy,
    lastRunParams,
    resetting,
    switching,
    reachable,
    goTo,
    startNew,
    analyze,
    optimize,
    disrupt,
    recover,
    restore,
    selectSolution,
    refresh,
    refreshScenarios,
    resetAll,
    dismissError,
  };
}

/* --------------------------------------------------------------- helpers */

/** Which stage a freshly loaded page should open at, given what the server holds. */
export function resumeStage(data: NetworkStateResponse | null): Stage {
  if (!data) return 'setup';
  if (data.stage === 'analyzing') return 'analyze';
  if (data.stage === 'optimizing') return 'optimize';
  if (data.recovery_report) return 'recovery';
  if (data.impact_report) return 'stress';
  if (hasResults(data)) return 'optimize';
  if (data.graph) return 'candidates';
  return 'setup';
}

/** A stage opens only when the backend holds what that screen needs to show. */
export function stageReach(
  data: NetworkStateResponse | null,
  busy: Busy
): Record<Stage, boolean> {
  const solved = hasResults(data);
  return {
    setup: true,
    analyze: busy === 'analyzing' || !!data?.candidates?.length,
    candidates: !!data?.candidates?.length && !!data?.graph,
    optimize: solved || busy === 'optimizing',
    stress: solved,
    recovery: !!data?.impact_report || !!data?.recovery_report,
    insights: solved,
  };
}

function mergeTrace(prev: AgentTraceEvent[], incoming: AgentTraceEvent[]): AgentTraceEvent[] {
  const seen = new Set(prev.map((e) => e.event_id));
  const merged = [...prev];
  for (const e of incoming) {
    if (!seen.has(e.event_id)) {
      seen.add(e.event_id);
      merged.push(e);
    }
  }
  return merged.length > MAX_TRACE ? merged.slice(merged.length - MAX_TRACE) : merged;
}
