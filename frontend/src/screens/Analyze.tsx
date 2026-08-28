import React, { useMemo } from 'react';
import { Activity, ArrowLeft } from 'lucide-react';
import { Button, Card, CardHeader, Spinner, cn } from '../components/ui';
import {
  AgentChecklist,
  LiveAgentActivity,
  PHASE_AGENTS,
  TraceLog,
  friendlyAgent,
} from '../components/AgentTrace';
import type { AgentTraceEvent } from '../types';
import type { ConnectionStatus } from '../services/websocket';

export interface AnalyzeProps {
  trace: AgentTraceEvent[];
  connection: ConnectionStatus;
  working: boolean;
  regionName?: string;
  /** 'analyze' while screening, 'optimize' while the solver runs. */
  phase?: 'analyze' | 'optimize' | 'recovery';
  onBack?: () => void;
  backLabel?: string;
}

const HEADLINES: Record<'analyze' | 'optimize' | 'recovery', { title: string; body: string }> = {
  analyze: {
    title: 'OptiFlow is analyzing your network',
    body: 'Every site is checked against real terrain, land cover and flood data, then drive times are measured across the whole region. Nothing here needs your input.',
  },
  optimize: {
    title: 'OptiFlow is building your network',
    body: 'The solver is choosing facilities and flows, then sweeping the cost-versus-resilience frontier for the alternatives worth comparing.',
  },
  recovery: {
    title: 'OptiFlow is recovering your network',
    body: 'Affected zones are being reassigned to surviving facilities and re-routed, then the result is audited before it is shown.',
  },
};

/**
 * The waiting room, and the one place the agent work is visible as it happens.
 * Every line on this screen is an event the backend actually emitted.
 */
export const Analyze: React.FC<AnalyzeProps> = ({
  trace,
  connection,
  working,
  regionName,
  phase = 'analyze',
  onBack,
  backLabel = 'Change the setup',
}) => {
  const copy = HEADLINES[phase];
  const expected = PHASE_AGENTS[phase];

  // Headline detail comes from the newest event of this phase, so it says what
  // is happening now rather than repeating the phase before it.
  const latest = useMemo(() => {
    for (let i = trace.length - 1; i >= 0; i--) {
      if (expected.includes(trace[i].agent_name)) return trace[i];
    }
    return null;
  }, [trace, expected]);

  // Counts the agents reported on their own events.
  const tally = useMemo(() => {
    let screened = 0;
    let qualified: number | null = null;
    let edges: number | null = null;
    for (const e of trace) {
      const d = e.details ?? {};
      if (e.action === 'CandidateScreened') screened += 1;
      if (typeof d.qualified_candidates === 'number') qualified = d.qualified_candidates;
      if (typeof d.surviving_count === 'number' && qualified == null) qualified = d.surviving_count;
      // The route agent reports progress as it measures, then a final count.
      if (typeof d.measured === 'number') edges = d.measured;
      if (typeof d.edges_count === 'number') edges = d.edges_count;
    }
    return { screened, qualified, edges };
  }, [trace]);

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start xl:gap-12">
      <div className="animate-fade-up">
        <div className="flex items-center gap-2 text-2xs font-medium uppercase tracking-[0.1em] text-muted">
          {working ? <Spinner className="h-3 w-3 text-accent" /> : null}
          {working ? 'Working' : 'Finished'}
          {regionName && <span className="text-faint">· {regionName}</span>}
        </div>

        <h1 className="mt-4 font-display text-[1.9rem] font-medium leading-[1.15] tracking-tight text-ink sm:text-[2.3rem]">
          {copy.title}
        </h1>
        <p className="mt-3 max-w-lg text-sm leading-relaxed text-muted">{copy.body}</p>

        {latest && (
          <p className="mt-4 flex items-start gap-2 rounded-lg border border-line bg-sunken px-3.5 py-3 text-xs leading-relaxed text-muted">
            <Activity className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
            <span>
              <span className="font-medium text-ink">{friendlyAgent(latest.agent_name)}</span> —{' '}
              {latest.message}
            </span>
          </p>
        )}

        <AgentChecklist trace={trace} expected={expected} className="mt-7" />

        {(tally.screened > 0 || tally.edges != null) && (
          <dl className="mt-6 grid grid-cols-3 gap-3 border-t border-line pt-5">
            <Tally label="Sites screened" value={tally.screened} />
            <Tally label="Sites viable" value={tally.qualified} />
            <Tally label="Routes measured" value={tally.edges} />
          </dl>
        )}

        {onBack && (
          <Button variant="ghost" size="sm" onClick={onBack} className="mt-7">
            <ArrowLeft className="h-3.5 w-3.5" />
            {backLabel}
          </Button>
        )}
      </div>

      <div className="space-y-5">
        <Card className="animate-fade-up [animation-delay:60ms]">
          <CardHeader
            title="Live agent activity"
            subtitle="The most recent report from each agent working on this network."
            action={
              <span
                className={cn(
                  'num text-2xs',
                  connection === 'open' ? 'text-pass' : connection === 'connecting' ? 'text-warn' : 'text-faint'
                )}
              >
                {connection === 'open' ? 'streaming' : connection}
              </span>
            }
          />
          <LiveAgentActivity trace={trace} agents={expected} className="mt-4" />
        </Card>

        <Card flush className="animate-fade-up [animation-delay:120ms]">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <span className="num font-mono text-2xs text-muted">/ws/trace</span>
            <span className="num text-2xs text-faint">{trace.length} events</span>
          </div>
          <TraceLog trace={trace} className="h-[22rem] px-4 py-3 lg:h-[26rem]" />
        </Card>
      </div>
    </div>
  );
};

const Tally: React.FC<{ label: string; value: number | null }> = ({ label, value }) => (
  <div>
    <dt className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">{label}</dt>
    <dd className="num mt-1 font-display text-2xl font-medium leading-none tracking-tight text-ink">
      {value == null ? '—' : value}
    </dd>
  </div>
);
