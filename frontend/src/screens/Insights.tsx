import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Download,
  MessageSquareText,
  RotateCcw,
} from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState, Meter, cn } from '../components/ui';
import { Markdown } from '../components/Markdown';
import { AuditPanel } from '../panels/AuditPanel';
import { BackendPanel } from '../panels/BackendPanel';
import { CostSplitCard, HubLoadCard, NetworkMetrics } from '../panels/PlanCards';
import { NetworkMap } from '../panels/NetworkMap';
import { buildReportMarkdown, compareToBaseline, verificationChecks } from '../lib/network';
import { num, pct, score, usd } from '../lib/format';
import type { AgentTraceEvent, NetworkSolution, NetworkStateResponse } from '../types';
import type { ConnectionStatus } from '../services/websocket';

export interface InsightsProps {
  state: NetworkStateResponse | null;
  /** The design being recommended, which may differ from the one running now. */
  solution: NetworkSolution | null;
  /** The plan the network is running on, when a recovery has changed it. */
  running?: NetworkSolution | null;
  trace: AgentTraceEvent[];
  connection: ConnectionStatus;
  onRunScenario: () => void;
  onAsk: () => void;
}

/**
 * The recommendation, what it costs against the cheapest design, whether it
 * passed its own checks, and why it was chosen. Every figure is read from the
 * state the agents produced.
 */
