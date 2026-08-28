/* ---------------------------------------------------------------------------
 * Derivations over what the backend returns, for the guided workflow screens.
 *
 * Everything here is arithmetic on values the agents produced: assignments,
 * routed edges, the frontier and the critic report. No thresholds, catalogues
 * or copy are duplicated from the Python side, and nothing is estimated.
 * ------------------------------------------------------------------------- */

import type {
  Candidate,
  CriticReport,
  InputSpec,
  LogisticsGraph,
  MetricSnapshot,
  NetworkSolution,
  NetworkStateResponse,
} from '../types';
import { baselineSolution, totalDemand } from './domain';

/* ---------- delivery time, read off the lanes the plan actually uses ------ */

const laneKey = (from: string, to: string) => `${from}->${to}`;

function laneIndex(graph: LogisticsGraph) {
  const map = new Map<string, { minutes: number; cost: number; status: string }>();
  for (const e of graph.edges) {
    map.set(laneKey(e.source_id, e.target_id), {
      minutes: e.travel_time_min,
      cost: e.transport_cost_usd,
      status: e.status,
    });
  }
  return map;
}

/**
 * Demand-weighted mean drive time across the lanes the active plan uses.
 * Null when no assignment has a routed lane behind it, rather than 0, so the
 * UI can say "not measured" instead of showing a number nobody computed.
 */
export function avgDeliveryMinutes(
  graph: LogisticsGraph | null,
  solution: NetworkSolution | null
): number | null {
  if (!graph || !solution) return null;
  const lanes = laneIndex(graph);
  let weighted = 0;
  let units = 0;

  for (const cust of graph.customers) {
    const wid = solution.customer_assignments[cust.id];
    if (!wid) continue;
    const lane = lanes.get(laneKey(wid, cust.id));
    if (!lane) continue;
    weighted += lane.minutes * cust.demand_units;
    units += cust.demand_units;
  }

  return units > 0 ? weighted / units : null;
}

/* ---------- candidate shortlist, as the Candidates screen shows it -------- */

export type CandidateStatus = 'selected' | 'eligible' | 'rejected';

export interface CandidateInsight {
  candidate: Candidate;
  /** The warehouse node built from this candidate, when it survived screening. */
  warehouseId: string | null;
  status: CandidateStatus;
  /** Demand zones this site can reach inside their own delivery window. */
  zonesInWindow: number;
  totalZones: number;
  /** Share of all demand reachable in-window from here, 0-1. */
  reachShare: number;
  /** Median drive time to the zones it can reach, in minutes. */
  medianMinutes: number | null;
  /** Only meaningful once a plan exists. */
  demandServed: number;
  customerCount: number;
}

/**
 * Accessibility is measured, not assumed: it counts the demand zones this site
 * can reach inside each zone own SLA using the routed edges the Route agent
 * built. Rejected sites never enter the graph, so they have no lanes and report
 * null rather than a made-up figure.
 */
