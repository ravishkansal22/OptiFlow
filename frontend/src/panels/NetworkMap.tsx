import React, { useMemo, useRef, useState } from 'react';
import { Layers } from 'lucide-react';
import { Card, CardHeader, EmptyState, cn } from '../components/ui';
import { coord, num, usdShort } from '../lib/format';
import { fitProjection } from '../lib/projection';
import type { Candidate, LogisticsGraph, NetworkSolution } from '../types';

const W = 900;
const PAD = 42;
const MIN_H = 460;
const MAX_H = 820;

interface Layer {
  key: 'hazards' | 'lanes' | 'customers' | 'rejected' | 'suppliers';
  label: string;
}

const LAYERS: Layer[] = [
  { key: 'lanes', label: 'Assigned lanes' },
  { key: 'hazards', label: 'Flood zones' },
  { key: 'customers', label: 'Demand zones' },
  { key: 'suppliers', label: 'Suppliers' },
  { key: 'rejected', label: 'Rejected sites' },
];

interface Focus {
  title: string;
  subtitle?: string;
  rows: [string, string][];
  x: number;
  y: number;
  tone: 'accent' | 'danger' | 'muted' | 'info';
}

export interface NetworkMapProps {
  graph: LogisticsGraph | null;
  candidates: Candidate[];
  solution: NetworkSolution | null;
  highlightWarehouseIds?: string[];
  /** Ringed on the map and kept in step with a list elsewhere on the screen. */
  selectedCandidateId?: string | null;
  onSelectCandidate?: (candidateId: string) => void;
  title?: string;
  subtitle?: string;
  /** Hides the layer toggles when the screen owns its own controls. */
  hideLayerToggles?: boolean;
  className?: string;
}

