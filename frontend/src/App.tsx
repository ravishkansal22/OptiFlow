import React from 'react';
import { AlertTriangle, Trash2, X } from 'lucide-react';
import { Button, Mark, Spinner, cn } from './components/ui';
import { WorkflowShell } from './components/WorkflowShell';
import { AskDrawer } from './panels/AskDrawer';
import { Landing } from './screens/Landing';
import { Setup } from './screens/Setup';
import { Analyze } from './screens/Analyze';
import { Candidates } from './screens/Candidates';
import { Optimize } from './screens/Optimize';
import { StressTest } from './screens/StressTest';
import { Recovery } from './screens/Recovery';
import { Insights } from './screens/Insights';
import { SiteCheckScreen } from './screens/SiteCheckScreen';
import { activeSolution, hasResults, hubFeasibility, recommendedSolution } from './lib/domain';
import { useTheme } from './lib/theme';
import { useOptiFlow } from './lib/useOptiFlow';
import { usdShort } from './lib/format';
import type { EvaluateSitesResponse, SiteInput } from './types';

/** Which of the three surfaces is on screen, independent of the workflow stage. */
type View = 'landing' | 'workflow' | 'sitecheck';

export const App: React.FC = () => {
  const store = useOptiFlow();
  const { theme, toggle } = useTheme();
  const {
    phase,
    stage,
    state,
    region,
    scenarios,
    trace,
    connection,
    dataSource,
    busy,
    error,
    reachable,
    goTo,
    startNew,
    analyze,
    optimize,
    disrupt,
    recover,
    restore,
    selectSolution,
    dismissError,
  } = store;

  const [view, setView] = React.useState<View>('landing');
  const [notice, setNotice] = React.useState<string | null>(null);
  const [askOpen, setAskOpen] = React.useState(false);
  const [resetToken, setResetToken] = React.useState(0);
  const [, setLastCheck] = React.useState<EvaluateSitesResponse | null>(null);

  const solution = React.useMemo(() => activeSolution(state), [state]);
  // After a recovery the active plan describes the repaired network, while the
  // recommendation is still the design the run produced.
  const recommended = React.useMemo(() => recommendedSolution(state), [state]);
  const solved = hasResults(state);

  const goHome = React.useCallback(() => {
    setNotice(null);
    setAskOpen(false);
    setView('landing');
  }, []);

  const openWorkflow = React.useCallback(() => setView('workflow'), []);

  const newNetwork = React.useCallback(() => {
    startNew();
    setView('workflow');
  }, [startNew]);

  const runReset = React.useCallback(() => {
    store
      .resetAll()
      .then((msg) => {
        setResetToken((t) => t + 1);
        setLastCheck(null);
        setNotice(msg);
      })
      .catch(() => undefined);
  }, [store]);

  // Sites screened on their own can be carried straight into a run.
  const analyzeWithSites = React.useCallback(
    (sites: SiteInput[]) => {
      setView('workflow');
      analyze({
        region_name: store.lastRunParams?.region_name ?? state?.inputs?.region_name,
        target_warehouses:
          store.lastRunParams?.target_warehouses ?? state?.inputs?.target_warehouses_to_open,
        service_radius_minutes:
          store.lastRunParams?.service_radius_minutes ?? state?.inputs?.service_radius_minutes,
        budget_limit_usd: store.lastRunParams?.budget_limit_usd ?? state?.inputs?.budget_limit_usd,
        optimization_preference:
          store.lastRunParams?.optimization_preference ?? state?.inputs?.optimization_preference,
        min_demand_coverage_pct:
          store.lastRunParams?.min_demand_coverage_pct ?? state?.inputs?.min_demand_coverage_pct,
        custom_sites: sites,
      });
    },
    [analyze, store.lastRunParams, state]
  );

  if (phase === 'booting') return <Booting />;
  if (phase === 'offline') return <Offline message={error} />;

  const subtitle = solution
    ? `${solution.selected_warehouse_ids.length} warehouses · ${usdShort(solution.total_cost)} a year · ${Math.round(solution.demand_retained_pct)}% coverage`
    : undefined;

  return (
    <>
      {view === 'landing' && (
        <Landing
          store={store}
          theme={theme}
          onToggleTheme={toggle}
          onCreate={newNetwork}
          onOpenNetwork={openWorkflow}
          onCheckLocations={() => setView('sitecheck')}
        />
      )}

      {view === 'sitecheck' && (
        <SiteCheckScreen
          onBack={goHome}
          regionName={state?.inputs?.region_name}
          dataSource={dataSource}
          onReset={runReset}
          resetting={store.resetting}
          resetToken={resetToken}
          onOpenPlan={solved ? openWorkflow : undefined}
          onResult={setLastCheck}
          theme={theme}
          onToggleTheme={toggle}
          onOptimise={analyzeWithSites}
        />
      )}

      {view === 'workflow' && (
        <WorkflowShell
          stage={stage}
          reachable={reachable}
          busy={busy}
          onGoTo={goTo}
          regionName={state?.inputs?.region_name}
          subtitle={subtitle}
          connection={connection}
          dataSource={dataSource}
          theme={theme}
          onToggleTheme={toggle}
          onNewNetwork={newNetwork}
          onHome={goHome}
          onOpenAsk={() => setAskOpen((v) => !v)}
          askOpen={askOpen}
          askEnabled={solved}
          wide={stage === 'candidates' || stage === 'optimize' || stage === 'recovery'}
        >
          <div key={stage} className="animate-fade-up">
            {stage === 'setup' && (
              <Setup
                region={region}
                defaults={state?.inputs ?? null}
                previous={store.lastRunParams}
                feasibility={state?.graph ? hubFeasibility(state.graph) : null}
                busy={busy === 'analyzing'}
                onAnalyze={analyze}
                onScreenSites={() => setView('sitecheck')}
              />
            )}

            {stage === 'analyze' && (
              <Analyze
                trace={trace}
                connection={connection}
                working={busy === 'analyzing'}
                regionName={state?.inputs?.region_name}
                phase="analyze"
                onBack={() => goTo('setup')}
              />
            )}

            {stage === 'candidates' && (
              <Candidates
                candidates={state?.candidates ?? []}
                graph={state?.graph ?? null}
                solution={solution}
                budgetLimit={state?.inputs?.budget_limit_usd}
                busy={busy === 'optimizing'}
                onOptimize={optimize}
              />
            )}

            {stage === 'optimize' && (
              <Optimize
                state={state}
                solution={solution}
                trace={trace}
                connection={connection}
                working={busy === 'optimizing'}
                switching={store.switching}
                onSelectSolution={selectSolution}
                onStressTest={() => goTo('stress')}
                onBackToCandidates={() => goTo('candidates')}
                onChangeSetup={() => goTo('setup')}
              />
            )}

            {stage === 'stress' && (
              <StressTest
                state={state}
                solution={solution}
                scenarios={scenarios}
                busy={busy === 'disrupting' || busy === 'recovering'}
                restoring={busy === 'restoring'}
                onDisrupt={disrupt}
                onRecover={recover}
                onRestore={restore}
              />
            )}

            {stage === 'recovery' && (
              <Recovery
                state={state}
                solution={solution}
                trace={trace}
                connection={connection}
                working={busy === 'recovering'}
                restoring={busy === 'restoring'}
                onRestore={restore}
                onInsights={() => goTo('insights')}
                onBackToStress={() => goTo('stress')}
              />
            )}

            {stage === 'insights' && (
              <Insights
                state={state}
                solution={recommended}
                running={solution}
                trace={trace}
                connection={connection}
                onRunScenario={() => goTo('stress')}
                onAsk={() => setAskOpen(true)}
              />
            )}
          </div>
        </WorkflowShell>
      )}

      {view === 'workflow' && (
        <AskDrawer
          open={askOpen}
          onClose={() => setAskOpen(false)}
          candidates={state?.candidates ?? []}
          warehouseNames={(state?.graph?.warehouses ?? [])
            .filter((w) => solution?.selected_warehouse_ids.includes(w.id))
            .map((w) => w.name)}
          ready={solved}
        />
      )}

      {error && <ErrorToast message={error} onDismiss={dismissError} />}
      {notice && !error && <Notice message={notice} onDismiss={() => setNotice(null)} />}
    </>
  );
};

