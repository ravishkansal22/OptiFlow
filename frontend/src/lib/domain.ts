import type {
  AgentTraceEvent,
  Candidate,
  LogisticsGraph,
  NetworkSolution,
  NetworkStateResponse,
} from '../types';

/* ---------------------------------------------------------------------------
 * Everything here is derived from what the backend actually returns.
 * No thresholds, copy or catalogues are duplicated from the Python agents --
 * if a value is shown in the UI, it came over the wire.
 * ------------------------------------------------------------------------- */

/* ---------- Disruption scenarios ---------- */

/**
 * These four ids are an API contract, not content: agents/disaster_agent.py
 * branches on the `scenario_type` string. Anything unrecognised falls through
 * to its single-facility outage branch. Titles and descriptions are NOT
 * defined here -- the backend returns the real ones on the Disruption object.
 */
export const SCENARIO_IDS = [
  'flood_green_river',
  'road_closure_corridor',
  'surge_demand',
  'warehouse_failure',
] as const;

export type ScenarioId = (typeof SCENARIO_IDS)[number];

/** "flood_green_river" -> "Flood green river". Derived, not authored. */
export const scenarioLabel = (id: string) => {
  const words = id.replace(/[_-]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/* ---------- Pipeline progress, derived from the live trace ---------- */

export interface StageProgress {
  agent: string;
  /** Latest status seen for this agent. */
  status: AgentTraceEvent['status'];
  /** Most recent message, shown as the stage's current activity. */
  message: string;
  events: number;
  done: boolean;
  failed: boolean;
}

/**
 * Builds the stage list from the trace stream itself, in the order agents
 * first report. Nothing about the workflow shape is assumed up front, so this
 * stays correct if the backend adds, removes or reorders agents.
 */
export function deriveStages(trace: AgentTraceEvent[]): StageProgress[] {
  const byAgent = new Map<string, StageProgress>();

  for (const e of trace) {
    const cur = byAgent.get(e.agent_name);
    if (!cur) {
      byAgent.set(e.agent_name, {
        agent: e.agent_name,
        status: e.status,
        message: e.message,
        events: 1,
        done: e.status === 'complete',
        failed: e.status === 'error',
      });
      continue;
    }
    cur.status = e.status;
    cur.message = e.message;
    cur.events += 1;
    if (e.status === 'complete') cur.done = true;
    if (e.status === 'error') cur.failed = true;
  }

  const stages = [...byAgent.values()];
  // Every agent before the last one to report has necessarily finished.
  for (let i = 0; i < stages.length - 1; i++) {
    if (!stages[i].failed) stages[i].done = true;
  }
  return stages;
}

/* ---------- Rejection reasons ---------- */

/**
 * The agents format every rejection as "<category>: <measurement>" or
 * "<category> (<measurement>)". Splitting on the first ':' or '(' recovers the
 * category without hardcoding what the categories are.
 */
export const reasonCategory = (reason: string) => {
  const cut = reason.split(/[:(]/)[0].trim();
  return cut || reason.trim();
};

/* ---------- Selectors over NetworkStateResponse ---------- */

export const activeSolution = (state: NetworkStateResponse | null): NetworkSolution | null => {
  if (!state?.frontier?.length) return null;
  return state.frontier.find((s) => s.solution_id === state.active_solution_id) ?? state.frontier[0];
};

export const baselineSolution = (frontier: NetworkSolution[]): NetworkSolution | null =>
  frontier.find((s) => s.is_baseline_cost_only) ?? frontier[0] ?? null;

/**
 * The design being recommended, which is not always the one running right now:
 * after a recovery the active solution describes the repaired network, while
 * the recommendation is still the design the plan started from.
 */
export const recommendedSolution = (
  state: NetworkStateResponse | null
): NetworkSolution | null => {
  if (!state?.frontier?.length) return null;
  const pre = state.pre_disruption_solution_id
    ? state.frontier.find((s) => s.solution_id === state.pre_disruption_solution_id)
    : undefined;
  return pre ?? activeSolution(state);
};

/** True once the backend has produced a solvable network we can render. */
export const hasResults = (state: NetworkStateResponse | null): boolean =>
  !!state?.graph && (state?.frontier?.length ?? 0) > 0;

export interface ScreeningSummary {
  total: number;
  passed: number;
  rejected: number;
  selected: number;
  passRate: number;
  /** Rejection categories the backend actually reported, most common first. */
  reasonCounts: { label: string; count: number }[];
}

export function summarizeScreening(
  candidates: Candidate[],
  solution: NetworkSolution | null
): ScreeningSummary {
  const passed = candidates.filter((c) => c.passed_screening).length;
  const counts = new Map<string, number>();

  for (const c of candidates) {
    for (const reason of c.rejection_reasons) {
      const label = reasonCategory(reason);
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
  }

  return {
    total: candidates.length,
    passed,
    rejected: candidates.length - passed,
    selected: solution?.selected_warehouse_ids.length ?? 0,
    passRate: candidates.length ? (passed / candidates.length) * 100 : 0,
    reasonCounts: [...counts.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count),
  };
}

export interface CandidateVerdict {
  candidate: Candidate;
  /** 'selected' = opened in the active plan, 'eligible' = passed but not opened. */
  outcome: 'selected' | 'eligible' | 'rejected';
  warehouseId: string;
  demandServed: number;
  customerCount: number;
}

export function buildVerdicts(
  candidates: Candidate[],
  graph: LogisticsGraph | null,
  solution: NetworkSolution | null
): CandidateVerdict[] {
  const selected = new Set(solution?.selected_warehouse_ids ?? []);
  const demandByWh = new Map<string, { units: number; count: number }>();

  if (graph && solution) {
    for (const cust of graph.customers) {
      const wid = solution.customer_assignments[cust.id];
      if (!wid) continue;
      const cur = demandByWh.get(wid) ?? { units: 0, count: 0 };
      cur.units += cust.demand_units;
      cur.count += 1;
      demandByWh.set(wid, cur);
    }
  }

  // Warehouse nodes carry the candidate id they came from; fall back to the id itself.
  const whIdForCandidate = new Map<string, string>();
  graph?.warehouses.forEach((w) => whIdForCandidate.set(w.candidate_id || w.id, w.id));

  const rank = { selected: 0, eligible: 1, rejected: 2 } as const;

  return candidates
    .map((candidate) => {
      const warehouseId = whIdForCandidate.get(candidate.id) ?? candidate.id;
      const load = demandByWh.get(warehouseId) ?? { units: 0, count: 0 };
      const outcome: CandidateVerdict['outcome'] = !candidate.passed_screening
        ? 'rejected'
        : selected.has(warehouseId)
          ? 'selected'
          : 'eligible';
      return { candidate, outcome, warehouseId, demandServed: load.units, customerCount: load.count };
    })
    .sort((a, b) => {
      if (rank[a.outcome] !== rank[b.outcome]) return rank[a.outcome] - rank[b.outcome];
      return a.candidate.composite_risk - b.candidate.composite_risk;
    });
}

/** Total demand across the network, used for coverage percentages. */
export const totalDemand = (graph: LogisticsGraph | null) =>
  graph?.customers.reduce((sum, c) => sum + c.demand_units, 0) ?? 0;

/**
 * Relative shading for a 0-1 risk score. Scaled against the highest score in
 * the current run rather than against invented bands, so it stays a comparison
 * between real sites instead of a judgement the backend never made.
 */
export const riskShade = (value: number, max: number) =>
  max <= 0 ? 0 : Math.min(1, Math.max(0, value / max));

export interface HubFeasibility {
  /** Smallest hub count whose combined capacity covers total demand, if any. */
  minHubs: number | null;
  /** Capacity reachable at a given hub count. */
  capacityAt: (k: number) => number;
  totalDemand: number;
  siteCount: number;
}

/**
 * Capacity is a necessary condition for the MILP, not a sufficient one: supply,
 * SLA and assignment constraints can still fail. Use this to rule counts OUT,
 * never to promise one will work.
 */
export function hubFeasibility(graph: LogisticsGraph | null): HubFeasibility {
  const capacities = (graph?.warehouses ?? [])
    .filter((w) => w.status === 'active')
    .map((w) => w.capacity_units)
    .sort((a, b) => b - a);

  const demand = totalDemand(graph);
  const capacityAt = (k: number) =>
    capacities.slice(0, Math.max(0, k)).reduce((sum, c) => sum + c, 0);

  let minHubs: number | null = null;
  for (let k = 1; k <= capacities.length; k++) {
    if (capacityAt(k) >= demand) {
      minHubs = k;
      break;
    }
  }

  return { minHubs, capacityAt, totalDemand: demand, siteCount: capacities.length };
}

/* ---------- Coordinate parsing for user-supplied sites ---------- */

export interface CoordRow {
  name?: string;
  lat: number;
  lon: number;
  capacity_units?: number;
  fixed_cost?: number;
  /** Only read from files that name their columns; used for demand zones. */
  demand_units?: number;
  service_sla_minutes?: number;
  priority?: number;
  /** Used for supply origins. */
  unit_supply_cost?: number;
}

/**
 * Parses pasted coordinate lines. Accepts, per line:
 *   lat, lon
 *   name, lat, lon
 *   name, lat, lon, capacity, cost
 * Separators may be commas, tabs, or runs of spaces.
 * Returns valid rows plus the line numbers that could not be read.
 */
export function parseCoordinateLines(text: string): {
  valid: CoordRow[];
  invalidLines: number[];
} {
  const valid: CoordRow[] = [];
  const invalidLines: number[] = [];
  const isNum = (v: string) => v !== undefined && v !== '' && !Number.isNaN(Number(v));

  text.split(/\r?\n/).forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) return;

    const parts = trimmed.split(/\s*[,\t]\s*|\s{2,}/).filter(Boolean);
    let name: string | undefined;
    let rest = parts;

    if (parts.length && !isNum(parts[0])) {
      name = parts[0];
      rest = parts.slice(1);
    }

    if (rest.length < 2 || !isNum(rest[0]) || !isNum(rest[1])) {
      invalidLines.push(index + 1);
      return;
    }

    const lat = Number(rest[0]);
    const lon = Number(rest[1]);
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      invalidLines.push(index + 1);
      return;
    }

    const row: CoordRow = { lat, lon };
    if (name) row.name = name;
    if (isNum(rest[2])) row.capacity_units = Number(rest[2]);
    if (isNum(rest[3])) row.fixed_cost = Number(rest[3]);
    valid.push(row);
  });

  return { valid, invalidLines };
}

