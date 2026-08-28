import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  CloudRain,
  Layers3,
  RotateCcw,
  Siren,
  TrafficCone,
  TrendingUp,
  Wand2,
  Warehouse,
  Zap,
} from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState, Spinner, cn } from '../components/ui';
import { EvidenceButton } from '../components/Provenance';
import { NetworkMap } from '../panels/NetworkMap';
import { SnapshotComparison, HeadlineStat } from '../panels/BeforeAfter';
import { DisruptionHistory, HubRiskCard } from '../panels/ResiliencePanel';
import { compareSnapshots } from '../lib/network';
import { num, pct } from '../lib/format';
import type {
  NetworkSolution,
  NetworkStateResponse,
  ScenarioDef,
  ScenarioParam,
} from '../types';

/** An icon per scenario id. Everything else about a scenario comes from the API. */
const SCENARIO_ICONS: Record<string, React.ReactNode> = {
  warehouse_failure: <Warehouse className="h-4 w-4" />,
  road_closure_corridor: <TrafficCone className="h-4 w-4" />,
  flood_green_river: <CloudRain className="h-4 w-4" />,
  surge_demand: <TrendingUp className="h-4 w-4" />,
  combined_disaster: <Layers3 className="h-4 w-4" />,
  auto: <Wand2 className="h-4 w-4" />,
};

export interface StressTestProps {
  state: NetworkStateResponse | null;
  solution: NetworkSolution | null;
  scenarios: ScenarioDef[];
  busy: boolean;
  restoring: boolean;
  onDisrupt: (scenario: string, params: Record<string, unknown>) => void;
  onRecover: () => void;
  onRestore: () => void;
}

/**
 * Choose a scenario, watch it hit the network, then decide whether to repair it.
 * Both halves are on one screen because they are one thought.
 */
export const StressTest: React.FC<StressTestProps> = ({
  state,
  solution,
  scenarios,
  busy,
  restoring,
  onDisrupt,
  onRecover,
  onRestore,
}) => {
  const impact = state?.impact_report ?? null;
  const recovered = !!state?.recovery_report;

  if (impact && !recovered) {
    return (
      <ImpactView
        state={state}
        solution={solution}
        busy={busy}
        restoring={restoring}
        onRecover={onRecover}
        onRestore={onRestore}
      />
    );
  }

  return (
    <ScenarioPicker
      state={state}
      solution={solution}
      scenarios={scenarios}
      busy={busy}
      restoring={restoring}
      onDisrupt={onDisrupt}
      onRestore={onRestore}
      recovered={recovered}
    />
  );
};

/* --------------------------------------------------------- pick a scenario */