export function buildCandidateInsights(
  candidates: Candidate[],
  graph: LogisticsGraph | null,
  solution: NetworkSolution | null
): CandidateInsight[] {
  const lanes = graph ? laneIndex(graph) : new Map();
  const selected = new Set(solution?.selected_warehouse_ids ?? []);
  const whForCandidate = new Map<string, string>();
  graph?.warehouses.forEach((w) => whForCandidate.set(w.candidate_id || w.id, w.id));

  const demandTotal = totalDemand(graph);
  const zones = graph?.customers ?? [];

  const load = new Map<string, { units: number; count: number }>();
  if (graph && solution) {
    for (const cust of graph.customers) {
      const wid = solution.customer_assignments[cust.id];
      if (!wid) continue;
      const cur = load.get(wid) ?? { units: 0, count: 0 };
      cur.units += cust.demand_units;
      cur.count += 1;
      load.set(wid, cur);
    }
  }

  const rank: Record<CandidateStatus, number> = { selected: 0, eligible: 1, rejected: 2 };

  return candidates
    .map((candidate) => {
      const warehouseId = whForCandidate.get(candidate.id) ?? null;
      const status: CandidateStatus = !candidate.passed_screening
        ? 'rejected'
        : warehouseId && selected.has(warehouseId)
          ? 'selected'
          : 'eligible';

      let inWindow = 0;
      let reachUnits = 0;
      const minutes: number[] = [];
      if (warehouseId) {
        for (const cust of zones) {
          const lane = lanes.get(laneKey(warehouseId, cust.id));
          if (!lane) continue;
          minutes.push(lane.minutes);
          if (lane.minutes <= cust.service_sla_minutes) {
            inWindow += 1;
            reachUnits += cust.demand_units;
          }
        }
      }
      minutes.sort((a, b) => a - b);

      const hit = load.get(warehouseId ?? '') ?? { units: 0, count: 0 };

      return {
        candidate,
        warehouseId,
        status,
        zonesInWindow: inWindow,
        totalZones: zones.length,
        reachShare: demandTotal > 0 ? reachUnits / demandTotal : 0,
        medianMinutes: minutes.length ? minutes[Math.floor(minutes.length / 2)] : null,
        demandServed: hit.units,
        customerCount: hit.count,
      };
    })
    .sort((a, b) => {
      if (rank[a.status] !== rank[b.status]) return rank[a.status] - rank[b.status];
      return b.candidate.suitability_score - a.candidate.suitability_score;
    });
}

/* ---------- before / after ------------------------------------------------ */

export interface Delta {
  before: number;
  after: number;
  change: number;
  /** True when the movement is an improvement for this measure. */
  better: boolean;
}

export const delta = (before: number, after: number, higherIsBetter = true): Delta => ({
  before,
  after,
  change: after - before,
  better: higherIsBetter ? after >= before : after <= before,
});

export interface SnapshotRow {
  key: string;
  label: string;
  format: 'pct' | 'minutes' | 'usd' | 'count';
  delta: Delta;
}

/** The measures both the impact and the recovery report carry. */
export function compareSnapshots(before: MetricSnapshot, after: MetricSnapshot): SnapshotRow[] {
  return [
    {
      key: 'demand',
      label: 'Demand served',
      format: 'pct',
      delta: delta(before.demand_served_pct, after.demand_served_pct, true),
    },
    {
      key: 'ontime',
      label: 'Arriving in the window',
      format: 'pct',
      delta: delta(before.on_time_pct, after.on_time_pct, true),
    },
    {
      key: 'time',
      label: 'Average delivery time',
      format: 'minutes',
      delta: delta(before.avg_delivery_minutes, after.avg_delivery_minutes, false),
    },
    {
      key: 'transport',
      label: 'Transport cost',
      format: 'usd',
      delta: delta(before.transport_cost_usd, after.transport_cost_usd, false),
    },
    {
      key: 'unserved',
      label: 'Zones cut off',
      format: 'count',
      delta: delta(before.customers_unserved, after.customers_unserved, false),
    },
    {
      key: 'partial',
      label: 'Zones part-supplied',
      format: 'count',
      delta: delta(before.customers_partial, after.customers_partial, false),
    },
    {
      key: 'hubs',
      label: 'Facilities shipping',
      format: 'count',
      delta: delta(before.active_warehouses, after.active_warehouses, true),
    },
  ];
}

/* ---------- verification, read off the critic report --------------------- */

export interface CheckItem {
  id: string;
  label: string;
  state: 'pass' | 'fail' | 'unknown';
  detail: string;
}

const matching = (items: string[], needle: string) =>
  items.filter((v) => v.toLowerCase().includes(needle));

/**
 * The Critic reports violations as text. Each check below reads the report
 * fields it owns and says what the report actually contains -- an absent
 * report is reported as unknown rather than quietly passing.
 */
