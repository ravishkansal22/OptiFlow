import React, { useEffect, useMemo, useRef } from 'react';
import { AlertTriangle, Check, Loader2, Radio } from 'lucide-react';
import { Spinner, cn } from './ui';
import { clockTime, titleCase } from '../lib/format';
import type { AgentTraceEvent } from '../types';
import type { ConnectionStatus } from '../services/websocket';

/* --------------------------------------------------------------- naming */

/**
 * Agent names are an implementation detail of the backend; these are what each
 * one is doing in the user's terms. Anything unmapped falls through to the name
 * the backend sent, so a new agent still shows up rather than disappearing.
 */
const AGENT_LABELS: Record<string, string> = {
  'Site Generation Agent': 'Screening the ground',
  'Risk Agent': 'Assessing geographic risk',
  'Route / Graph Builder Agent': 'Building the transportation network',
  'Optimization Agent': 'Optimizing the network',
  'Critic Agent': 'Verifying the answer',
  'Reporting / Narrator Agent': 'Writing the report',
  'Disaster Simulation Agent': 'Simulating the disruption',
  'Recovery / Verification Agent': 'Recovering the network',
  'Mireye Gateway Agent': 'Fetching geographic intelligence',
};

/** Short forms for the activity panel, where space is tight. */
const AGENT_SHORT: Record<string, string> = {
  'Site Generation Agent': 'SITE AGENT',
  'Risk Agent': 'RISK AGENT',
  'Route / Graph Builder Agent': 'ROUTE AGENT',
  'Optimization Agent': 'OPTIMIZER',
  'Critic Agent': 'CRITIC',
  'Reporting / Narrator Agent': 'NARRATOR',
  'Disaster Simulation Agent': 'DISASTER AGENT',
  'Recovery / Verification Agent': 'RECOVERY AGENT',
  'Mireye Gateway Agent': 'MIREYE',
};

export const friendlyAgent = (name: string) => AGENT_LABELS[name] ?? name;
export const shortAgent = (name: string) => AGENT_SHORT[name] ?? name.toUpperCase();

/**
 * The agents each phase of the pipeline runs, in order. This mirrors the graphs
 * compiled in agents/controller_agent.py, and is only used to show what has not
 * started yet -- every status comes from real trace events.
 */
export const PHASE_AGENTS: Record<'analyze' | 'optimize' | 'recovery', string[]> = {
  analyze: ['Site Generation Agent', 'Risk Agent', 'Route / Graph Builder Agent'],
  optimize: ['Optimization Agent', 'Critic Agent', 'Reporting / Narrator Agent'],
  recovery: [
    'Disaster Simulation Agent',
    'Recovery / Verification Agent',
    'Critic Agent',
    'Reporting / Narrator Agent',
  ],
};

/* ------------------------------------------------------------- checklist */

export type StepState = 'pending' | 'running' | 'done' | 'failed';

export interface AgentStep {
  agent: string;
  state: StepState;
  message: string;
  events: number;
}

/** Every agent any phase is known to run, used to spot ones we do not know about. */
const KNOWN_AGENTS = new Set(Object.values(PHASE_AGENTS).flat());

/**
 * Folds the trace into one row per agent of this phase. An agent with no events
 * yet is pending; the last one to report is running until it completes.
 *
 * The trace holds every phase of the run, so rows are limited to the agents this
 * phase runs -- plus any agent the frontend does not know about, which keeps a
 * newly added backend agent visible rather than silently dropped.
 */
export function deriveSteps(trace: AgentTraceEvent[], expected: string[]): AgentStep[] {
  const seen = new Map<string, AgentStep>();
  const order: string[] = [];
  const inPhase = (agent: string) => expected.includes(agent) || !KNOWN_AGENTS.has(agent);

  for (const e of trace) {
    if (!inPhase(e.agent_name)) continue;
    if (!seen.has(e.agent_name)) {
      order.push(e.agent_name);
      seen.set(e.agent_name, { agent: e.agent_name, state: 'running', message: e.message, events: 0 });
    }
    const row = seen.get(e.agent_name)!;
    row.events += 1;
    row.message = e.message;
    if (e.status === 'complete') row.state = 'done';
    if (e.status === 'error') row.state = 'failed';
  }

  // Anything the expected list mentions but the trace has not reached yet.
  const names = [...order, ...expected.filter((a) => !seen.has(a))];
  const rows = names.map(
    (agent) => seen.get(agent) ?? { agent, state: 'pending' as StepState, message: '', events: 0 }
  );

  // An agent that reported before a later one necessarily finished.
  const lastReported = order.length ? names.indexOf(order[order.length - 1]) : -1;
  rows.forEach((row, i) => {
    if (row.state === 'failed') return;
    if (i < lastReported) row.state = 'done';
    else if (i === lastReported && row.state !== 'done') row.state = 'running';
  });

  return rows;
}

