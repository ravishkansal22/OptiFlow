import React from 'react';
import { History } from 'lucide-react';
import { Badge, Card, CardHeader, EmptyState, Meter } from '../components/ui';
import { riskShade } from '../lib/domain';
import { dateTime } from '../lib/format';
import type { Disruption, LogisticsGraph, NetworkSolution } from '../types';

/**
 * Flood exposure across the facilities the active plan opens, scored by the
 * Risk agent. Scaled against the highest score in this network rather than
 * against invented bands, so it stays a comparison between real sites.
 */
export const HubRiskCard: React.FC<{
  graph: LogisticsGraph | null;
  solution: NetworkSolution | null;
  className?: string;
}> = ({ graph, solution, className }) => {
  const openHubs =
    graph?.warehouses.filter((w) => solution?.selected_warehouse_ids.includes(w.id)) ?? [];
  const maxRisk = Math.max(0, ...openHubs.map((w) => w.flood_risk_score));

  return (
    <Card className={className}>
      <CardHeader
        title="Flood exposure in this plan"
        subtitle="0 is safe, 1 is the worst. Only the facilities this design opens."
      />
      {openHubs.length === 0 ? (
        <EmptyState title="No facilities open" body="Optimise a network first." />
      ) : (
        <ul className="mt-4 space-y-3.5">
          {[...openHubs]
            .sort((a, b) => b.flood_risk_score - a.flood_risk_score)
            .map((w) => (
              <li key={w.id}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-xs font-medium text-ink">{w.name}</span>
                  <span className="num shrink-0 text-xs text-muted">
                    {w.flood_risk_score.toFixed(2)}
                  </span>
                </div>
                <Meter
                  value={riskShade(w.flood_risk_score, maxRisk)}
                  tone="danger"
                  className="mt-1.5"
                />
                {w.status !== 'active' && (
                  <p className="num mt-1 font-mono text-2xs text-danger">status: {w.status}</p>
                )}
              </li>
            ))}
        </ul>
      )}
    </Card>
  );
};

/** Every scenario run against this network, newest first. */
export const DisruptionHistory: React.FC<{
  disruptions: Disruption[];
  graph?: LogisticsGraph | null;
  className?: string;
}> = ({ disruptions, graph, className }) => (
  <Card flush className={className}>
    <div className="border-b border-line px-5 py-3.5">
      <CardHeader title="Scenarios you have run" subtitle="Newest first." />
    </div>
    {disruptions.length === 0 ? (
      <EmptyState
        icon={<History className="h-5 w-5" />}
        title="Nothing tested yet"
        body="Pick a scenario above to see how this network holds up."
      />
    ) : (
      <ul className="divide-y divide-line">
        {[...disruptions].reverse().map((d) => (
          <li key={d.disruption_id} className="px-5 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-medium text-ink">{d.title}</span>
              <Badge tone="neutral">{d.disruption_type}</Badge>
              <span className="num ml-auto font-mono text-2xs text-faint">{d.disruption_id}</span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted">{d.description}</p>
            <p className="num mt-1.5 font-mono text-2xs text-faint">
              {d.affected_warehouse_ids.length} facilities
              {d.affected_warehouse_ids.length > 0 && graph
                ? ` (${d.affected_warehouse_ids
                    .map((id) => graph.warehouses.find((w) => w.id === id)?.name ?? id)
                    .join(', ')})`
                : ''}{' '}
              · {d.affected_edge_ids.length} lanes · {d.demand_multiplier.toFixed(2)}x demand ·{' '}
              {dateTime(d.timestamp)}
            </p>
          </li>
        ))}
      </ul>
    )}
  </Card>
);