export function verificationChecks(
  report: CriticReport | null,
  solution: NetworkSolution | null,
  inputs: InputSpec | null
): CheckItem[] {
  if (!report) {
    return [
      {
        id: 'audit',
        label: 'Critic audit',
        state: 'unknown',
        detail: 'The critic has not audited this plan yet.',
      },
    ];
  }

  const violations = report.constraint_violations;
  const capacity = matching(violations, 'capacity');
  const budget = matching(violations, 'budget');
  const delivery = matching(violations, 'delivery requirement');
  const assignment = violations.filter(
    (v) => v.toLowerCase().includes('unassigned') || v.toLowerCase().includes('closed facility')
  );
  const evidenceFlags = report.flags.filter((f) => !violations.includes(f));

  const checks: CheckItem[] = [
    {
      id: 'capacity',
      label: 'Capacity constraints satisfied',
      state: capacity.length ? 'fail' : 'pass',
      detail: capacity.length
        ? capacity.join(' · ')
        : 'No facility is assigned more demand than it can hold.',
    },
    {
      id: 'budget',
      label: 'Budget constraint satisfied',
      state: budget.length ? 'fail' : 'pass',
      detail: budget.length
        ? budget.join(' · ')
        : inputs && solution
          ? `Plan costs ${Math.round((solution.total_cost / inputs.budget_limit_usd) * 100)}% of the budget set for this run.`
          : 'Within the budget recorded for this run.',
    },
    {
      id: 'delivery',
      label: 'Delivery requirement satisfied',
      state: delivery.length ? 'fail' : inputs && inputs.min_demand_coverage_pct > 0 ? 'pass' : 'unknown',
      detail: delivery.length
        ? delivery.join(' · ')
        : inputs && inputs.min_demand_coverage_pct > 0
          ? `${solution ? solution.demand_retained_pct.toFixed(1) : '—'}% of demand arrives in the window, against the ${inputs.min_demand_coverage_pct.toFixed(0)}% required.`
          : 'No coverage requirement was set for this run, so nothing was tested.',
    },
    {
      id: 'assignment',
      label: 'Every zone assigned to an open facility',
      state: assignment.length ? 'fail' : 'pass',
      detail: assignment.length
        ? assignment.join(' · ')
        : 'No zone is unassigned or pointed at a closed facility.',
    },
    {
      id: 'evidence',
      label: 'Mireye evidence verified',
      state: evidenceFlags.length ? 'fail' : 'pass',
      detail: evidenceFlags.length
        ? `${evidenceFlags.length} value${evidenceFlags.length === 1 ? '' : 's'} could not be traced to a lookup.`
        : `${report.evidence_coverage_pct.toFixed(1)}% of audited values trace back to a recorded lookup.`,
    },
    {
      id: 'provenance',
      label: 'Geographic provenance available',
      state: report.missing_provenance_count > 0 ? 'fail' : 'pass',
      detail:
        report.missing_provenance_count > 0
          ? `${report.missing_provenance_count} record${report.missing_provenance_count === 1 ? '' : 's'} carry no provenance tag.`
          : 'Every audited site and lane carries a provenance tag.',
    },
  ];

  return checks;
}

/* ---------- recommendation against the cost-only baseline ---------------- */

export interface BaselineComparison {
  baseline: NetworkSolution;
  recommended: NetworkSolution;
  costChangePct: number;
  resilienceChangePct: number;
  demandChangePct: number;
  isBaseline: boolean;
}

export function compareToBaseline(
  frontier: NetworkSolution[],
  solution: NetworkSolution | null
): BaselineComparison | null {
  const baseline = baselineSolution(frontier);
  if (!baseline || !solution) return null;
  const pctChange = (before: number, after: number) =>
    before === 0 ? 0 : ((after - before) / before) * 100;

  return {
    baseline,
    recommended: solution,
    costChangePct: pctChange(baseline.total_cost, solution.total_cost),
    resilienceChangePct: pctChange(baseline.resilience_score, solution.resilience_score),
    demandChangePct: pctChange(baseline.demand_retained_pct, solution.demand_retained_pct),
    isBaseline: baseline.solution_id === solution.solution_id,
  };
}

/* ---------- the downloadable report -------------------------------------- */

/**
 * A plain-text version of what is on screen. Every line is a value already
 * returned by the backend; nothing is added for the file.
 */