export const AgentChecklist: React.FC<{
  trace: AgentTraceEvent[];
  expected: string[];
  className?: string;
}> = ({ trace, expected, className }) => {
  const steps = useMemo(() => deriveSteps(trace, expected), [trace, expected]);

  return (
    <ol className={cn('space-y-0.5', className)}>
      {steps.map((s) => (
        <li
          key={s.agent}
          className={cn(
            'flex items-start gap-3.5 rounded-lg px-3 py-2.5 transition-colors duration-300',
            s.state === 'running' && 'bg-accent-soft'
          )}
        >
          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
            {s.state === 'failed' ? (
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-danger text-white">
                <AlertTriangle className="h-3 w-3" />
              </span>
            ) : s.state === 'done' ? (
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white">
                <Check className="h-3 w-3" strokeWidth={3} />
              </span>
            ) : s.state === 'running' ? (
              <Loader2 className="h-4 w-4 animate-spin text-accent" />
            ) : (
              <span className="h-3.5 w-3.5 rounded-full border border-strong" />
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span
              className={cn(
                'block text-sm font-medium',
                s.state === 'failed'
                  ? 'text-danger'
                  : s.state === 'pending'
                    ? 'text-faint'
                    : 'text-ink'
              )}
            >
              {friendlyAgent(s.agent)}
            </span>
            {s.state !== 'pending' && (
              <span className="num mt-0.5 block truncate text-2xs text-faint" title={s.message}>
                {s.events} {s.events === 1 ? 'event' : 'events'}
                {s.state === 'running' ? ' · in progress' : ''}
              </span>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
};

/* -------------------------------------------------------- live activity */

/** The latest thing each agent said, newest agent first. */
export const LiveAgentActivity: React.FC<{
  trace: AgentTraceEvent[];
  /** When given, only these agents are shown. */
  agents?: string[];
  className?: string;
}> = ({ trace, agents, className }) => {
  const rows = useMemo(() => {
    const latest = new Map<string, AgentTraceEvent>();
    for (const e of trace) {
      if (agents && agents.length && !agents.includes(e.agent_name) && KNOWN_AGENTS.has(e.agent_name))
        continue;
      latest.set(e.agent_name, e);
    }
    return [...latest.values()].reverse();
  }, [trace, agents]);

  if (!rows.length) {
    return (
      <p className={cn('text-xs text-faint', className)}>
        No agent has reported yet. Activity appears here as soon as the first one does.
      </p>
    );
  }

  return (
    <ul className={cn('space-y-3', className)}>
      {rows.map((e) => (
        <li key={e.agent_name} className="animate-slide-in">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'h-1.5 w-1.5 shrink-0 rounded-full',
                STATUS_DOT[e.status] ?? 'bg-faint',
                e.status === 'progress' || e.status === 'start' ? 'animate-pulse' : ''
              )}
            />
            <span className="num text-2xs font-semibold tracking-[0.06em] text-ink">
              {shortAgent(e.agent_name)}
            </span>
            {e.timestamp && (
              <span className="num ml-auto shrink-0 font-mono text-2xs text-faint">
                {clockTime(e.timestamp)}
              </span>
            )}
          </div>
          <p className="mt-1 pl-3.5 text-xs leading-relaxed text-muted">{e.message}</p>
        </li>
      ))}
    </ul>
  );
};

/* ----------------------------------------------------------- raw stream */

const STATUS_DOT: Record<string, string> = {
  start: 'bg-info',
  progress: 'bg-accent',
  complete: 'bg-pass',
  warning: 'bg-warn',
  error: 'bg-danger',
};

export const TraceLine: React.FC<{ event: AgentTraceEvent }> = ({ event }) => (
  <li className="animate-slide-in">
    <div className="flex items-center gap-2">
      <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', STATUS_DOT[event.status] ?? 'bg-faint')} />
      <span className="truncate text-2xs font-medium text-ink">{friendlyAgent(event.agent_name)}</span>
      <span className="num shrink-0 font-mono text-2xs text-faint">{titleCase(event.action)}</span>
      {event.timestamp && (
        <span className="num ml-auto shrink-0 font-mono text-2xs text-faint">
          {clockTime(event.timestamp)}
        </span>
      )}
    </div>
    <p className="mt-1 pl-3.5 text-xs leading-relaxed text-muted">{event.message}</p>
  </li>
);

/** The raw event stream, scrolled to the newest line. */
export const TraceLog: React.FC<{
  trace: AgentTraceEvent[];
  limit?: number;
  className?: string;
}> = ({ trace, limit = 60, className }) => {
  const ref = useRef<HTMLDivElement>(null);
  const recent = trace.slice(-limit);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' });
  }, [trace.length]);

  return (
    <div ref={ref} className={cn('overflow-y-auto', className)}>
      {recent.length === 0 ? (
        <div className="flex h-full items-center justify-center text-xs text-faint">
          No events received yet.
        </div>
      ) : (
        <ul className="space-y-2.5">
          {recent.map((e) => (
            <TraceLine key={e.event_id} event={e} />
          ))}
        </ul>
      )}
    </div>
  );
};

/* ------------------------------------------------------ connection pill */

export const ConnectionPill: React.FC<{ status: ConnectionStatus; className?: string }> = ({
  status,
  className,
}) => {
  const map = {
    open: { label: 'Live', cls: 'text-pass', dot: 'bg-pass' },
    connecting: { label: 'Connecting', cls: 'text-warn', dot: 'bg-warn animate-pulse' },
    closed: { label: 'Offline', cls: 'text-faint', dot: 'bg-faint' },
  }[status];

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-2xs font-medium',
        map.cls,
        className
      )}
      title={`Trace socket: ${map.label.toLowerCase()}`}
    >
      <Radio className="h-3 w-3" />
      <span className={cn('h-1.5 w-1.5 rounded-full', map.dot)} />
      {map.label}
    </span>
  );
};

/** A small inline "still working" marker for headers. */
export const WorkingPill: React.FC<{ label: string; className?: string }> = ({ label, className }) => (
  <span
    className={cn(
      'inline-flex items-center gap-1.5 rounded-md border border-accent/25 bg-accent-soft px-2 py-1 text-2xs font-medium text-accent',
      className
    )}
  >
    <Spinner className="h-3 w-3" />
    {label}
  </span>
);
