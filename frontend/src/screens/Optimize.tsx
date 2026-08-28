import React from 'react';
import { AlertTriangle, ArrowRight, SlidersHorizontal } from 'lucide-react';
import { Badge, Button, Card, CardHeader, cn } from '../components/ui';
import { Markdown } from '../components/Markdown';
import { NetworkMap } from '../panels/NetworkMap';
import { CostSplitCard, HubLoadCard, NetworkMetrics } from '../panels/PlanCards';
import { TradeoffPanel } from '../panels/TradeoffPanel';
import { Analyze } from './Analyze';
import { hubFeasibility } from '../lib/domain';
import { num } from '../lib/format';
import type { AgentTraceEvent, NetworkSolution, NetworkStateResponse } from '../types';
import type { ConnectionStatus } from '../services/websocket';

export interface OptimizeProps {
  state: NetworkStateResponse | null;
  solution: NetworkSolution | null;
  trace: AgentTraceEvent[];
  connection: ConnectionStatus;
  working: boolean;
  switching?: boolean;
  onSelectSolution: (id: string) => void;
  onStressTest: () => void;
  onBackToCandidates: () => void;
  onChangeSetup: () => void;
}

/**
 * The main dashboard: the network on the map, what it costs, and the frontier
 * of alternatives. Selecting a point on the frontier repaints everything here.
 */
export const Optimize: React.FC<OptimizeProps> = ({
  state,
  solution,
  trace,
  connection,
  working,
  switching,
  onSelectSolution,
  onStressTest,
  onBackToCandidates,
  onChangeSetup,
}) => {
  if (working) {
    return (
      <Analyze
        trace={trace}
        connection={connection}
        working
        phase="optimize"
        regionName={state?.inputs?.region_name}
        onBack={onBackToCandidates}
        backLabel="Back to the candidates"
      />
    );
  }

  if (!solution) {
    return <NoPlan state={state} trace={trace} onChangeSetup={onChangeSetup} onBack={onBackToCandidates} />;
  }

  const disrupted = !!state?.impact_report && !state?.recovery_report;
  const recovered = !!state?.recovery_report;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-display text-[1.6rem] font-medium leading-tight tracking-tight text-ink">
              Optimized Network
            </h1>
            {solution.is_baseline_cost_only && <Badge tone="warn">cost-only baseline</Badge>}
            {disrupted && <Badge tone="danger">running disrupted</Badge>}
            {recovered && <Badge tone="pass">recovered plan</Badge>}
          </div>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">
            {solution.name}
            {state?.frontier.length
              ? ` — one of ${state.frontier.length} designs OptiFlow found for this region.`
              : ''}
          </p>
        </div>
        <Button variant="primary" size="lg" onClick={onStressTest}>
          Stress Test This Network
          <ArrowRight className="h-4 w-4" />
        </Button>
      </header>

      <Card className={cn(switching && 'opacity-60 transition-opacity')}>
        <NetworkMetrics graph={state?.graph ?? null} solution={solution} inputs={state?.inputs ?? null} />
      </Card>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(20rem,0.9fr)] xl:items-start">
        <NetworkMap
          graph={state?.graph ?? null}
          candidates={state?.candidates ?? []}
          solution={solution}
          highlightWarehouseIds={state?.impact_report?.failed_warehouse_ids}
          title="The network"
          subtitle="Suppliers, facilities, demand zones, assigned lanes and hazard layers."
        />
        <div className="space-y-5">
          <CostSplitCard solution={solution} inputs={state?.inputs ?? null} />
          <HubLoadCard graph={state?.graph ?? null} solution={solution} onSeeAll={onBackToCandidates} />
        </div>
      </div>

      {/* ------------------------------------------- compare network designs */}
      <section>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-display text-lg font-medium tracking-tight text-ink">
              Compare Network Designs
            </h2>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted">
              Each point is a design the optimiser found. Further right costs more; higher up copes
              better with disruption. Click one and the map, the metrics and the facility list above
              all move to it.
            </p>
          </div>
        </div>
        <TradeoffPanel
          frontier={state?.frontier ?? []}
          activeId={state?.active_solution_id ?? ''}
          onSelect={onSelectSolution}
          busy={switching}
        />
      </section>

      {state?.narrative && (
        <Card>
          <CardHeader title="What OptiFlow found" subtitle="Written from the numbers above." />
          <div className="mt-4">
            <Markdown text={state.narrative} />
          </div>
        </Card>
      )}
    </div>
  );
};

/* ------------------------------------------------------------- no plan */

const NoPlan: React.FC<{
  state: NetworkStateResponse | null;
  trace: AgentTraceEvent[];
  onChangeSetup: () => void;
  onBack: () => void;
}> = ({ state, trace, onChangeSetup, onBack }) => {
  const graph = state?.graph ?? null;
  const { minHubs, totalDemand: demand, siteCount } = hubFeasibility(graph);
  const requested = state?.inputs?.target_warehouses_to_open ?? 0;

  // The optimiser reports the reason on its own trace event.
  const note = [...trace]
    .reverse()
    .find((e) => e.agent_name === 'Optimization Agent' && (e.status === 'error' || e.status === 'warning'));

  return (
    <div className="space-y-5">
      <Card className="border-l-[3px] border-l-warn">
        <div className="flex items-start gap-3.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-warn/25 bg-warn-soft text-warn">
            <AlertTriangle className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <h1 className="font-display text-xl font-medium tracking-tight text-ink">
              No workable design for these requirements
            </h1>
            <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">
              {note?.message ??
                'The solver found no assignment that satisfies the capacity, supply and demand constraints together.'}
            </p>
            <dl className="mt-4 grid gap-4 sm:grid-cols-3">
              <Fact label="Sites that qualified" value={num(siteCount)} />
              <Fact label="Warehouses allowed" value={num(requested)} />
              <Fact label="Demand to cover" value={`${num(demand)} units`} />
            </dl>
            {minHubs != null && minHubs > requested && (
              <p className="mt-4 rounded-lg border border-line bg-sunken px-3.5 py-3 text-xs leading-relaxed text-muted">
                Capacity is only covered from{' '}
                <span className="num font-semibold text-ink">{minHubs}</span> warehouses upward with
                the sites that qualified. That rules smaller counts out; it does not promise{' '}
                {minHubs} will work.
              </p>
            )}
            <div className="mt-5 flex flex-wrap gap-3">
              <Button variant="primary" size="md" onClick={onChangeSetup}>
                <SlidersHorizontal className="h-3.5 w-3.5" />
                Change the requirements
              </Button>
              <Button variant="secondary" size="md" onClick={onBack}>
                Review the candidates
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {state?.narrative && (
        <Card>
          <CardHeader title="The full explanation" subtitle="From the narrator agent." />
          <div className="mt-4">
            <Markdown text={state.narrative} />
          </div>
        </Card>
      )}
    </div>
  );
};

const Fact: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <dt className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">{label}</dt>
    <dd className="num mt-1 font-display text-xl font-medium leading-none text-ink">{value}</dd>
  </div>
);