export const Insights: React.FC<InsightsProps> = ({
  state,
  solution,
  running,
  trace,
  connection,
  onRunScenario,
  onAsk,
}) => {
  const [showAudit, setShowAudit] = useState(false);

  const comparison = useMemo(
    () => compareToBaseline(state?.frontier ?? [], solution),
    [state?.frontier, solution]
  );
  // The critic audits whatever plan is in place, which after a recovery is the
  // repaired network rather than the recommendation. Check against that plan so
  // the findings and the figures beside them describe the same thing.
  const audited = running ?? solution;
  const checks = useMemo(
    () => verificationChecks(state?.critic_report ?? null, audited, state?.inputs ?? null),
    [state?.critic_report, audited, state?.inputs]
  );
  const failing = checks.filter((c) => c.state === 'fail');

  const download = () => {
    if (!state) return;
    const text = buildReportMarkdown(state, solution);
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `optiflow-${(state.inputs?.region_name ?? 'network')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '')}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  if (!solution) {
    return (
      <Card>
        <EmptyState
          icon={<CircleHelp className="h-5 w-5" />}
          title="No recommendation yet"
          body="Optimise a network and the recommendation, its evidence and the reasoning behind it appear here."
        />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent" dot>
              recommended
            </Badge>
            {state?.recovery_report && <Badge tone="pass">stress tested and recovered</Badge>}
            {failing.length > 0 && <Badge tone="warn">{failing.length} critic flag{failing.length === 1 ? '' : 's'}</Badge>}
          </div>
          <h1 className="mt-2 font-display text-[1.6rem] font-medium leading-tight tracking-tight text-ink">
            OptiFlow Recommendation
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">
            Open {solution.selected_warehouse_ids.length}{' '}
            {solution.selected_warehouse_ids.length === 1 ? 'warehouse' : 'warehouses'}
            {state?.inputs?.region_name ? ` across ${state.inputs.region_name}` : ''} —{' '}
            {solution.name}.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="md" onClick={download}>
            <Download className="h-3.5 w-3.5" />
            Download report
          </Button>
          <Button variant="secondary" size="md" onClick={onRunScenario}>
            <RotateCcw className="h-3.5 w-3.5" />
            Run another scenario
          </Button>
          <Button variant="primary" size="md" onClick={onAsk}>
            <MessageSquareText className="h-3.5 w-3.5" />
            Ask OptiFlow
          </Button>
        </div>
      </header>

      <Card>
        <NetworkMetrics
          graph={state?.graph ?? null}
          solution={solution}
          inputs={state?.inputs ?? null}
        />
        {running && running.solution_id !== solution.solution_id && (
          <p className="mt-5 border-t border-line pt-4 text-xs leading-relaxed text-muted">
            The network is currently running on{' '}
            <span className="font-medium text-ink">{running.name}</span> after the stress test —{' '}
            {pct(running.demand_retained_pct, 1)} of demand at {usd(running.total_cost)} a year.
            The figures above describe the design being recommended; the stress test below is what
            happened when it was broken on purpose.
          </p>
        )}
      </Card>

      {/* --------------------------------------- against the cost-only baseline */}
      {comparison && (
        <Card>
          <CardHeader
            title="Against the cost-only baseline"
            subtitle={
              comparison.isBaseline
                ? 'This recommendation is the cost-only baseline. Nothing has been spent on shielding the network yet.'
                : `The cheapest design OptiFlow found was ${comparison.baseline.name}.`
            }
          />
          {comparison.isBaseline ? (
            <p className="mt-4 text-xs leading-relaxed text-muted">
              Move along the frontier on the Optimize screen to see what more resilience would cost.
            </p>
          ) : (
            <>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <Change label="Cost" value={comparison.costChangePct} betterWhenUp={false} />
                <Change label="Resilience" value={comparison.resilienceChangePct} betterWhenUp />
                <Change
                  label="Demand retention"
                  value={comparison.demandChangePct}
                  betterWhenUp
                />
              </div>
              <div className="mt-5 grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
                <SideBySide
                  label="Cost-only baseline"
                  tone="warn"
                  solution={comparison.baseline}
                />
                <SideBySide label="Recommended" tone="accent" solution={comparison.recommended} />
              </div>
            </>
          )}
        </Card>
      )}

      {/* --------------------------------------- what the stress test showed */}
      {state?.impact_report && (
        <Card className="border-l-[3px] border-l-warn">
          <CardHeader
            title="What the stress test showed"
            subtitle={state.impact_report.title}
          />
          <p className="mt-3 text-xs leading-relaxed text-muted">
            {state.impact_report.explanation}
          </p>
          {state.recovery_report && (
            <p className="mt-2 text-xs leading-relaxed text-muted">
              {state.recovery_report.summary} Recovery took{' '}
              <span className="num font-medium text-ink">
                {state.recovery_report.recovery_seconds.toFixed(2)}s
              </span>
              .
            </p>
          )}
          <Button variant="secondary" size="sm" onClick={onRunScenario} className="mt-4">
            <RotateCcw className="h-3.5 w-3.5" />
            Open the stress test
          </Button>
        </Card>
      )}

      {/* --------------------------------------------------------- verification */}
      <Card className={cn('border-l-[3px]', failing.length ? 'border-l-warn' : 'border-l-pass')}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <CardHeader
            title="Verification"
            subtitle={
              audited && audited.solution_id !== solution.solution_id
                ? `The critic last audited the network as it stands now — ${audited.name}.`
                : 'The critic agent audits every recommendation before it is shown.'
            }
          />
          {state?.critic_report && (
            <div className="min-w-[12rem]">
              <div className="flex items-baseline justify-between">
                <span className="text-2xs uppercase tracking-[0.06em] text-faint">
                  Evidence coverage
                </span>
                <span className="num text-sm font-medium text-ink">
                  {state.critic_report.evidence_coverage_pct.toFixed(1)}%
                </span>
              </div>
              <Meter
                value={state.critic_report.evidence_coverage_pct}
                max={100}
                tone={state.critic_report.evidence_coverage_pct >= 95 ? 'pass' : 'warn'}
                className="mt-2"
              />
            </div>
          )}
        </div>

        <ul className="mt-5 space-y-2.5">
          {checks.map((c) => (
            <li
              key={c.id}
              className={cn(
                'flex items-start gap-3 rounded-lg border px-3.5 py-3',
                c.state === 'fail'
                  ? 'border-warn/25 bg-warn-soft'
                  : c.state === 'unknown'
                    ? 'border-line bg-sunken'
                    : 'border-line bg-surface'
              )}
            >
              <span className="mt-0.5 shrink-0">
                {c.state === 'fail' ? (
                  <AlertTriangle className="h-4 w-4 text-warn" />
                ) : c.state === 'unknown' ? (
                  <CircleHelp className="h-4 w-4 text-faint" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 text-pass" />
                )}
              </span>
              <span className="min-w-0">
                <span
                  className={cn(
                    'block text-[13px] font-medium',
                    c.state === 'fail' ? 'text-warn' : 'text-ink'
                  )}
                >
                  {c.state === 'fail' ? `CRITIC FLAG — ${c.label}` : c.label}
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted">{c.detail}</span>
              </span>
            </li>
          ))}
        </ul>

        {failing.length > 0 && (
          <p className="mt-4 rounded-lg border border-line bg-sunken px-3.5 py-3 text-xs leading-relaxed text-muted">
            The plan is still workable, but read the flags above before committing money. Moving to
            another design on the frontier, raising the facility cap or relaxing the coverage
            requirement usually clears them.
          </p>
        )}

        <div className="mt-4 border-t border-line pt-4">
          <button
            onClick={() => setShowAudit((v) => !v)}
            className="flex items-center gap-1.5 text-xs font-medium text-muted transition-colors hover:text-ink focus-ring"
          >
            <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showAudit && 'rotate-180')} />
            Full audit, evidence log and agent trace
          </button>
          {showAudit && (
            <div className="mt-4 animate-fade-in space-y-6">
              <AuditPanel
                report={state?.critic_report ?? null}
                flags={state?.critic_flags ?? []}
                trace={trace}
              />
              <BackendPanel connection={connection} traceCount={trace.length} state={state} />
            </div>
          )}
        </div>
      </Card>

      {/* ------------------------------------------------- why this network */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader
            title="Why this network?"
            subtitle="From the narrator agent, using only the optimisation results and the evidence behind them."
          />
          {state?.narrative ? (
            <div className="mt-4">
              <Markdown text={state.narrative} />
            </div>
          ) : (
            <p className="mt-4 text-sm text-muted">No report has been generated for this plan yet.</p>
          )}
        </Card>

        <div className="space-y-5">
          <CostSplitCard solution={solution} inputs={state?.inputs ?? null} />
          <HubLoadCard graph={state?.graph ?? null} solution={solution} />
        </div>
      </div>

      <NetworkMap
        graph={state?.graph ?? null}
        candidates={state?.candidates ?? []}
        solution={solution}
        highlightWarehouseIds={state?.impact_report?.failed_warehouse_ids}
        title="The recommended network"
        subtitle="What you would be building."
      />
    </div>
  );
};

/* ---------------------------------------------------------------- pieces */

const Change: React.FC<{ label: string; value: number; betterWhenUp: boolean }> = ({
  label,
  value,
  betterWhenUp,
}) => {
  const up = value >= 0;
  const good = betterWhenUp ? up : !up;
  const neutral = Math.abs(value) < 0.05;
  return (
    <div className="rounded-lg border border-line bg-sunken px-3.5 py-3">
      <div className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">{label}</div>
      <div
        className={cn(
          'num mt-1 font-display text-2xl font-medium leading-none tracking-tight',
          neutral ? 'text-ink' : good ? 'text-pass' : 'text-warn'
        )}
      >
        {up ? '+' : ''}
        {value.toFixed(1)}%
      </div>
      <p className="mt-1.5 text-2xs leading-relaxed text-muted">against the cheapest design</p>
    </div>
  );
};

const SideBySide: React.FC<{
  label: string;
  tone: 'accent' | 'warn';
  solution: NetworkSolution;
}> = ({ label, tone, solution }) => (
  <div className="flex items-start gap-3 rounded-lg border border-line px-3.5 py-3">
    <span
      className={cn('mt-0.5 h-10 w-1 shrink-0 rounded-full', tone === 'accent' ? 'bg-accent' : 'bg-warn')}
    />
    <div className="min-w-0 flex-1">
      <p className="text-xs font-medium text-ink">{label}</p>
      <p className="num mt-0.5 truncate text-2xs text-faint">{solution.name}</p>
      <dl className="mt-2 space-y-1">
        <Line k="Cost" v={usd(solution.total_cost)} />
        <Line k="Resilience" v={score(solution.resilience_score)} />
        <Line k="Coverage" v={pct(solution.demand_retained_pct, 1)} />
        <Line k="Warehouses" v={num(solution.selected_warehouse_ids.length)} />
      </dl>
    </div>
  </div>
);

const Line: React.FC<{ k: string; v: string }> = ({ k, v }) => (
  <div className="flex items-baseline justify-between gap-3">
    <dt className="text-2xs text-faint">{k}</dt>
    <dd className="num text-2xs font-medium text-ink">{v}</dd>
  </div>
);
