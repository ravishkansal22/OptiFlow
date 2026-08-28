import React from 'react';
import { ArrowRight, MapPin, Moon, Plus, Sun } from 'lucide-react';
import { Badge, Button, Mark, cn } from '../components/ui';
import { DataSourceBanner } from '../components/DataSourceBanner';
import { ConnectionPill } from '../components/AgentTrace';
import { STAGE_LABELS } from '../components/WorkflowShell';
import { num, pct, usdShort } from '../lib/format';
import { activeSolution, hasResults, summarizeScreening, totalDemand } from '../lib/domain';
import { avgDeliveryMinutes } from '../lib/network';
import { resumeStage } from '../lib/useOptiFlow';
import type { Theme } from '../lib/theme';
import type { OptiFlowStore } from '../lib/useOptiFlow';

export interface LandingProps {
  store: OptiFlowStore;
  theme: Theme;
  onToggleTheme: () => void;
  onCreate: () => void;
  onOpenNetwork: () => void;
  onCheckLocations: () => void;
}

/**
 * The way in. One clear action -- build a network -- with whatever the server
 * is already holding shown above it, so returning to a finished run is one
 * click rather than a rerun.
 */
export const Landing: React.FC<LandingProps> = ({
  store,
  theme,
  onToggleTheme,
  onCreate,
  onOpenNetwork,
  onCheckLocations,
}) => {
  const { state, region, busy } = store;
  const solution = activeSolution(state);
  const solved = hasResults(state);
  const summary = summarizeScreening(state?.candidates ?? [], solution);
  const minutes = avgDeliveryMinutes(state?.graph ?? null, solution);
  const stage = resumeStage(state);
  const working = !!busy;

  return (
    <div className="min-h-[100dvh]">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-5xl items-center gap-4 px-6 py-4 sm:px-8">
          <div className="flex items-center gap-2.5">
            <Mark />
            <span className="font-display text-base font-medium tracking-tight text-ink">
              OptiFlow
            </span>
            <span className="text-faint">/</span>
            <span className="text-xs text-muted">Network intelligence</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <DataSourceBanner data={store.dataSource} compact className="hidden sm:inline-flex" />
            <ConnectionPill status={store.connection} className="hidden sm:inline-flex" />
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggleTheme}
              aria-label={theme === 'dark' ? 'Use light colours' : 'Use dark colours'}
              className="px-2"
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-12 sm:px-8 sm:py-16">
        <section className="animate-fade-up">
          <h1 className="max-w-3xl font-display text-[2rem] font-medium leading-[1.15] tracking-tight text-ink sm:text-[2.75rem]">
            Design logistics networks that are efficient today and resilient tomorrow.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-muted sm:text-base">
            Give OptiFlow a region and what the network has to achieve. It screens the ground,
            scores the hazards, builds the routes, optimises the design, breaks it on purpose and
            repairs it — showing the evidence behind every step.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button variant="primary" size="lg" onClick={onCreate}>
              <Plus className="h-4 w-4" />
              Create New Network
            </Button>
            <Button variant="secondary" size="lg" onClick={onCheckLocations}>
              <MapPin className="h-4 w-4" />
              Screen individual sites
            </Button>
          </div>
        </section>

        {/* ------------- what the server is already holding ------------- */}
        {(solved || working || (state?.candidates?.length ?? 0) > 0) && (
          <section className="mt-10 animate-fade-up [animation-delay:60ms]">
            <h2 className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
              Current network
            </h2>
            <button
              onClick={onOpenNetwork}
              className="mt-3 flex w-full flex-wrap items-center gap-5 rounded-xl border border-accent/30 bg-accent-soft p-5 text-left transition-all hover:shadow-lift focus-ring"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="accent" dot={working}>
                    {working ? `Working — ${STAGE_LABELS[stage]}` : STAGE_LABELS[stage]}
                  </Badge>
                  {state?.impact_report && !state.recovery_report && (
                    <Badge tone="danger">disrupted</Badge>
                  )}
                  {state?.recovery_report && <Badge tone="pass">recovered</Badge>}
                </div>
                <p className="mt-2 font-display text-lg font-medium leading-tight tracking-tight text-ink">
                  {state?.inputs?.region_name ?? 'Untitled network'}
                </p>
                <p className="num mt-1.5 text-xs text-muted">
                  {solution
                    ? `${solution.selected_warehouse_ids.length} warehouses · ${usdShort(
                        solution.total_cost
                      )} a year · ${pct(solution.demand_retained_pct, 0)} of demand in the window${
                        minutes != null ? ` · ${minutes.toFixed(0)} min average` : ''
                      }`
                    : `${summary.total} sites screened · ${summary.passed} viable`}
                </p>
              </div>
              <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs font-medium text-accent">
                {working ? 'Watch it work' : 'Open this network'}
                <ArrowRight className="h-3.5 w-3.5" />
              </span>
            </button>

            {solution && (
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Tile label="Designs on the frontier" value={num(state?.frontier.length ?? 0)} note="Each a different set of warehouses" />
                <Tile
                  label="Sites screened"
                  value={num(summary.total)}
                  note={`${summary.passed} viable · ${summary.rejected} ruled out`}
                />
                <Tile
                  label="Demand zones"
                  value={num(state?.graph?.customers.length ?? 0)}
                  note={`${num(totalDemand(state?.graph ?? null))} units of demand`}
                />
                <Tile
                  label="Resilience score"
                  value={solution.resilience_score.toFixed(2)}
                  note="0 to 1, higher copes better"
                  tone="accent"
                />
              </div>
            )}
          </section>
        )}

        {/* ------------------------- how it works ------------------------- */}
        <section className="mt-14 animate-fade-up border-t border-line pt-8 [animation-delay:120ms]">
          <h2 className="text-sm font-semibold tracking-tight text-ink">How a network gets built</h2>
          <p className="mt-2 max-w-2xl text-xs leading-relaxed text-muted">
            Siting a warehouse is a trade-off: the cheapest land is often the land that floods.
            OptiFlow works through that with real geospatial data instead of guesswork.
            {region ? ` The server has ${region.candidate_warehouses.length} candidate sites, ${region.customers.length} demand zones and ${region.suppliers.length} suppliers loaded for ${region.region_name}.` : ''}
          </p>
          <ol className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            <Step
              n={1}
              title="Setup"
              body="Say where the network goes and what it has to achieve: delivery time, coverage, budget, and whether to favour cost or resilience."
            />
            <Step
              n={2}
              title="Analyze"
              body="Terrain, land cover and flood exposure are checked at every site, then real drive times are measured across the whole region."
            />
            <Step
              n={3}
              title="Optimize"
              body="A solver picks the best set of warehouses, and a frontier of alternatives shows what more resilience would cost."
            />
            <Step
              n={4}
              title="Stress test"
              body="Flood it, close the corridor or take a facility out, then watch OptiFlow repair the network and check its own work."
            />
          </ol>
        </section>

        <div className="mt-10 animate-fade-up [animation-delay:180ms]">
          <DataSourceBanner data={store.dataSource} />
        </div>
      </main>
    </div>
  );
};

/* ---------------------------------------------------------------- pieces */

const Tile: React.FC<{
  label: string;
  value: string;
  note: string;
  tone?: 'neutral' | 'accent';
}> = ({ label, value, note, tone = 'neutral' }) => (
  <div className="rounded-xl border border-line bg-surface p-4 shadow-card">
    <div className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">{label}</div>
    <div
      className={cn(
        'num mt-1.5 font-display text-3xl font-medium leading-none tracking-tight',
        tone === 'accent' ? 'text-accent' : 'text-ink'
      )}
    >
      {value}
    </div>
    <p className="mt-2 text-2xs leading-relaxed text-muted">{note}</p>
  </div>
);

const Step: React.FC<{ n: number; title: string; body: string }> = ({ n, title, body }) => (
  <li className="flex gap-3">
    <span className="num flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line bg-sunken text-2xs font-medium text-muted">
      {n}
    </span>
    <span>
      <span className="block text-[13px] font-medium text-ink">{title}</span>
      <span className="mt-1 block text-xs leading-relaxed text-muted">{body}</span>
    </span>
  </li>
);