const ScenarioPicker: React.FC<{
  state: NetworkStateResponse | null;
  solution: NetworkSolution | null;
  scenarios: ScenarioDef[];
  busy: boolean;
  restoring: boolean;
  recovered: boolean;
  onDisrupt: (scenario: string, params: Record<string, unknown>) => void;
  onRestore: () => void;
}> = ({ state, solution, scenarios, busy, restoring, recovered, onDisrupt, onRestore }) => {
  const [selected, setSelected] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});

  const current = scenarios.find((s) => s.id === selected) ?? null;

  // Each scenario carries its own defaults, so switching cards resets the form.
  useEffect(() => {
    if (!current) return;
    const next: Record<string, unknown> = {};
    for (const p of current.parameters) if (p.default != null) next[p.key] = p.default;
    setValues(next);
  }, [current?.id]);

  if (!solution) {
    return (
      <Card>
        <EmptyState
          icon={<Siren className="h-5 w-5" />}
          title="No network to stress test"
          body="Optimise a network first, then break it here on purpose."
        />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-[1.6rem] font-medium leading-tight tracking-tight text-ink">
            Stress Test Your Network
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">
            Pick something that could go wrong. OptiFlow applies it to the real network, measures the
            damage, and then repairs it on your say-so.
          </p>
        </div>
        {recovered && (
          <Button variant="secondary" size="md" onClick={onRestore} loading={restoring}>
            <RotateCcw className="h-3.5 w-3.5" />
            Reset to the healthy network
          </Button>
        )}
      </header>

      {scenarios.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Siren className="h-5 w-5" />}
            title="No scenarios available"
            body="The server did not return a scenario catalogue for this network."
          />
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {scenarios.map((s) => (
            <button
              key={s.id}
              onClick={() => setSelected(s.id)}
              disabled={!s.available || busy}
              className={cn(
                'group flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition-all duration-150 focus-ring',
                selected === s.id
                  ? 'border-accent bg-accent-soft shadow-card'
                  : 'border-line bg-surface hover:border-strong hover:shadow-lift',
                (!s.available || busy) && 'cursor-not-allowed opacity-50'
              )}
            >
              <span
                className={cn(
                  'flex h-9 w-9 items-center justify-center rounded-lg border transition-colors',
                  selected === s.id
                    ? 'border-accent/30 bg-surface text-accent'
                    : 'border-line bg-sunken text-muted group-hover:text-ink'
                )}
              >
                {SCENARIO_ICONS[s.id] ?? <Siren className="h-4 w-4" />}
              </span>
              <span className="flex items-center gap-2">
                <span
                  className={cn(
                    'text-[13px] font-medium',
                    selected === s.id ? 'text-accent' : 'text-ink'
                  )}
                >
                  {s.title}
                </span>
                {s.id === 'auto' && <Badge tone="accent">recommended</Badge>}
              </span>
              <span className="text-xs leading-relaxed text-muted">{s.summary}</span>
              {!s.available && (
                <span className="text-2xs text-faint">Not available for this network.</span>
              )}
            </button>
          ))}
        </div>
      )}

      {current && (
        <Card className="animate-fade-up">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <CardHeader
              title={current.title}
              subtitle={
                current.parameters.length
                  ? 'Adjust what this scenario does, or run it as it stands.'
                  : 'Nothing to configure — this scenario reads what it needs from the network.'
              }
            />
            <Button
              variant="primary"
              size="md"
              onClick={() => onDisrupt(current.id, values)}
              loading={busy}
            >
              Simulate Disruption
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </div>

          {current.parameters.length > 0 && (
            <div className="mt-5 grid gap-4 border-t border-line pt-5 sm:grid-cols-2">
              {current.parameters.map((p) => (
                <ParamField
                  key={p.key}
                  param={p}
                  value={values[p.key]}
                  onChange={(v) => setValues((cur) => ({ ...cur, [p.key]: v }))}
                />
              ))}
            </div>
          )}

          {current.id === 'auto' && (
            <p className="mt-4 rounded-lg border border-line bg-sunken px-3.5 py-3 text-xs leading-relaxed text-muted">
              The disaster agent inspects this network — what sits inside a mapped hazard zone, and
              which facility carries the most demand — and runs whichever scenario it is most
              exposed to. It reports which one it chose and why.
            </p>
          )}
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <HubRiskCard graph={state?.graph ?? null} solution={solution} />
        <DisruptionHistory
          disruptions={state?.disruption_log ?? []}
          graph={state?.graph ?? null}
        />
      </div>
    </div>
  );
};

const ParamField: React.FC<{
  param: ScenarioParam;
  value: unknown;
  onChange: (v: unknown) => void;
}> = ({ param, value, onChange }) => (
  <label className="block">
    <span className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
      {param.label}
    </span>
    {param.type === 'select' ? (
      <select
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
        className="mt-2 w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-xs text-ink outline-none transition-colors focus:border-accent/50 focus:ring-4 focus:ring-accent/10"
      >
        {(param.options ?? []).map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
            {o.detail ? ` — ${o.detail}` : ''}
          </option>
        ))}
      </select>
    ) : (
      <span className="mt-2 flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 focus-within:border-accent/40 focus-within:ring-4 focus-within:ring-accent/10">
        <input
          type="number"
          value={Number(value ?? param.default ?? 0)}
          min={param.min}
          max={param.max}
          step={param.step}
          onChange={(e) => onChange(Number(e.target.value))}
          className="num w-full bg-transparent text-sm text-ink outline-none"
        />
        {param.unit && <span className="text-2xs text-faint">{param.unit}</span>}
      </span>
    )}
  </label>
);

/* ------------------------------------------------------------ the damage */

