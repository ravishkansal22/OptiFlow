import React from 'react';
import { Building2, Truck } from 'lucide-react';
import { Button, Card, CardHeader, Meter, Stat, cn } from '../components/ui';
import { num, pct, score, usd, usdShort } from '../lib/format';
import { avgDeliveryMinutes } from '../lib/network';
import { totalDemand } from '../lib/domain';
import type { InputSpec, LogisticsGraph, NetworkSolution } from '../types';

/**
 * The five numbers that describe a network, read straight off the active
 * solution and the routed graph behind it.
 */
export const NetworkMetrics: React.FC<{
  graph: LogisticsGraph | null;
  solution: NetworkSolution;
  inputs?: InputSpec | null;
  className?: string;
}> = ({ graph, solution, inputs, className }) => {
  const minutes = avgDeliveryMinutes(graph, solution);
  const overBudget = inputs ? solution.total_cost > inputs.budget_limit_usd : false;
  const openHubs = (graph?.warehouses ?? []).filter((w) =>
    solution.selected_warehouse_ids.includes(w.id)
  );
  const offline = openHubs.filter((w) => w.status !== 'active').length;
  const shortOfCoverage =
    inputs && inputs.min_demand_coverage_pct > 0
      ? solution.demand_retained_pct < inputs.min_demand_coverage_pct
      : false;

  return (
    <div className={cn('grid gap-6 sm:grid-cols-2 lg:grid-cols-5', className)}>
      <Stat
        label="Total cost"
        value={usd(solution.total_cost)}
        tone={overBudget ? 'danger' : 'neutral'}
        hint={
          inputs
            ? overBudget
              ? `${usd(solution.total_cost - inputs.budget_limit_usd)} over budget`
              : `${usd(inputs.budget_limit_usd - solution.total_cost)} under budget`
            : 'a year'
        }
      />
      <Stat
        label="Active warehouses"
        value={num(openHubs.length)}
        tone={offline ? 'danger' : 'neutral'}
        hint={
          offline
            ? `${offline} offline right now`
            : `of ${num(graph?.warehouses.length ?? 0)} viable sites`
        }
      />
      <Stat
        label="Demand coverage"
        value={pct(solution.demand_retained_pct, 1)}
        tone={shortOfCoverage ? 'warn' : 'neutral'}
        hint={
          inputs && inputs.min_demand_coverage_pct > 0
            ? `${pct(inputs.min_demand_coverage_pct, 0)} required`
            : `${num(graph?.customers.length ?? 0)} demand zones`
        }
      />
      <Stat
        label="Avg delivery time"
        value={minutes == null ? '—' : `${minutes.toFixed(1)} min`}
        hint={
          minutes == null
            ? 'no routed lanes to measure'
            : inputs
              ? `${num(inputs.service_radius_minutes)} min window`
              : 'demand-weighted'
        }
      />
      <Stat
        label="Resilience score"
        value={score(solution.resilience_score)}
        tone="accent"
        hint="0 to 1, higher copes better"
      />
    </div>
  );
};