export const NetworkMap: React.FC<NetworkMapProps> = ({
  graph,
  candidates,
  solution,
  highlightWarehouseIds,
  selectedCandidateId,
  onSelectCandidate,
  title,
  subtitle,
  hideLayerToggles,
  className,
}) => {
  const [on, setOn] = useState<Record<Layer['key'], boolean>>({
    hazards: true,
    lanes: true,
    customers: true,
    rejected: true,
    suppliers: true,
  });
  const [focus, setFocus] = useState<Focus | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  /** Fit the projection to every point we plan to draw, then pad the edges. */
  const { project, height: H } = useMemo(() => {
    const pts: [number, number][] = [];
    graph?.warehouses.forEach((w) => pts.push([w.lat, w.lon]));
    graph?.customers.forEach((c) => pts.push([c.lat, c.lon]));
    graph?.suppliers.forEach((s) => pts.push([s.lat, s.lon]));
    candidates.forEach((c) => pts.push([c.lat, c.lon]));
    graph?.hazards.forEach((h) =>
      h.coordinates.forEach((ring) => ring.forEach(([lat, lon]) => pts.push([lat, lon])))
    );
    return fitProjection(pts, { width: W, pad: PAD, minHeight: MIN_H, maxHeight: MAX_H });
  }, [graph, candidates]);

  if (!graph) {
    return (
      <Card className={className}>
        <EmptyState
          icon={<Layers className="h-5 w-5" />}
          title="No network yet"
          body="Run a study and the corridor, its hazards and the assigned lanes will appear here."
        />
      </Card>
    );
  }

  const selected = new Set(solution?.selected_warehouse_ids ?? []);
  const highlight = new Set(highlightWarehouseIds ?? []);
  const candById = new Map(candidates.map((c) => [c.id, c]));
  const whById = new Map(graph.warehouses.map((w) => [w.id, w]));
  const maxDemand = Math.max(1, ...graph.customers.map((c) => c.demand_units));

  const rejected = candidates.filter((c) => !c.passed_screening);
  const eligibleNotOpened = candidates.filter(
    (c) => c.passed_screening && !selected.has(c.id) && !selected.has(whById.get(c.id)?.id ?? '')
  );

  // Only the lanes the active plan actually uses, otherwise the map is a hairball.
  const lanes = solution
    ? graph.customers
        .map((cust) => {
          const wid = solution.customer_assignments[cust.id];
          const wh = wid ? whById.get(wid) : undefined;
          if (!wh) return null;
          const a = project(wh.lat, wh.lon);
          const b = project(cust.lat, cust.lon);
          const disrupted = wh.status !== 'active';
          return { id: `${wid}-${cust.id}`, a, b, disrupted };
        })
        .filter(Boolean as unknown as (v: any) => v is { id: string; a: any; b: any; disrupted: boolean })
    : [];

  const showFocus = (f: Focus) => setFocus(f);

  return (
    <Card flush className={cn('overflow-hidden', className)}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <CardHeader
          title={title ?? 'Corridor map'}
          subtitle={
            subtitle ??
            `${graph.warehouses.length} sites · ${graph.customers.length} demand zones · ${graph.suppliers.length} suppliers`
          }
        />
        <div className={cn('flex flex-wrap gap-1.5', hideLayerToggles && 'hidden')}>
          {LAYERS.map((l) => (
            <button
              key={l.key}
              onClick={() => setOn((s) => ({ ...s, [l.key]: !s[l.key] }))}
              className={cn(
                'rounded-md border px-2 py-1 text-2xs font-medium transition-colors focus-ring',
                on[l.key]
                  ? 'border-accent/30 bg-accent-soft text-accent'
                  : 'border-line bg-surface text-faint hover:text-muted'
              )}
            >
              {l.label}
            </button>
          ))}
        </div>
      </div>

      <div className="relative bg-sunken/60">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          // max-height keeps a tall corridor from pushing the page to several
          // screens; the viewBox letterboxes rather than distorting.
          className="mx-auto block h-auto max-h-[74vh] w-full"
          onMouseLeave={() => setFocus(null)}
          role="img"
          aria-label="Map of the logistics corridor"
        >
          <defs>
            <pattern id="grid" width="45" height="45" patternUnits="userSpaceOnUse">
              <path d="M45 0H0v45" fill="none" stroke="rgb(var(--c-line))" strokeWidth="1" />
            </pattern>
            <pattern id="hazardHatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="7" stroke="rgb(var(--c-danger))" strokeWidth="1.4" opacity="0.28" />
            </pattern>
          </defs>

          <rect width={W} height={H} fill="url(#grid)" opacity="0.7" />

          {/* hazard polygons */}
          {on.hazards &&
            graph.hazards.map((h) =>
              h.coordinates.map((ring, ri) => {
                const d = ring.map(([lat, lon], i) => {
                  const p = project(lat, lon);
                  return `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
                });
                const centre = project(
                  ring.reduce((s, r) => s + r[0], 0) / ring.length,
                  ring.reduce((s, r) => s + r[1], 0) / ring.length
                );
                return (
                  <g key={`${h.hazard_id}-${ri}`}>
                    <path
                      d={`${d.join(' ')} Z`}
                      fill="url(#hazardHatch)"
                      stroke="rgb(var(--c-danger))"
                      strokeOpacity="0.35"
                      strokeWidth="1.2"
                      strokeDasharray="4 3"
                      className="cursor-pointer"
                      onMouseEnter={() =>
                        showFocus({
                          title: h.description || h.hazard_type,
                          subtitle: `${h.severity} severity`,
                          rows: [['Type', h.hazard_type], ['Severity', h.severity]],
                          x: centre.x,
                          y: centre.y,
                          tone: 'danger',
                        })
                      }
                    />
                  </g>
                );
              })
            )}

          {/* assigned lanes */}
          {on.lanes &&
            lanes.map((l) => (
              <line
                key={l.id}
                x1={l.a.x}
                y1={l.a.y}
                x2={l.b.x}
                y2={l.b.y}
                stroke={l.disrupted ? 'rgb(var(--c-danger))' : 'rgb(var(--c-accent))'}
                strokeWidth={l.disrupted ? 1.1 : 0.9}
                strokeOpacity={l.disrupted ? 0.5 : 0.28}
                strokeDasharray={l.disrupted ? '3 3' : undefined}
              />
            ))}

          {/* customers */}
          {on.customers &&
            graph.customers.map((c) => {
              const p = project(c.lat, c.lon);
              const r = 2.6 + (c.demand_units / maxDemand) * 5.4;
              const critical = c.priority >= 3;
              return (
                <circle
                  key={c.id}
                  cx={p.x}
                  cy={p.y}
                  r={r}
                  fill={critical ? 'rgb(var(--c-info))' : 'rgb(var(--c-muted))'}
                  fillOpacity={critical ? 0.75 : 0.42}
                  stroke="rgb(var(--c-surface))"
                  strokeWidth="1"
                  className="cursor-pointer transition-opacity hover:fill-opacity-100"
                  onMouseEnter={() =>
                    showFocus({
                      title: c.name,
                      subtitle: critical ? 'Critical priority zone' : 'Demand zone',
                      rows: [
                        ['Demand', `${num(c.demand_units)} units`],
                        ['SLA', `${num(c.service_sla_minutes)} min`],
                        ['Served by', whById.get(solution?.customer_assignments[c.id] ?? '')?.name ?? 'Unassigned'],
                      ],
                      x: p.x,
                      y: p.y,
                      tone: 'info',
                    })
                  }
                />
              );
            })}

          {/* suppliers */}
          {on.suppliers &&
            graph.suppliers.map((s) => {
              const p = project(s.lat, s.lon);
              return (
                <rect
                  key={s.id}
                  x={p.x - 4.5}
                  y={p.y - 4.5}
                  width="9"
                  height="9"
                  rx="1.5"
                  fill="rgb(var(--c-surface))"
                  stroke="rgb(var(--c-ink))"
                  strokeWidth="1.6"
                  className="cursor-pointer"
                  onMouseEnter={() =>
                    showFocus({
                      title: s.name,
                      subtitle: 'Supply origin',
                      rows: [
                        ['Capacity', `${num(s.capacity_units)} units`],
                        ['Unit cost', `$${s.unit_supply_cost.toFixed(2)}`],
                        ['Location', coord(s.lat, s.lon)],
                      ],
                      x: p.x,
                      y: p.y,
                      tone: 'muted',
                    })
                  }
                />
              );
            })}

          {/* rejected candidates */}
          {on.rejected &&
            rejected.map((c) => {
              const p = project(c.lat, c.lon);
              const picked = selectedCandidateId === c.id;
              return (
                <g
                  key={c.id}
                  className="cursor-pointer"
                  onClick={() => onSelectCandidate?.(c.id)}
                  onMouseEnter={() =>
                    showFocus({
                      title: c.name,
                      subtitle: 'Rejected in screening',
                      rows: [
                        ['Reason', c.rejection_reasons[0] ?? 'Screening failure'],
                        ['Slope', `${c.terrain_slope_pct.toFixed(1)}%`],
                        ['Elevation', `${num(c.elevation_m)} m`],
                      ],
                      x: p.x,
                      y: p.y,
                      tone: 'danger',
                    })
                  }
                >
                  {picked && (
                    <circle
                      cx={p.x}
                      cy={p.y}
                      r="12"
                      fill="rgb(var(--c-danger))"
                      fillOpacity="0.1"
                      stroke="rgb(var(--c-danger))"
                      strokeWidth="1.4"
                    />
                  )}
                  <line x1={p.x - 4} y1={p.y - 4} x2={p.x + 4} y2={p.y + 4} stroke="rgb(var(--c-danger))" strokeWidth="1.6" strokeOpacity="0.6" strokeLinecap="round" />
                  <line x1={p.x + 4} y1={p.y - 4} x2={p.x - 4} y2={p.y + 4} stroke="rgb(var(--c-danger))" strokeWidth="1.6" strokeOpacity="0.6" strokeLinecap="round" />
                </g>
              );
            })}

          {/* eligible but unopened */}
          {eligibleNotOpened.map((c) => {
            const p = project(c.lat, c.lon);
            const picked = selectedCandidateId === c.id;
            return (
              <circle
                key={c.id}
                cx={p.x}
                cy={p.y}
                r={picked ? 7.5 : 5}
                fill={picked ? 'rgb(var(--c-pass-soft))' : 'rgb(var(--c-surface))'}
                stroke={picked ? 'rgb(var(--c-pass))' : 'rgb(var(--c-line-strong))'}
                strokeWidth={picked ? 2.2 : 1.6}
                strokeDasharray="2.5 2"
                className="cursor-pointer"
                onClick={() => onSelectCandidate?.(c.id)}
                onMouseEnter={() =>
                  showFocus({
                    title: c.name,
                    subtitle: 'Eligible, not opened in this plan',
                    rows: [
                      ['Hazard index', c.composite_risk.toFixed(2)],
                      ['Fixed cost', `${usdShort(c.fixed_operating_cost)}/yr`],
                      ['Capacity', `${num(c.capacity_units)} units`],
                    ],
                    x: p.x,
                    y: p.y,
                    tone: 'muted',
                  })
                }
              />
            );
          })}

          {/* opened hubs */}
          {graph.warehouses
            .filter((w) => selected.has(w.id))
            .map((w) => {
              const p = project(w.lat, w.lon);
              const offline = w.status !== 'active';
              const flagged = highlight.has(w.id);
              const cand = candById.get(w.candidate_id) ?? candById.get(w.id);
              const picked = selectedCandidateId === (w.candidate_id || w.id);
              return (
                <g
                  key={w.id}
                  className="cursor-pointer"
                  onClick={() => onSelectCandidate?.(w.candidate_id || w.id)}
                  onMouseEnter={() =>
                    showFocus({
                      title: w.name,
                      subtitle: offline ? `Offline — ${w.status}` : 'Open hub',
                      rows: [
                        ['Capacity', `${num(w.capacity_units)} units`],
                        ['Fixed cost', `${usdShort(w.fixed_operating_cost)}/yr`],
                        ['flood_risk_score', w.flood_risk_score.toFixed(2)],
                        ['Land cover', cand?.land_cover ?? '—'],
                      ],
                      x: p.x,
                      y: p.y,
                      tone: offline ? 'danger' : 'accent',
                    })
                  }
                >
                  {(flagged || offline) && (
                    <circle
                      cx={p.x}
                      cy={p.y}
                      r="15"
                      fill="none"
                      stroke={offline ? 'rgb(var(--c-danger))' : 'rgb(var(--c-accent))'}
                      strokeWidth="1.2"
                      strokeOpacity="0.4"
                    >
                      <animate attributeName="r" values="11;18;11" dur="2.4s" repeatCount="indefinite" />
                      <animate attributeName="stroke-opacity" values="0.5;0;0.5" dur="2.4s" repeatCount="indefinite" />
                    </circle>
                  )}
                  {picked && (
                    <circle
                      cx={p.x}
                      cy={p.y}
                      r="14"
                      fill="none"
                      stroke={offline ? 'rgb(var(--c-danger))' : 'rgb(var(--c-accent))'}
                      strokeWidth="1.6"
                    />
                  )}
                  <rect
                    x={p.x - 7}
                    y={p.y - 7}
                    width="14"
                    height="14"
                    rx="3.5"
                    fill={offline ? 'rgb(var(--c-danger))' : 'rgb(var(--c-accent))'}
                    stroke="rgb(var(--c-surface))"
                    strokeWidth="2"
                  />
                </g>
              );
            })}

          {/* hover card */}
          {focus && <FocusCard focus={focus} frameHeight={H} />}
        </svg>

        <MapLegend />
      </div>
    </Card>
  );
};

/* ---------------------------------------------------------------- pieces */

const FocusCard: React.FC<{ focus: Focus; frameHeight: number }> = ({ focus, frameHeight }) => {
  const width = 232;
  const height = 34 + focus.rows.length * 17 + (focus.subtitle ? 15 : 0);
  const x = Math.min(Math.max(focus.x + 14, 8), W - width - 8);
  const y = Math.min(Math.max(focus.y - height / 2, 8), frameHeight - height - 8);
  const stroke =
    focus.tone === 'accent'
      ? 'rgb(var(--c-accent))'
      : focus.tone === 'danger'
        ? 'rgb(var(--c-danger))'
        : focus.tone === 'info'
          ? 'rgb(var(--c-info))'
          : 'rgb(var(--c-line-strong))';

  return (
    <g pointerEvents="none" className="animate-fade-in">
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx="8"
        fill="rgb(var(--c-surface))"
        stroke={stroke}
        strokeOpacity="0.45"
        strokeWidth="1"
        filter="drop-shadow(0 4px 14px rgb(var(--c-shadow) / 0.18))"
      />
      <text x={x + 11} y={y + 18} fontSize="11.5" fontWeight="600" fill="rgb(var(--c-ink))">
        {truncate(focus.title, 30)}
      </text>
      {focus.subtitle && (
        <text x={x + 11} y={y + 32} fontSize="9.5" fill={stroke}>
          {truncate(focus.subtitle, 36)}
        </text>
      )}
      {focus.rows.map(([k, v], i) => {
        const ty = y + (focus.subtitle ? 48 : 34) + i * 17;
        return (
          <g key={k}>
            <text x={x + 11} y={ty} fontSize="9.5" fill="rgb(var(--c-faint))">
              {k}
            </text>
            <text x={x + width - 11} y={ty} fontSize="9.5" textAnchor="end" fill="rgb(var(--c-ink))">
              {truncate(v, 24)}
            </text>
          </g>
        );
      })}
    </g>
  );
};

const MapLegend: React.FC = () => (
  <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-surface px-5 py-3">
    <LegendItem swatch={<span className="h-3 w-3 rounded-[3px] bg-accent" />} label="Open hub" />
    <LegendItem
      swatch={<span className="h-3 w-3 rounded-full border-[1.5px] border-dashed border-strong bg-surface" />}
      label="Viable, not opened"
    />
    <LegendItem
      swatch={
        <svg viewBox="0 0 12 12" className="h-3 w-3 text-danger">
          <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      }
      label="Rejected"
    />
    <LegendItem swatch={<span className="h-2.5 w-2.5 rounded-full bg-muted/50" />} label="Demand zone" />
    <LegendItem swatch={<span className="h-2.5 w-2.5 rounded-full bg-info/75" />} label="Critical zone" />
    <LegendItem swatch={<span className="h-3 w-3 rounded-[2px] border-[1.5px] border-ink bg-surface" />} label="Supplier" />
    <LegendItem swatch={<span className="h-3 w-3 rounded-[2px] bg-danger/25 ring-1 ring-dashed ring-danger/40" />} label="Flood zone" />
    <span className="ml-auto text-2xs text-faint">Point size tracks demand volume</span>
  </div>
);

const LegendItem: React.FC<{ swatch: React.ReactNode; label: string }> = ({ swatch, label }) => (
  <span className="inline-flex items-center gap-1.5 text-2xs text-muted">
    {swatch}
    {label}
  </span>
);

const truncate = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