/* ---------- Coverage checks (Mireye v1 is US-only) ---------- */

/** Rough bounding boxes for the areas Mireye v1 covers. */
const US_BOXES: [number, number, number, number][] = [
  [24.4, -125.0, 49.4, -66.9], // contiguous states
  [51.0, -180.0, 71.6, -129.0], // Alaska
  [18.8, -160.6, 22.3, -154.7], // Hawaii
  [17.8, -67.4, 18.6, -65.2], // Puerto Rico
];

export const isInUSCoverage = (lat: number, lon: number) =>
  US_BOXES.some(([s, w, n, e]) => lat >= s && lat <= n && lon >= w && lon <= e);

export interface CoordIssue {
  kind: 'sign' | 'outside';
  message: string;
  /** Present for 'sign': the corrected pair. */
  fix?: { lat: number; lon: number };
}

/**
 * Mireye v1 answers for US coordinates only, so anything else is refused before
 * it reaches the API. The most common cause by far is a dropped minus sign on
 * longitude -- every US longitude is negative.
 */
export function checkCoordinate(lat: number, lon: number): CoordIssue | null {
  if (isInUSCoverage(lat, lon)) return null;

  if (lon > 0 && isInUSCoverage(lat, -lon)) {
    return {
      kind: 'sign',
      message: `Longitude looks like it is missing a minus sign — ${lon} should probably be ${-lon}.`,
      fix: { lat, lon: -lon },
    };
  }

  if (lat > 0 && lon < 0 && isInUSCoverage(lon, lat)) {
    return {
      kind: 'sign',
      message: `Latitude and longitude look swapped — try ${lon}, ${lat}.`,
      fix: { lat: lon, lon: lat },
    };
  }

  return {
    kind: 'outside',
    message: 'Outside Mireye coverage. The API answers for US coordinates only.',
  };
}