/** Where the money goes, split the way the solver reported it. */
export const CostSplitCard: React.FC<{
  solution: NetworkSolution;
  inputs?: InputSpec | null;
  className?: string;
}> = ({ solution, inputs, className }) => {
  const overBudget = inputs ? solution.total_cost > inputs.budget_limit_usd : false;
  const total = Math.max(solution.total_cost, 1);

  return (
    <Card className={className}>
      <CardHeader title="Where the money goes" subtitle="Annual, as the solver costed it." />
      <div className="mt-4 flex h-2.5 overflow-hidden rounded-full bg-sunken">
        <div className="h-full bg-accent" style={{ width: `${(solution.total_fixed_cost / total) * 100}%` }} />
        <div
          className="h-full bg-info/50"
          style={{ width: `${(solution.total_transport_cost / total) * 100}%` }}
        />
      </div>
      <dl className="mt-4 space-y-3">
        <CostRow
          icon={<Building2 className="h-3.5 w-3.5" />}
          label="Running the warehouses"
          value={usd(solution.total_fixed_cost)}
          share={solution.total_fixed_cost / total}
          swatch="bg-accent"
        />
        <CostRow
          icon={<Truck className="h-3.5 w-3.5" />}
          label="Moving the goods"
          value={usd(solution.total_transport_cost)}
          share={solution.total_transport_cost / total}
          swatch="bg-info/50"
        />
      </dl>
      {inputs && (
        <div className="mt-5 border-t border-line pt-4">
          <div className="flex items-baseline justify-between">
            <span className="text-2xs text-muted">Of the {usd(inputs.budget_limit_usd)} budget</span>
            <span className={cn('num text-xs font-medium', overBudget ? 'text-danger' : 'text-ink')}>
              {pct((solution.total_cost / inputs.budget_limit_usd) * 100, 0)}
            </span>
          </div>
          <Meter
            value={Math.min(1, solution.total_cost / inputs.budget_limit_usd)}
            tone={overBudget ? 'danger' : 'accent'}
            className="mt-2"
          />
        </div>
      )}
    </Card>
  );
};

const CostRow: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
  share: number;
  swatch: string;
}> = ({ icon, label, value, share, swatch }) => (
  <div className="flex items-center gap-3">
    <span className={cn('h-2.5 w-2.5 shrink-0 rounded-sm', swatch)} />
    <span className="flex items-center gap-1.5 text-xs text-muted">
      <span className="text-faint">{icon}</span>
      {label}
    </span>
    <span className="num ml-auto text-xs font-medium text-ink">{value}</span>
    <span className="num w-9 shrink-0 text-right text-2xs text-faint">
      {(share * 100).toFixed(0)}%
    </span>
  </div>
);

/** What each open facility is carrying under the active plan. */
export const HubLoadCard: React.FC<{
  graph: LogisticsGraph | null;
  solution: NetworkSolution;
  onSeeAll?: () => void;
  className?: string;
}> = ({ graph, solution, onSeeAll, className }) => {
  const demand = totalDemand(graph);
  const openHubs = (graph?.warehouses ?? []).filter((w) =>
    solution.selected_warehouse_ids.includes(w.id)
  );

  const rows = openHubs
    .map((w) => {
      const served = (graph?.customers ?? []).filter(
        (c) => solution.customer_assignments[c.id] === w.id
      );
      return { w, zones: served.length, units: served.reduce((s, c) => s + c.demand_units, 0) };
    })
    .sort((a, b) => b.units - a.units);

  return (
    <Card flush className={className}>
      <div className="border-b border-line px-5 py-3.5">
        <CardHeader
          title="Facilities in this design"
          subtitle="Largest share of the work first."
          action={
            onSeeAll && (
              <Button variant="ghost" size="sm" onClick={onSeeAll}>
                All sites
              </Button>
            )
          }
        />
      </div>
      <ul className="divide-y divide-line">
        {rows.length === 0 ? (
          <li className="px-5 py-6 text-xs text-muted">No facility is open in this design.</li>
        ) : (
          rows.map(({ w, zones, units }) => (
            <li key={w.id} className="px-5 py-3.5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="truncate text-[13px] font-medium text-ink">{w.name}</span>
                <span className="num shrink-0 text-xs text-muted">
                  {demand > 0 ? pct((units / demand) * 100, 0) : '—'}
                </span>
              </div>
              <Meter
                value={demand > 0 ? units / demand : 0}
                tone={w.status === 'active' ? 'accent' : 'danger'}
                className="mt-1.5"
              />
              <p className="num mt-1.5 text-2xs text-faint">
                {num(units)} units · {zones} zones · {usdShort(w.fixed_operating_cost)}/yr · flood{' '}
                {w.flood_risk_score.toFixed(2)}
                {w.status !== 'active' && ` · ${w.status}`}
              </p>
            </li>
          ))
        )}
      </ul>
    </Card>
  );
};
