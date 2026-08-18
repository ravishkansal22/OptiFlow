import React, { useState } from 'react';
import { AlertTriangle, ShieldCheck, Zap, Waves, Construction, HeartPulse, CheckCircle2, ArrowRight, Clock } from 'lucide-react';
import { Disruption, NetworkSolution } from '../types';

interface DisruptionPanelProps {
  disruptions: Disruption[];
  activeSolution: NetworkSolution | null;
  baselineSolution: NetworkSolution | null;
  onTriggerDisruption: (scenarioType: string) => Promise<void>;
  isLoading: boolean;
}

export const DisruptionPanel: React.FC<DisruptionPanelProps> = ({
  disruptions,
  activeSolution,
  baselineSolution,
  onTriggerDisruption,
  isLoading
}) => {
  const [selectedScenario, setSelectedScenario] = useState('flood_green_river');

  const scenarios = [
    {
      id: 'flood_green_river',
      title: '100-Yr Green River Valley Flood',
      type: 'Flood Zone AE Inundation',
      desc: 'Mireye flood layers detect heavy atmospheric river inundating low-elevation facilities in Green River basin (Kent South / Fife).',
      icon: Waves,
      color: 'text-cyan-400 border-cyan-500/30 bg-cyan-500/10'
    },
    {
      id: 'road_closure_corridor',
      title: 'I-5 / I-405 Interchange Cut',
      type: 'Corridor Structural Closure',
      desc: 'Major highway infrastructure collapse severing primary north-south freight arterial routes between Seattle and Tacoma.',
      icon: Construction,
      color: 'text-amber-400 border-amber-500/30 bg-amber-500/10'
    },
    {
      id: 'surge_demand',
      title: 'Critical Emergency Demand Surge',
      type: '45% Medical Volume Surge',
      desc: 'Regional health crisis spikes medical demand across Puget Sound hospitals by +45%, stressing warehouse throughput.',
      icon: HeartPulse,
      color: 'text-rose-400 border-rose-500/30 bg-rose-500/10'
    }
  ];

  const latestDisruption = disruptions.length > 0 ? disruptions[disruptions.length - 1] : null;

  return (
    <div className="p-5 rounded-2xl glass-panel border border-surface-border flex flex-col space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-border/70 pb-3">
        <div className="flex items-center space-x-2">
          <div className="p-1.5 rounded-lg bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Disaster Simulation & Sub-60s Recovery
            </h3>
            <p className="text-[11px] text-slate-400">
              Grounded environmental stressors using live Mireye flood and road network layers
            </p>
          </div>
        </div>

        {/* Sub-60s Badge */}
        <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-[11px] text-emerald-300 font-mono">
          <Zap className="w-3.5 h-3.5 text-emerald-400 fill-emerald-400" />
          <span>Warm-Started Re-Solve &lt; 60s</span>
        </div>
      </div>

      {/* Scenario Pickers */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {scenarios.map((sc) => {
          const Icon = sc.icon;
          const isSelected = selectedScenario === sc.id;

          return (
            <div
              key={sc.id}
              onClick={() => setSelectedScenario(sc.id)}
              className={`p-3.5 rounded-xl cursor-pointer border transition-all ${
                isSelected
                  ? 'bg-surface-elevated border-emerald-500/60 shadow-lg glow-emerald'
                  : 'bg-surface/50 border-surface-border hover:border-slate-600'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className={`p-1.5 rounded-lg border ${sc.color}`}>
                  <Icon className="w-4 h-4" />
                </div>
                {isSelected && <span className="w-2 h-2 rounded-full bg-emerald-400" />}
              </div>
              <h4 className="text-xs font-bold text-white">{sc.title}</h4>
              <p className="text-[10px] text-slate-400 mt-1 line-clamp-2">{sc.desc}</p>
            </div>
          );
        })}
      </div>

      {/* Trigger Button */}
      <div className="flex items-center justify-between pt-1">
        <span className="text-xs text-slate-400">
          Selected Stressor: <span className="text-slate-200 font-medium">{scenarios.find(s => s.id === selectedScenario)?.title}</span>
        </span>
        <button
          onClick={() => onTriggerDisruption(selectedScenario)}
          disabled={isLoading}
          className="flex items-center space-x-2 px-5 py-2 rounded-xl bg-gradient-to-r from-rose-600 to-amber-600 hover:from-rose-500 hover:to-amber-500 text-xs font-bold text-white shadow-lg shadow-rose-600/30 transition-all disabled:opacity-50"
        >
          <Zap className="w-4 h-4 fill-current" />
          <span>{isLoading ? 'Simulating & Re-Optimizing...' : 'Simulate & Auto-Recover'}</span>
        </button>
      </div>

      {/* Before vs After Disruption Delta Table */}
      {latestDisruption && activeSolution && (
        <div className="mt-3 p-4 rounded-xl bg-black/40 border border-surface-border text-xs space-y-3 animate-in fade-in duration-300">
          <div className="flex items-center justify-between border-b border-surface-border/60 pb-2">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30">
                Active Disruption Event
              </span>
              <span className="font-semibold text-white">{latestDisruption.title}</span>
            </div>
            <span className="text-[10px] text-slate-400 font-mono">{latestDisruption.timestamp.slice(11, 19)} UTC</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div className="p-2.5 rounded-lg bg-surface/60 border border-surface-border">
              <span className="text-[10px] text-slate-400 block">Compromised Hubs</span>
              <span className="text-sm font-bold font-mono text-rose-400">
                {latestDisruption.affected_warehouse_ids.length} Facilities
              </span>
            </div>

            <div className="p-2.5 rounded-lg bg-surface/60 border border-surface-border">
              <span className="text-[10px] text-slate-400 block">SLA Demand Retained</span>
              <span className="text-sm font-bold font-mono text-emerald-400">
                {activeSolution.demand_retained_pct}%
              </span>
            </div>

            <div className="p-2.5 rounded-lg bg-surface/60 border border-surface-border">
              <span className="text-[10px] text-slate-400 block">Post-Recovery Resilience</span>
              <span className="text-sm font-bold font-mono text-cyan-300">
                {activeSolution.resilience_score.toFixed(3)}
              </span>
            </div>

            <div className="p-2.5 rounded-lg bg-surface/60 border border-surface-border">
              <span className="text-[10px] text-slate-400 block">Recovery Time</span>
              <span className="text-sm font-bold font-mono text-emerald-400 flex items-center justify-center gap-1">
                <Clock className="w-3.5 h-3.5" /> &lt; 2.0s
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