/* ---------- Reading coordinates out of an uploaded file ---------- */

const LAT_KEYS = ['lat', 'latitude', 'y'];
const LON_KEYS = ['lon', 'lng', 'long', 'longitude', 'x'];
const NAME_KEYS = ['name', 'site', 'site_name', 'label', 'title', 'warehouse'];
const CAP_KEYS = ['capacity', 'capacity_units', 'units', 'size'];
const COST_KEYS = ['cost', 'fixed_cost', 'fixed_operating_cost', 'annual_cost'];
const DEMAND_KEYS = ['demand', 'demand_units', 'volume', 'orders'];
const SLA_KEYS = ['sla', 'service_sla_minutes', 'sla_minutes', 'window', 'window_minutes'];
const PRIORITY_KEYS = ['priority', 'tier'];
const SUPPLY_COST_KEYS = ['unit_supply_cost', 'unit_cost', 'supply_cost'];

/** Columns beyond lat/lon that a named-column file may carry. */
function readExtras(record: Record<string, any>, row: CoordRow) {
  const demand = toNum(pick(record, DEMAND_KEYS));
  if (demand !== undefined) row.demand_units = demand;
  const sla = toNum(pick(record, SLA_KEYS));
  if (sla !== undefined) row.service_sla_minutes = sla;
  const priority = toNum(pick(record, PRIORITY_KEYS));
  if (priority !== undefined) row.priority = priority;
  const supplyCost = toNum(pick(record, SUPPLY_COST_KEYS));
  if (supplyCost !== undefined) row.unit_supply_cost = supplyCost;
}

