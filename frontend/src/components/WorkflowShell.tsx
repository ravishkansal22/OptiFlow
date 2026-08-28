import React from 'react';
import { Check, Home as HomeIcon, Lock, MessageSquareText, Moon, Plus, Sun } from 'lucide-react';
import { Button, Mark, Spinner, cn } from './ui';
import { ConnectionPill } from './AgentTrace';
import { DataSourceBanner } from './DataSourceBanner';
import { STAGE_ORDER, type Busy, type Stage } from '../lib/useOptiFlow';
import type { ConnectionStatus } from '../services/websocket';
import type { Theme } from '../lib/theme';
import type { DataSource } from '../types';

/** The seven steps, in the order the workflow runs them. */
export const STAGE_LABELS: Record<Stage, string> = {
  setup: 'Setup',
  analyze: 'Analyze',
  candidates: 'Candidates',
  optimize: 'Optimize',
  stress: 'Stress test',
  recovery: 'Recovery',
  insights: 'Insights',
};

/** Which stage each long-running backend call belongs to. */
const BUSY_STAGE: Record<Exclude<Busy, null>, Stage> = {
  analyzing: 'analyze',
  optimizing: 'optimize',
  disrupting: 'stress',
  recovering: 'recovery',
  restoring: 'stress',
};

export interface WorkflowShellProps {
  stage: Stage;
  reachable: Record<Stage, boolean>;
  busy: Busy;
  onGoTo: (stage: Stage) => void;
  regionName?: string;
  subtitle?: string;
  connection: ConnectionStatus;
  dataSource?: DataSource | null;
  theme: Theme;
  onToggleTheme: () => void;
  onNewNetwork: () => void;
  onHome: () => void;
  onOpenAsk?: () => void;
  askOpen?: boolean;
  askEnabled?: boolean;
  /** Full-bleed screens (the map ones) manage their own padding. */
  wide?: boolean;
  children: React.ReactNode;
}

/**
 * One frame for the whole workflow: the same header everywhere, and a rail that
 * says where the person is without them having to remember which screen is next.
 */
export const WorkflowShell: React.FC<WorkflowShellProps> = ({
  stage,
  reachable,
  busy,
  onGoTo,
  regionName,
  subtitle,
  connection,
  dataSource,
  theme,
  onToggleTheme,
  onNewNetwork,
  onHome,
  onOpenAsk,
  askOpen,
  askEnabled,
  wide,
  children,
}) => {
  const current = STAGE_ORDER.indexOf(stage);
  const busyStage = busy ? BUSY_STAGE[busy] : null;

  return (
    <div className={cn('min-h-[100dvh] transition-[padding] duration-300', askOpen && 'lg:pr-[28rem]')}>
      <header className="sticky top-0 z-30 border-b border-line bg-canvas/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[92rem] items-center gap-4 px-5 py-3 sm:px-8">
          <button
            onClick={onHome}
            title="Back to the start"
            className="flex min-w-0 items-center gap-2.5 rounded-lg px-1 py-0.5 transition-colors hover:bg-sunken focus-ring"
          >
            <Mark />
            <div className="min-w-0 text-left">
              <div className="flex items-baseline gap-2">
                <span className="font-display text-base font-medium leading-none tracking-tight text-ink">
                  OptiFlow
                </span>
                {regionName && (
                  <>
                    <span className="text-faint">/</span>
                    <span className="truncate text-xs text-muted">{regionName}</span>
                  </>
                )}
              </div>
              {subtitle && <p className="mt-0.5 truncate text-2xs text-faint">{subtitle}</p>}
            </div>
          </button>

          <div className="ml-auto flex items-center gap-2">
            <DataSourceBanner data={dataSource ?? null} compact className="hidden md:inline-flex" />
            <ConnectionPill status={connection} className="hidden md:inline-flex" />
            {onOpenAsk && (
              <Button
                variant={askOpen ? 'primary' : 'secondary'}
                size="sm"
                onClick={onOpenAsk}
                disabled={!askEnabled}
                title={
                  askEnabled
                    ? 'Ask about this network'
                    : 'Available once a network has been optimised'
                }
              >
                <MessageSquareText className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Ask</span>
              </Button>
            )}
            <Button variant="secondary" size="sm" onClick={onHome} title="Back to the start">
              <HomeIcon className="h-3.5 w-3.5" />
              <span className="hidden lg:inline">Home</span>
            </Button>
            <Button variant="secondary" size="sm" onClick={onNewNetwork} title="Start a new network">
              <Plus className="h-3.5 w-3.5" />
              <span className="hidden lg:inline">New network</span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              className="px-2"
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </div>

        <nav aria-label="Workflow" className="mx-auto max-w-[92rem] px-5 sm:px-8">
          <ol className="flex items-center gap-0.5 overflow-x-auto pb-2.5 pt-0.5">
            {STAGE_ORDER.map((s, i) => {
              const done = i < current && reachable[s];
              const active = s === stage;
              const working = busyStage === s && !!busy;
              const open = reachable[s] || active;
              return (
                <li key={s} className="flex shrink-0 items-center">
                  {i > 0 && (
                    <span
                      className={cn(
                        'mx-1 h-px w-4 sm:w-6',
                        i <= current ? 'bg-accent/40' : 'bg-line'
                      )}
                    />
                  )}
                  <button
                    onClick={() => open && onGoTo(s)}
                    disabled={!open}
                    aria-current={active ? 'step' : undefined}
                    title={open ? STAGE_LABELS[s] : 'Not available yet'}
                    className={cn(
                      'group flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-2xs font-medium transition-all duration-150 focus-ring',
                      active
                        ? 'border-accent/40 bg-accent-soft text-accent shadow-card'
                        : open
                          ? 'border-transparent text-muted hover:bg-sunken hover:text-ink'
                          : 'cursor-not-allowed border-transparent text-faint'
                    )}
                  >
                    <span
                      className={cn(
                        'flex h-4.5 w-4.5 items-center justify-center rounded-full border text-[9px] leading-none',
                        active
                          ? 'border-accent bg-accent text-white'
                          : done
                            ? 'border-accent/40 bg-accent/15 text-accent'
                            : open
                              ? 'border-strong text-faint'
                              : 'border-line text-faint'
                      )}
                      style={{ height: '1.125rem', width: '1.125rem' }}
                    >
                      {working ? (
                        <Spinner className="h-2.5 w-2.5" />
                      ) : done ? (
                        <Check className="h-2.5 w-2.5" strokeWidth={3} />
                      ) : open ? (
                        i + 1
                      ) : (
                        <Lock className="h-2 w-2" />
                      )}
                    </span>
                    <span className="whitespace-nowrap">{STAGE_LABELS[s]}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>
      </header>

      <main className={cn('mx-auto w-full', wide ? 'max-w-[110rem] px-4 py-5 sm:px-6' : 'max-w-[92rem] px-5 py-7 sm:px-8')}>
        {children}
      </main>
    </div>
  );
};
