import React, { useMemo } from 'react';
import { ArrowRight, RotateCcw, Siren, Zap } from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState } from '../components/ui';
import { Markdown } from '../components/Markdown';
import { NetworkMap } from '../panels/NetworkMap';
import { HeadlineStat, SnapshotComparison } from '../panels/BeforeAfter';
import { Analyze } from './Analyze';
import { compareSnapshots } from '../lib/network';
import { num, usd } from '../lib/format';
import type { AgentTraceEvent, NetworkSolution, NetworkStateResponse } from '../types';
import type { ConnectionStatus } from '../services/websocket';

export interface RecoveryProps {
  state: NetworkStateResponse | null;
  solution: NetworkSolution | null;
  trace: AgentTraceEvent[];
  connection: ConnectionStatus;
  working: boolean;
  restoring: boolean;
  onRestore: () => void;
  onInsights: () => void;
  onBackToStress: () => void;
}

/**
 * What the recovery re-solve actually achieved, measured against the disrupted
 * network it started from and against the healthy network before that.
 */
export const Recovery: React.FC<RecoveryProps> = ({
  state,
  solution,
  trace,
  connection,
  working,
  restoring,
  onRestore,
  onInsights,
  onBackToStress,
}) => {
  const report = state?.recovery_report ?? null;
  const impact = state?.impact_report ?? null;

  const vsDisrupted = useMemo(
    () => (report ? compareSnapshots(report.before, report.after) : []),
    [report]
  );
  const vsHealthy = useMemo(
    () => (report && impact ? compareSnapshots(impact.before, report.after) : []),
    [report, impact]
  );

  if (working) {
    return (
      <Analyze
        trace={trace}
        connection={connection}
        working
        phase="recovery"
        regionName={state?.inputs?.region_name}
        onBack={onBackToStress}
        backLabel="Back to the impact"
      />
    );
  }

  if (!report) {
    return (
      <Card>
        <EmptyState
          icon={<Siren className="h-5 w-5" />}
          title="Nothing to recover yet"
          body="Run a scenario against the network first, then repair it here."
          action={
            <Button variant="primary" size="md" onClick={onBackToStress}>
              Go to the stress test
            </Button>
          }
        />
      </Card>
    );
  }

  const names = (ids: string[]) =>
    ids.map((id) => state?.graph?.warehouses.find((w) => w.id === id)?.name ?? id);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="pass" dot>
              recovered
            </Badge>
            <h1 className="font-display text-[1.6rem] font-medium leading-tight tracking-tight text-ink">
              Network Recovered
            </h1>
          </div>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-muted">
            {impact?.title ?? 'The network has been repaired around the disruption.'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="md" onClick={onRestore} loading={restoring}>
            <RotateCcw className="h-3.5 w-3.5" />
            Run another scenario
          </Button>
          <Button variant="primary" size="lg" onClick={onInsights}>
            See the recommendation
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </header>

      <Card className="border-l-[3px] border-l-pass">
        <div className="flex items-start gap-3.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-pass/25 bg-pass-soft text-pass">
            <Zap className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
              Recovery summary
            </p>
            <p className="mt-1.5 text-sm leading-relaxed text-ink">{report.summary}</p>
          </div>
        </div>

        <div className="mt-5 grid gap-3 border-t border-line pt-4 sm:grid-cols-2 lg:grid-cols-4">
          <HeadlineStat
            label="Recovery time"
            value={`${report.recovery_seconds.toFixed(2)}s`}
            hint="From disruption to a re-solved network"
            tone="accent"
          />
          <HeadlineStat
            label="Zones recovered"
            value={num(report.customers_reassigned)}
            hint="Reassigned to a surviving facility"
          />
          <HeadlineStat
            label="Routes changed"
            value={num(report.routes_changed)}
            hint="Lanes that now run somewhere else"
          />
          <HeadlineStat
            label="Cost against the healthy network"
            value={usd(report.added_cost_usd)}
            hint={
              report.added_cost_usd > 0
                ? 'What the repaired network costs on top'
                : report.warehouses_deactivated.length > 0
                  ? `Lower because ${report.warehouses_deactivated.length} ${
                      report.warehouses_deactivated.length === 1 ? 'facility is' : 'facilities are'
                    } offline, so the network also ships less`
                  : 'Lower because the network is shipping less, not because it costs less to run'
            }
            tone={report.added_cost_usd > 0 ? 'warn' : 'neutral'}
          />
        </div>

        {(report.warehouses_activated.length > 0 || report.warehouses_deactivated.length > 0) && (
          <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
            <FacilityChange
              label="Facilities taken offline"
              names={names(report.warehouses_deactivated)}
              tone="danger"
            />
            <FacilityChange
              label="Facilities brought in"
              names={names(report.warehouses_activated)}
              tone="pass"
            />
          </div>
        )}
      </Card>

      <section>
        <h2 className="text-sm font-semibold tracking-tight text-ink">
          Against the disrupted network
        </h2>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted">
          What the repair bought, measured from the moment the disruption hit.
        </p>
        <SnapshotComparison rows={vsDisrupted} className="mt-4" />
      </section>

      {vsHealthy.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold tracking-tight text-ink">
            Against the network before anything went wrong
          </h2>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted">
            How much of the original service the repaired network gets back.
          </p>
          <SnapshotComparison rows={vsHealthy} className="mt-4" />
        </section>
      )}

      <NetworkMap
        graph={state?.graph ?? null}
        candidates={state?.candidates ?? []}
        solution={solution}
        highlightWarehouseIds={impact?.failed_warehouse_ids}
        title="The recovered network"
        subtitle="Facilities that went down stay red; the lanes show where the work moved to."
      />

      {state?.narrative && (
        <Card>
          <CardHeader
            title="What the narrator reports"
            subtitle="Rewritten around the recovered plan."
          />
          <div className="mt-4">
            <Markdown text={state.narrative} />
          </div>
        </Card>
      )}
    </div>
  );
};

const FacilityChange: React.FC<{ label: string; names: string[]; tone: 'pass' | 'danger' }> = ({
  label,
  names,
  tone,
}) => (
  <div className="rounded-lg border border-line bg-sunken px-3.5 py-3">
    <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">{label}</p>
    {names.length === 0 ? (
      <p className="mt-1.5 text-xs text-muted">None.</p>
    ) : (
      <ul className="mt-2 flex flex-wrap gap-1.5">
        {names.map((n) => (
          <li key={n}>
            <Badge tone={tone}>{n}</Badge>
          </li>
        ))}
      </ul>
    )}
  </div>
);
