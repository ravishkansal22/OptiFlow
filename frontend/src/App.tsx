import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { ResilienceScorecard } from './components/ResilienceScorecard';
import { MapView } from './components/MapView';
import { FrontierChart } from './components/FrontierChart';
import { DisruptionPanel } from './components/DisruptionPanel';
import { LiveTracePanel } from './components/LiveTracePanel';
import { NarratorChat } from './components/NarratorChat';
import { ProvenanceModal } from './components/ProvenanceModal';
import { fetchNetworkState, runOptimization, triggerDisruption, switchSolution, fetchProvenanceHistory } from './services/api';
import { wsClient } from './services/websocket';
import { NetworkStateResponse, NetworkSolution, AgentTraceEvent, ProvenanceTag } from './types';

export const App: React.FC = () => {
  const [state, setState] = useState<NetworkStateResponse | null>(null);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [isDisrupting, setIsDisrupting] = useState(false);
  const [activeSolutionId, setActiveSolutionId] = useState<string>('');
  const [traceEvents, setTraceEvents] = useState<AgentTraceEvent[]>([]);

  // Provenance Modal State
  const [modalState, setModalState] = useState<{
    isOpen: boolean;
    title: string;
    tag?: ProvenanceTag | null;
    rawPayload?: Record<string, any> | null;
  }>({
    isOpen: false,
    title: '',
    tag: null,
    rawPayload: null
  });

  const loadState = async () => {
    try {
      const data = await fetchNetworkState();
      setState(data);
      if (data.active_solution_id) {
        setActiveSolutionId(data.active_solution_id);
      }
      if (data.trace_events) {
        setTraceEvents(data.trace_events);
      }
    } catch (err) {
      console.error('Error loading initial network state:', err);
    }
  };

  useEffect(() => {
    loadState();
    wsClient.connect();

    const unsubTrace = wsClient.onTrace((event: AgentTraceEvent) => {
      setTraceEvents((prev) => [...prev, event]);
    });

    const unsubSignal = wsClient.onSignal((payload: any) => {
      if (payload.type === 'pipeline_complete' || payload.type === 'disruption_resolved' || payload.type === 'solution_switched') {
        loadState();
        setIsOptimizing(false);
        setIsDisrupting(false);
      }
    });

    return () => {
      unsubTrace();
      unsubSignal();
    };
  }, []);

  const handleRunOptimization = async () => {
    setIsOptimizing(true);
    try {
      await runOptimization();
    } catch (err) {
      console.error(err);
      setIsOptimizing(false);
    }
  };

  const handleTriggerDisruption = async (scenarioType: string) => {
    setIsDisrupting(true);
    try {
      await triggerDisruption(scenarioType);
      await loadState();
    } catch (err) {
      console.error(err);
    } finally {
      setIsDisrupting(false);
    }
  };

  const handleSelectSolution = async (solId: string) => {
    setActiveSolutionId(solId);
    try {
      await switchSolution(solId);
      await loadState();
    } catch (err) {
      console.error(err);
    }
  };

  const handleInspectProvenance = (title: string, tag?: ProvenanceTag | null, payload?: any) => {
    setModalState({
      isOpen: true,
      title,
      tag: tag || null,
      rawPayload: payload || null
    });
  };

  const handleOpenProvenanceHistory = async () => {
    try {
      const data = await fetchProvenanceHistory();
      setModalState({
        isOpen: true,
        title: `Mireye Gateway Audit History (${data.call_count} Calls)`,
        tag: null,
        rawPayload: { total_calls: data.call_count, recent_history: data.history }
      });
    } catch (err) {
      console.error(err);
    }
  };

  const activeSolution = state?.frontier.find((s) => s.solution_id === (activeSolutionId || state.active_solution_id)) || (state?.frontier[0] || null);
  const baselineSolution = state?.frontier.find((s) => s.is_baseline_cost_only) || (state?.frontier[0] || null);
  const isDisrupted = (state?.disruption_log && state.disruption_log.length > 0) || false;

  return (
    <div className="min-h-screen bg-[#080C14] text-slate-100 flex flex-col selection:bg-emerald-500 selection:text-white">
      {/* 1. Header */}
      <Header
        regionName={state?.inputs.region_name || 'Puget Sound Logistics Corridor'}
        isOptimizing={isOptimizing}
        isDisrupted={isDisrupted}
        onRunOptimization={handleRunOptimization}
        onOpenDisruptionModal={() => handleTriggerDisruption('flood_green_river')}
        onOpenProvenanceHistory={handleOpenProvenanceHistory}
      />

      {/* 2. Main Content Dashboard */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Top Resilience & Financials Scorecard */}
        <ResilienceScorecard
          activeSolution={activeSolution}
          baselineSolution={baselineSolution}
          criticReport={state?.critic_report || null}
          candidateCount={state?.candidates.length || 0}
          onInspectMetric={(title, data) => handleInspectProvenance(title, null, data)}
        />

        {/* Mid Row: Spatial Logistics Map & Live Trace Feed */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Spatial Logistics Map */}
          <div className="lg:col-span-7">
            <MapView
              graph={state?.graph || null}
              candidates={state?.candidates || []}
              activeSolution={activeSolution}
              onInspectNode={(title, data, tag) => handleInspectProvenance(title, tag, data)}
            />
          </div>

          {/* Live Agent Trace Stream */}
          <div className="lg:col-span-5">
            <LiveTracePanel
              events={traceEvents}
              onInspectProvenance={(title, tag, payload) => handleInspectProvenance(title, tag, payload)}
            />
          </div>
        </div>

        {/* Lower Row: NSGA-II Pareto Frontier & Disruption Panel */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Pareto Frontier Chart */}
          <div className="lg:col-span-7">
            <FrontierChart
              frontier={state?.frontier || []}
              activeSolutionId={activeSolution?.solution_id || ''}
              onSelectSolution={handleSelectSolution}
            />
          </div>

          {/* Disruption Simulator & Sub-60s Recovery */}
          <div className="lg:col-span-5">
            <DisruptionPanel
              disruptions={state?.disruption_log || []}
              activeSolution={activeSolution}
              baselineSolution={baselineSolution}
              onTriggerDisruption={handleTriggerDisruption}
              isLoading={isDisrupting}
            />
          </div>
        </div>

        {/* Bottom Row: Executive Intelligence Narrative & Narrator AI Assistant */}
        <NarratorChat
          narrativeText={state?.narrative || ''}
          onInspectProvenance={(title, tag, payload) => handleInspectProvenance(title, tag, payload)}
        />
      </main>

      {/* 3. Clickable Provenance Inspector Modal */}
      <ProvenanceModal
        isOpen={modalState.isOpen}
        onClose={() => setModalState((prev) => ({ ...prev, isOpen: false }))}
        title={modalState.title}
        tag={modalState.tag}
        rawPayload={modalState.rawPayload}
      />

      {/* Footer */}
      <footer className="w-full border-t border-surface-border/60 py-4 px-6 text-center text-xs text-slate-500 flex items-center justify-between max-w-7xl mx-auto">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-400" />
          <span>OptiFlow Core 1.0 • 10-Agent LangGraph State Machine</span>
        </div>
        <div className="text-slate-400">
          Mireye Gateway • OR-Tools MILP • pymoo NSGA-II • Redis Geohash-7
        </div>
      </footer>
    </div>
  );
};

export default App;
