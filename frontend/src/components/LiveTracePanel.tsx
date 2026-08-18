import React, { useState, useEffect, useRef } from 'react';
import { Radio, Database, ShieldCheck, Cpu, Filter, Eye, Clock, CheckCircle2, AlertCircle, ArrowUpRight } from 'lucide-react';
import { AgentTraceEvent, ProvenanceTag } from '../types';

interface LiveTracePanelProps {
  events: AgentTraceEvent[];
  onInspectProvenance: (title: string, tag: ProvenanceTag, payload?: any) => void;
}

export const LiveTracePanel: React.FC<LiveTracePanelProps> = ({
  events,
  onInspectProvenance
}) => {
  const [selectedAgent, setSelectedAgent] = useState<string>('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  const filteredEvents = events.filter((ev) => {
    if (selectedAgent === 'all') return true;
    if (selectedAgent === 'mireye') return ev.provenance !== undefined || ev.agent_name.includes('Mireye');
    return ev.agent_name.toLowerCase().includes(selectedAgent.toLowerCase());
  });

  const getAgentBadge = (name: string) => {
    if (name.includes('Mireye')) return 'bg-cyan-500/10 text-cyan-400 border-cyan-500/30';
    if (name.includes('Risk')) return 'bg-rose-500/10 text-rose-400 border-rose-500/30';
    if (name.includes('Site')) return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
    if (name.includes('Route')) return 'bg-blue-500/10 text-blue-400 border-blue-500/30';
    if (name.includes('Optimization')) return 'bg-purple-500/10 text-purple-400 border-purple-500/30';
    if (name.includes('Critic')) return 'bg-amber-500/10 text-amber-400 border-amber-500/30';
    return 'bg-slate-700 text-slate-300 border-slate-600';
  };

  return (
    <div className="p-5 rounded-2xl glass-panel border border-surface-border flex flex-col h-[520px]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-border/70 pb-3 mb-3">
        <div className="flex items-center space-x-2">
          <div className="p-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <Radio className="w-4 h-4 animate-pulse" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Live Agent Execution & Mireye Telemetry Stream
            </h3>
            <p className="text-[11px] text-slate-400">
              Real-time LangGraph multi-agent trace stream & provenance auditor
            </p>
          </div>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center space-x-1 text-xs">
          {['all', 'mireye', 'optimization', 'critic'].map((tab) => (
            <button
              key={tab}
              onClick={() => setSelectedAgent(tab)}
              className={`px-2.5 py-1 rounded-lg capitalize transition-all text-[11px] font-medium border ${
                selectedAgent === tab
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                  : 'bg-surface-elevated text-slate-400 border-surface-border hover:text-white'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Events Log Container */}
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const target = e.currentTarget;
          const isAtBottom = target.scrollHeight - target.scrollTop <= target.clientHeight + 40;
          setAutoScroll(isAtBottom);
        }}
        className="flex-1 overflow-y-auto space-y-2.5 pr-1"
      >
        {filteredEvents.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs">
            <Clock className="w-6 h-6 mb-2 text-slate-600 animate-spin" />
            <span>Awaiting incoming multi-agent trace events...</span>
          </div>
        ) : (
          filteredEvents.map((ev, idx) => (
            <div
              key={ev.event_id || idx}
              className="p-3 rounded-xl bg-surface-elevated/70 hover:bg-surface-elevated border border-surface-border/60 text-xs transition-all space-y-1.5"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase border ${getAgentBadge(ev.agent_name)}`}>
                    {ev.agent_name}
                  </span>
                  <span className="font-mono text-[11px] text-slate-300 font-semibold">{ev.action}</span>
                </div>
                <div className="flex items-center space-x-2 text-[10px] text-slate-400 font-mono">
                  {ev.status === 'complete' && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                  {ev.status === 'warning' && <AlertCircle className="w-3.5 h-3.5 text-amber-400" />}
                  <span>{ev.status.toUpperCase()}</span>
                </div>
              </div>

              <p className="text-slate-300 text-[11px] leading-relaxed">{ev.message}</p>

              {/* Attached Mireye Provenance Tag Pill */}
              {ev.provenance && (
                <div className="flex items-center justify-between pt-1.5 border-t border-surface-border/40 text-[10px]">
                  <div className="flex items-center space-x-2 text-slate-400 font-mono">
                    <Database className="w-3 h-3 text-cyan-400" />
                    <span className="text-cyan-300">{ev.provenance.endpoint}</span>
                    <span className="text-slate-500">•</span>
                    <span className="text-amber-400 font-bold">{ev.provenance.latency_ms}ms</span>
                    <span className="text-slate-500">•</span>
                    <span>{ev.provenance.cached ? '⚡ Cached' : '🌐 Live'}</span>
                  </div>

                  <button
                    onClick={() => onInspectProvenance(`Mireye Call: ${ev.provenance?.endpoint}`, ev.provenance!, ev.details)}
                    className="flex items-center gap-1 text-emerald-400 hover:text-emerald-300 font-medium transition-colors"
                  >
                    <span>Inspect</span>
                    <ArrowUpRight className="w-3 h-3" />
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Footer / Autoscroll indicator */}
      <div className="flex items-center justify-between text-[11px] pt-2 border-t border-surface-border/60 text-slate-400">
        <span className="font-mono">{filteredEvents.length} trace records captured</span>
        <button
          onClick={() => setAutoScroll(!autoScroll)}
          className={`px-2 py-0.5 rounded text-[10px] font-mono border ${
            autoScroll ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' : 'bg-surface text-slate-400 border-surface-border'
          }`}
        >
          {autoScroll ? '● Auto-Scroll ON' : '○ Auto-Scroll OFF'}
        </button>
      </div>
    </div>
  );
};
