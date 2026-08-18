import React from 'react';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell
} from 'recharts';
import { TrendingUp, Sparkles, AlertCircle, Check } from 'lucide-react';
import { NetworkSolution } from '../types';

interface FrontierChartProps {
  frontier: NetworkSolution[];
  activeSolutionId: string;
  onSelectSolution: (solutionId: string) => void;
}

export const FrontierChart: React.FC<FrontierChartProps> = ({
  frontier,
  activeSolutionId,
  onSelectSolution
}) => {
  if (!frontier || frontier.length === 0) return null;

  const chartData = frontier.map((sol) => ({
    id: sol.solution_id,
    name: sol.name,
    cost: Math.round(sol.total_cost),
    cost_k: Math.round(sol.total_cost / 1000),
    resilience: Number(sol.resilience_score.toFixed(3)),
    demand_retained: sol.demand_retained_pct,
    hubs: sol.selected_warehouse_ids.length,
    isBaseline: sol.is_baseline_cost_only,
    isActive: sol.solution_id === activeSolutionId,
    rank: sol.rank
  }));

  const activeSol = frontier.find((s) => s.solution_id === activeSolutionId);
  const baselineSol = frontier.find((s) => s.is_baseline_cost_only);

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="p-3.5 rounded-xl glass-panel-elevated text-xs border border-surface-border shadow-2xl space-y-1">
          <div className="flex items-center justify-between gap-2 border-b border-surface-border pb-1">
            <span className="font-bold text-white">{data.name}</span>
            {data.isBaseline && (
              <span className="px-1.5 py-0.5 text-[9px] font-bold rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                Baseline
              </span>
            )}
          </div>
          <div className="text-slate-300 space-y-0.5 pt-1">
            <p>Annual Budget: <span className="font-mono font-semibold text-cyan-300">${data.cost.toLocaleString()}</span></p>
            <p>Resilience Score: <span className="font-mono font-semibold text-emerald-400">{data.resilience}</span></p>
            <p>SLA Demand Retained: <span className="font-mono text-emerald-300">{data.demand_retained}%</span></p>
            <p>Active Hubs: <span className="font-mono text-purple-300">{data.hubs} facilities</span></p>
          </div>
          <p className="text-[10px] text-slate-500 pt-1 border-t border-surface-border">Click to activate this configuration</p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="p-5 rounded-2xl glass-panel border border-surface-border flex flex-col h-[400px]">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2">
          <div className="p-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <TrendingUp className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              NSGA-II Multi-Objective Pareto Frontier
            </h3>
            <p className="text-[11px] text-slate-400">
              Trade-off spectrum: Financial Outlay ($) vs. Disruption Resilience Index
            </p>
          </div>
        </div>

        {/* Trade-off summary badge */}
        {activeSol && baselineSol && (
          <div className="hidden sm:flex items-center gap-2 text-xs px-3 py-1 rounded-lg bg-surface-elevated border border-surface-border">
            <span className="text-slate-400">Active Rank:</span>
            <span className="font-mono text-emerald-400 font-bold">#{activeSol.rank}</span>
            <span className="text-slate-600">|</span>
            <span className="text-slate-400">Resilience Gain:</span>
            <span className="font-mono text-cyan-300 font-semibold">
              +{((activeSol.resilience_score - baselineSol.resilience_score) * 100).toFixed(1)}%
            </span>
          </div>
        )}
      </div>

      {/* Chart Canvas */}
      <div className="flex-1 w-full min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 15, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.06)" />
            <XAxis
              type="number"
              dataKey="cost_k"
              name="Total Cost"
              unit="k"
              stroke="#64748B"
              fontSize={11}
              tickLine={false}
              tickFormatter={(v) => `$${v}k`}
              label={{ value: 'Total Logistics Cost (USD $ Thousands)', position: 'insideBottom', offset: -10, fill: '#94A3B8', fontSize: 11 }}
            />
            <YAxis
              type="number"
              dataKey="resilience"
              name="Resilience Score"
              domain={[0.4, 1.0]}
              stroke="#64748B"
              fontSize={11}
              tickLine={false}
              label={{ value: 'Resilience Index (0–1)', angle: -90, position: 'insideLeft', fill: '#94A3B8', fontSize: 11 }}
            />
            <ZAxis range={[70, 160]} />
            <Tooltip content={<CustomTooltip />} />
            <Scatter
              data={chartData}
              onClick={(node) => onSelectSolution(node.id)}
              className="cursor-pointer"
            >
              {chartData.map((entry, index) => {
                let fill = '#06B6D4';
                if (entry.isBaseline) fill = '#F59E0B'; // Amber baseline
                if (entry.isActive) fill = '#10B981'; // Active green

                return (
                  <Cell
                    key={`cell-${index}`}
                    fill={fill}
                    stroke={entry.isActive ? '#FFFFFF' : fill}
                    strokeWidth={entry.isActive ? 2.5 : 1}
                    className="transition-all duration-200 hover:scale-125"
                  />
                );
              })}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {/* Legend & Guide */}
      <div className="flex items-center justify-between text-xs pt-2 border-t border-surface-border/60 text-slate-400">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
            <span>Cost-Only Baseline (Zero Hazard Shield)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400" />
            <span>Pareto Non-Dominated Tier</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full bg-emerald-500 ring-2 ring-white/50" />
            <span className="font-medium text-emerald-300">Selected Active Plan</span>
          </div>
        </div>
        <span className="text-[11px] text-slate-500 font-mono hidden md:inline">
          Click any point to re-route logistics
        </span>
      </div>
    </div>
  );
};
