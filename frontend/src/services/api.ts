import type {
  NetworkStateResponse,
  RegionInfo,
  ScenarioCatalogue,
  ImpactReport,
  RecoveryReport,
  NetworkSolution,
  NarratorAnswer,
  HealthResponse,
  MireyeCallRecord,
  RunParams,
  SiteInput,
  EvaluateSitesResponse,
  DataSource,
} from '../types';

/**
 * Empty base = same origin, which the Vite dev proxy and the nginx container
 * both forward to the FastAPI backend. Set VITE_API_URL to point elsewhere.
 */
export const API_BASE: string = (import.meta as any).env?.VITE_API_URL ?? '';

const UNREACHABLE_MESSAGE =
  'Cannot reach the OptiFlow API. Is the backend running on port 8000?';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
    /** True when the backend never answered, as opposed to answering with an error. */
    readonly unreachable = false
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
      ...init,
    });
  } catch {
    throw new ApiError(UNREACHABLE_MESSAGE, 0, undefined, true);
  }

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail);
    } catch {
      /* response had no JSON body */
    }

    // A dev/nginx proxy answers 5xx with no JSON body when the upstream is
    // down, which is indistinguishable from the backend being absent.
    if (!detail && res.status >= 500) {
      throw new ApiError(UNREACHABLE_MESSAGE, res.status, undefined, true);
    }

    throw new ApiError(detail || `${res.status} ${res.statusText}`, res.status, detail);
  }

  return res.json() as Promise<T>;
}

export const getHealth = () => request<HealthResponse>('/api/health');

export const getNetworkState = () => request<NetworkStateResponse>('/api/state');

export const runOptimization = (params: Partial<RunParams>) =>
  request<{ message: string }>('/api/run', { method: 'POST', body: JSON.stringify(params) });

/** Phase one: site screening, hazard scoring and the routed graph. */
export const analyzeNetwork = (params: Partial<RunParams>) =>
  request<{ message: string; candidate_count: number | null }>('/api/analyze', {
    method: 'POST',
    body: JSON.stringify(params),
  });

/** Phase two: the MILP, the NSGA-II frontier, the critic audit and the report. */
export const optimizeNetwork = () =>
  request<{ message: string }>('/api/optimize', { method: 'POST' });

/** What the server has loaded: bounds, suppliers, demand zones, hazards. */
export const getRegion = () => request<RegionInfo>('/api/region');

/** Disruption scenarios that can run against the network as it stands. */
export const getScenarios = () => request<ScenarioCatalogue>('/api/scenarios');

/**
 * Runs a scenario and measures the damage. Recovery is a separate call, so the
 * impact is visible before the network is repaired.
 */
export const triggerDisruption = (
  scenario_type: string,
  params?: Record<string, unknown>
) =>
  request<{
    message: string;
    active_solution_id: string;
    impact_report: ImpactReport | null;
    recovery_report: RecoveryReport | null;
  }>('/api/disrupt', {
    method: 'POST',
    body: JSON.stringify({ scenario_type, params: params ?? null }),
  });

/** Warm-started delta re-solve against the latest disruption. */
export const recoverNetwork = () =>
  request<{ message: string; active_solution_id: string; recovery_report: RecoveryReport | null }>(
    '/api/recover',
    { method: 'POST' }
  );

/** Puts the network back as it was before the first disruption. */
export const restoreNetwork = () =>
  request<{ message: string; active_solution_id: string }>('/api/restore', { method: 'POST' });

export const switchSolution = (solution_id: string) =>
  request<{ message: string; solution: NetworkSolution }>('/api/switch-solution', {
    method: 'POST',
    body: JSON.stringify({ solution_id }),
  });

export const askNarrator = (query: string) =>
  request<NarratorAnswer>('/api/ask', { method: 'POST', body: JSON.stringify({ query }) });

/**
 * Screens user-supplied coordinates and ranks them. Runs the same Site and Risk
 * agents the full pipeline uses. Roughly 3 geospatial lookups per site, so this
 * can take a few seconds per coordinate against a live key.
 */
export const evaluateSites = (sites: SiteInput[]) =>
  request<EvaluateSitesResponse>('/api/evaluate-sites', {
    method: 'POST',
    body: JSON.stringify({ sites }),
  });

/** How much of the data served so far actually came from the Mireye API. */
export const getDataSource = () => request<DataSource>('/api/data-source');

/** Clears every cached geospatial value, the call log and the network state. */
export const resetBackend = () =>
  request<{ message: string; removed: Record<string, number> }>('/api/reset', { method: 'POST' });

export const getProvenanceTrace = () =>
  request<{ call_count: number; history: MireyeCallRecord[] }>('/api/provenance-trace');