/* --------------------------------------------------------------- screens */

const Booting: React.FC = () => (
  <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-4">
    <Mark className="h-7 w-7" />
    <div className="flex items-center gap-2 text-xs text-muted">
      <Spinner className="h-3.5 w-3.5 text-accent" />
      Starting up&hellip;
    </div>
  </div>
);

const Offline: React.FC<{ message: string | null }> = ({ message }) => (
  <div className="flex min-h-[100dvh] flex-col items-center justify-center px-6">
    <div className="w-full max-w-md animate-fade-up rounded-2xl border border-line bg-surface p-7 shadow-lift">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl border border-warn/25 bg-warn-soft text-warn">
        <AlertTriangle className="h-4 w-4" />
      </span>
      <h1 className="mt-4 font-display text-xl font-medium tracking-tight text-ink">
        Cannot reach the server
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        {message ?? 'The OptiFlow server is not answering.'}
      </p>
      <div className="mt-5 rounded-lg border border-line bg-sunken p-3.5">
        <p className="text-2xs font-medium uppercase tracking-[0.08em] text-faint">
          Start it by running
        </p>
        <code className="num mt-2 block font-mono text-2xs text-ink">python server.py</code>
      </div>
      <Button
        variant="primary"
        size="md"
        className="mt-5 w-full"
        onClick={() => window.location.reload()}
      >
        Try again
      </Button>
    </div>
  </div>
);

const Notice: React.FC<{ message: string; onDismiss: () => void }> = ({ message, onDismiss }) => (
  <Toast icon={<Trash2 className="mt-0.5 h-4 w-4 shrink-0 text-accent" />} onDismiss={onDismiss}>
    {message}
  </Toast>
);

const ErrorToast: React.FC<{ message: string; onDismiss: () => void }> = ({
  message,
  onDismiss,
}) => (
  <Toast
    icon={<AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />}
    onDismiss={onDismiss}
    danger
  >
    {message}
  </Toast>
);

const Toast: React.FC<{
  icon: React.ReactNode;
  onDismiss: () => void;
  danger?: boolean;
  children: React.ReactNode;
}> = ({ icon, onDismiss, danger, children }) => (
  <div className="fixed bottom-5 left-1/2 z-50 w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 animate-fade-up">
    <div
      className={cn(
        'flex items-start gap-3 rounded-xl border bg-surface p-3.5 shadow-pop',
        danger ? 'border-danger/25' : 'border-line'
      )}
    >
      {icon}
      <p className="flex-1 text-xs leading-relaxed text-ink">{children}</p>
      <button
        onClick={onDismiss}
        aria-label="Close"
        className="shrink-0 rounded p-0.5 text-faint transition-colors hover:text-ink focus-ring"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  </div>
);

export default App;