export function buildReportMarkdown(
  state: NetworkStateResponse,
  solution: NetworkSolution | null
): string {
  const lines: string[] = [];
  const inputs = state.inputs;
  const graph = state.graph;

  lines.push(`# OptiFlow recommendation — ${inputs?.region_name ?? 'network'}`);
  lines.push('');
  lines.push(`Generated ${new Date().toISOString()}`);
  lines.push('');

  if (solution) {
    const minutes = avgDeliveryMinutes(graph, solution);
    lines.push('## Recommended network');
    lines.push('');
    lines.push(`- Design: ${solution.name}`);
    lines.push(`- Active warehouses: ${solution.selected_warehouse_ids.length}`);
    lines.push(`- Total cost: $${Math.round(solution.total_cost).toLocaleString('en-US')} a year`);
    lines.push(`- Demand coverage: ${solution.demand_retained_pct.toFixed(1)}%`);
    lines.push(
      `- Average delivery time: ${minutes == null ? 'not measured' : `${minutes.toFixed(1)} min`}`
    );
    lines.push(`- Resilience score: ${solution.resilience_score.toFixed(3)}`);
    lines.push('');

    const names = (graph?.warehouses ?? [])
      .filter((w) => solution.selected_warehouse_ids.includes(w.id))
      .map((w) => `  - ${w.name} (${w.status})`);
    if (names.length) {
      lines.push('### Facilities');
      lines.push('');
      lines.push(...names);
      lines.push('');
    }

    const comparison = compareToBaseline(state.frontier, solution);
    if (comparison && !comparison.isBaseline) {
      lines.push('### Against the cost-only baseline');
      lines.push('');
      lines.push(`- Cost: ${comparison.costChangePct >= 0 ? '+' : ''}${comparison.costChangePct.toFixed(1)}%`);
      lines.push(
        `- Resilience: ${comparison.resilienceChangePct >= 0 ? '+' : ''}${comparison.resilienceChangePct.toFixed(1)}%`
      );
      lines.push(
        `- Demand retention: ${comparison.demandChangePct >= 0 ? '+' : ''}${comparison.demandChangePct.toFixed(1)}%`
      );
      lines.push('');
    }
  }

  if (state.impact_report) {
    const r = state.impact_report;
    lines.push('## Stress test');
    lines.push('');
    lines.push(`- Scenario: ${r.title}`);
    lines.push(`- ${r.explanation}`);
    lines.push(
      `- Demand served: ${r.before.demand_served_pct.toFixed(1)}% -> ${r.after.demand_served_pct.toFixed(1)}%`
    );
    lines.push(
      `- Average delivery time: ${r.before.avg_delivery_minutes.toFixed(1)} min -> ${r.after.avg_delivery_minutes.toFixed(1)} min`
    );
    lines.push('');
  }

  if (state.recovery_report) {
    const r = state.recovery_report;
    lines.push('## Recovery');
    lines.push('');
    lines.push(`- ${r.summary}`);
    lines.push(`- Recovery time: ${r.recovery_seconds.toFixed(2)}s`);
    lines.push(`- Zones reassigned: ${r.customers_reassigned}`);
    lines.push(
      `- Demand served: ${r.before.demand_served_pct.toFixed(1)}% -> ${r.after.demand_served_pct.toFixed(1)}%`
    );
    lines.push(`- Cost against the healthy network: $${Math.round(r.added_cost_usd).toLocaleString('en-US')}`);
    lines.push('');
  }

  if (state.critic_report) {
    lines.push('## Verification');
    lines.push('');
    lines.push(`- Audit: ${state.critic_report.passed ? 'passed' : 'flags raised'}`);
    lines.push(`- Evidence coverage: ${state.critic_report.evidence_coverage_pct.toFixed(1)}%`);
    for (const v of state.critic_report.constraint_violations) lines.push(`- Violation: ${v}`);
    lines.push('');
  }

  if (state.narrative) {
    lines.push('## Why this network');
    lines.push('');
    lines.push(state.narrative);
    lines.push('');
  }

  return lines.join('\n');
}