const pick = (row: Record<string, any>, keys: string[]) => {
  for (const k of keys) {
    const hit = Object.keys(row).find((c) => c.trim().toLowerCase() === k);
    if (hit !== undefined && row[hit] !== '' && row[hit] != null) return row[hit];
  }
  return undefined;
};

const toNum = (v: any) => {
  const n = Number(String(v).trim());
  return Number.isFinite(n) ? n : undefined;
};

/** Splits a CSV line, honouring double-quoted fields. */
function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = '';
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else quoted = !quoted;
    } else if ((ch === ',' || ch === '\t' || ch === ';') && !quoted) {
      out.push(cur);
      cur = '';
    } else cur += ch;
  }
  out.push(cur);
  return out.map((c) => c.trim());
}

/**
 * Reads coordinates out of a pasted or uploaded file. Handles:
 *   - JSON: an array of objects, or {sites: [...]}
 *   - CSV/TSV with a header row naming latitude and longitude in any order
 *   - Plain lines, the same shapes the paste box accepts
 * Returns the rows it understood plus the 1-based lines it could not read.
 */
export function parseCoordinateFile(
  text: string,
  filename = ''
): { valid: CoordRow[]; invalidLines: number[] } {
  const trimmed = text.trim();
  if (!trimmed) return { valid: [], invalidLines: [] };

  const looksJson =
    filename.toLowerCase().endsWith('.json') || trimmed.startsWith('[') || trimmed.startsWith('{');

  if (looksJson) {
    try {
      const parsed = JSON.parse(trimmed);
      const rows: any[] = Array.isArray(parsed)
        ? parsed
        : Array.isArray(parsed?.sites)
          ? parsed.sites
          : Array.isArray(parsed?.warehouses)
            ? parsed.warehouses
            : [];
      const valid: CoordRow[] = [];
      const invalidLines: number[] = [];
      rows.forEach((r, i) => {
        const lat = toNum(pick(r, LAT_KEYS));
        const lon = toNum(pick(r, LON_KEYS));
        if (lat === undefined || lon === undefined || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
          invalidLines.push(i + 1);
          return;
        }
        const row: CoordRow = { lat, lon };
        const nm = pick(r, NAME_KEYS);
        if (nm) row.name = String(nm);
        const cap = toNum(pick(r, CAP_KEYS));
        if (cap !== undefined) row.capacity_units = cap;
        const cost = toNum(pick(r, COST_KEYS));
        if (cost !== undefined) row.fixed_cost = cost;
        readExtras(r, row);
        valid.push(row);
      });
      return { valid, invalidLines };
    } catch {
      return { valid: [], invalidLines: [1] };
    }
  }

  // Does the first non-empty line name its columns? If so, read by header.
  const lines = trimmed.split(/\r?\n/);
  const firstIdx = lines.findIndex((l) => l.trim() !== '');
  const header = firstIdx >= 0 ? splitCsvLine(lines[firstIdx]).map((h) => h.toLowerCase()) : [];
  const hasHeader =
    header.some((h) => LAT_KEYS.includes(h)) && header.some((h) => LON_KEYS.includes(h));

  if (!hasHeader) return parseCoordinateLines(trimmed);

  const valid: CoordRow[] = [];
  const invalidLines: number[] = [];
  lines.forEach((line, i) => {
    if (i <= firstIdx || !line.trim()) return;
    const cells = splitCsvLine(line);
    const rec: Record<string, string> = {};
    header.forEach((h, c) => (rec[h] = cells[c] ?? ''));

    const lat = toNum(pick(rec, LAT_KEYS));
    const lon = toNum(pick(rec, LON_KEYS));
    if (lat === undefined || lon === undefined || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      invalidLines.push(i + 1);
      return;
    }
    const row: CoordRow = { lat, lon };
    const nm = pick(rec, NAME_KEYS);
    if (nm) row.name = String(nm);
    const cap = toNum(pick(rec, CAP_KEYS));
    if (cap !== undefined) row.capacity_units = cap;
    const cost = toNum(pick(rec, COST_KEYS));
    if (cost !== undefined) row.fixed_cost = cost;
    readExtras(rec, row);
    valid.push(row);
  });

  return { valid, invalidLines };
}

/** Turns parsed rows back into the text the paste box shows. */
export const coordRowsToText = (rows: CoordRow[]) =>
  rows
    .map((r) =>
      [r.name, r.lat, r.lon, r.capacity_units, r.fixed_cost]
        .filter((v) => v !== undefined && v !== '')
        .join(', ')
    )
    .join('\n');
