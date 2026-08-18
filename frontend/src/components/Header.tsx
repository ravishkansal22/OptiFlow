import React from 'react';
import { Layers, Play, AlertTriangle, RefreshCw, Radio, Sparkles } from 'lucide-react';

interface HeaderProps {
  regionName: string;
  isOptimizing: boolean;
  isDisrupted: boolean;
  onRunOptimization: () => void;
  onOpenDisruptionModal: () => void;
  onOpenProvenanceHistory: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  regionName,
  isOptimizing,
  isDisrupted,
  onRunOptimization,
  onOpenDisruptionModal,
  onOpenProvenanceHistory
}) => {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-surface-border glass-panel">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand & Logo */}
        <div className="flex items-center space-x-4">
          <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-600 to-cyan-500 shadow-lg shadow-emerald-500/20">
            <Layers className="w-5 h-5 text-white" />
            <div className="absolute -top-1 -right-1 w-3 h-3 bg-emerald-400 rounded-full ring-2 ring-[#0B0F19] animate-pulse" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-xl font-bold bg-gradient-to-r from-white via-slate-200 to-emerald-400 bg-clip-text text-transparent">
                OPTIFLOW
              </h1>
              <span className="px-2 py-0.5 text-[10px] font-bold tracking-wider uppercase rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
                10-Agent Core
              </span>
            </div>
            <p className="text-xs text-slate-400 flex items-center gap-1.5">
              <span>Agentic Logistics Intelligence</span>
              <span className="text-slate-600">•</span>
              <span className="text-cyan-400 font-medium flex items-center gap-1">
                <Sparkles className="w-3 h-3" /> Powered by Mireye
              </span>
            </p>
          </div>
        </div>

        {/* Status Indicators & Actions */}
        <div className="flex items-center space-x-3">
          {/* Region Tag */}
          <div className="hidden md:flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-surface-elevated/70 border border-surface-border text-xs text-slate-300">
            <span className="w-2 h-2 rounded-full bg-cyan-400" />
            <span className="font-medium">{regionName}</span>
          </div>

          {/* System State Badge */}
          <div className="flex items-center space-x-2 px-3 py-1.5 rounded-lg border text-xs font-medium backdrop-blur-md bg-surface-elevated/80 border-surface-border">
            {isDisrupted ? (
              <span className="flex items-center text-rose-400 gap-1.5">
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-500"></span>
                </span>
                Active Disruption (Sub-60s Recovered)
              </span>
            ) : isOptimizing ? (
              <span className="flex items-center text-amber-400 gap-1.5">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Orchestrating 10 Agents...
              </span>
            ) : (
              <span className="flex items-center text-emerald-400 gap-1.5">
                <Radio className="w-3.5 h-3.5 animate-pulse" />
                Mireye Gateway Live & Cached
              </span>
            )}
          </div>

          {/* Action: Provenance Audit View */}
          <button
            onClick={onOpenProvenanceHistory}
            className="hidden sm:inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-surface-elevated hover:bg-slate-700 border border-surface-border text-xs font-medium text-slate-300 hover:text-white transition-colors"
          >
            <Layers className="w-3.5 h-3.5 text-cyan-400" />
            <span>Mireye Trace</span>
          </button>

          {/* Action: Simulate Disruption */}
          <button
            onClick={onOpenDisruptionModal}
            className="inline-flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/30 text-xs font-semibold text-rose-300 hover:text-rose-200 transition-all glow-rose"
          >
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>Simulate Disruption</span>
          </button>

          {/* Action: Run Optimization */}
          <button
            onClick={onRunOptimization}
            disabled={isOptimizing}
            className="inline-flex items-center space-x-1.5 px-4 py-1.5 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-500 hover:from-emerald-500 hover:to-teal-400 text-xs font-semibold text-white shadow-lg shadow-emerald-600/25 transition-all disabled:opacity-50"
          >
            <Play className={`w-3.5 h-3.5 fill-current ${isOptimizing ? 'animate-spin' : ''}`} />
            <span>{isOptimizing ? 'Running...' : 'Run Pipeline'}</span>
          </button>
        </div>
      </div>
    </header>
  );
};