const ImpactView: React.FC<{
  state: NetworkStateResponse | null;
  solution: NetworkSolution | null;
  busy: boolean;
  restoring: boolean;
  onRecover: () => void;
  onRestore: () => void;
}> = ({ state, solution, busy, restoring, onRecover, onRestore }) => {
  const impact = state!.impact_report!;
  const rows = useMemo(() => compareSnapshots(impact.before, impact.after), [impact]);
  const disruption = state?.disruption_log?.[state.disruption_log.length - 1] ?? null;
  const failedNames = impact.failed_warehouse_ids.map(
    (id) => state?.graph?.warehouses.find((w) => w.id === id)?.name ?? id
  );

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="danger" dot>
              {impact.disruption_type}
            </Badge>
            <h1 className="font-display text-[1.6rem] font-medium leading-tight tracking-tight text-ink">
              Network Impact
            </h1>
          </div>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">{impact.title}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="md" onClick={onRestore} loading={restoring}>
            <RotateCcw className="h-3.5 w-3.5" />
            Run a different scenario
          </Button>
          <Button variant="primary" size="lg" onClick={onRecover} loading={busy}>
            <Zap className="h-4 w-4" />
            Automatically Recover Network
          </Button>
        </div>
      </header>

      <Card className="border-l-[3px] border-l-danger">
        <p className="text-sm leading-relaxed text-ink">{impact.explanation}</p>
        {disruption && (
          <p className="mt-2 text-xs leading-relaxed text-muted">{disruption.description}</p>
        )}
        <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2 lg:grid-cols-4">
          <HeadlineStat
            label="Facilities lost"
            value={num(impact.failed_warehouse_ids.length)}
            hint={failedNames.join(', ') || 'None — the facilities are all standing'}
            tone={impact.failed_warehouse_ids.length ? 'danger' : 'neutral'}
          />
          <HeadlineStat
            label="Lanes blocked"
            value={num(impact.disrupted_edge_ids.length)}
            hint="Routes that stopped moving"
          />
          <HeadlineStat
            label="Zones affected"
            value={num(impact.affected_customer_ids.length)}
            hint={`of ${num(state?.graph?.customers.length ?? 0)} demand zones`}
            tone={impact.affected_customer_ids.length ? 'warn' : 'neutral'}
          />
          <HeadlineStat
            label="Demand in the network"
            value={num(impact.after.demand_total_units)}
            hint={
              disruption && disruption.demand_multiplier !== 1
                ? `${disruption.demand_multiplier.toFixed(2)}x normal under this scenario`
                : 'unchanged by this scenario'
            }
          />
        </div>
      </Card>

      <section>
        <h2 className="text-sm font-semibold tracking-tight text-ink">Before and after</h2>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted">
          The same network, measured with the plan left exactly as it was. Nothing has been
          re-optimised yet.
        </p>
        <SnapshotComparison rows={rows} className="mt-4" />
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(20rem,0.9fr)] xl:items-start">
        <NetworkMap
          graph={state?.graph ?? null}
          candidates={state?.candidates ?? []}
          solution={solution}
          highlightWarehouseIds={impact.failed_warehouse_ids}
          title="The network under this scenario"
          subtitle="Failed facilities and disrupted lanes are drawn in red."
        />
        <div className="space-y-5">
          <Card>
            <CardHeader
              title="Where this came from"
              subtitle="The scenario is built from the hazard layers and routed lanes in this network."
            />
            <dl className="mt-4 space-y-2.5">
              <Fact k="Scenario id" v={impact.disruption_id} />
              <Fact k="Type" v={impact.disruption_type} />
              {disruption?.flood_depth_m != null && (
                <Fact k="Flood depth" v={`${disruption.flood_depth_m.toFixed(2)} m`} />
              )}
              <Fact k="Demand multiplier" v={`${disruption?.demand_multiplier.toFixed(2) ?? '1.00'}x`} />
              <Fact
                k="Demand still served"
                v={pct(impact.after.demand_served_pct, 1)}
              />
            </dl>
            {disruption?.provenance && (
              <div className="mt-4 border-t border-line pt-4">
                <EvidenceButton
                  provenance={{ disruption: disruption.provenance }}
                  title={impact.title}
                />
              </div>
            )}
          </Card>
          <HubRiskCard graph={state?.graph ?? null} solution={solution} />
        </div>
      </div>

      <Card className="flex flex-wrap items-center gap-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-accent/25 bg-accent-soft text-accent">
          {busy ? <Spinner className="h-4 w-4" /> : <Zap className="h-4 w-4" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-ink">Repair this network</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            OptiFlow reassigns the affected zones to surviving facilities, re-routes them, and
            re-checks the constraints before showing you the result.
          </p>
        </div>
        <Button variant="primary" size="md" onClick={onRecover} loading={busy}>
          <Zap className="h-3.5 w-3.5" />
          Automatically Recover Network
        </Button>
      </Card>
    </div>
  );
};

const Fact: React.FC<{ k: string; v: string }> = ({ k, v }) => (
  <div className="flex items-baseline justify-between gap-3">
    <dt className="text-2xs text-faint">{k}</dt>
    <dd className="num truncate text-xs text-ink">{v}</dd>
  </div>
);
