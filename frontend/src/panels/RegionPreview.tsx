import React, { useMemo } from 'react';
import { MapPin } from 'lucide-react';
import { Card, EmptyState, cn } from '../components/ui';
import { fitProjection } from '../lib/projection';
import { num } from '../lib/format';
import type { CoordRow } from '../lib/domain';
import type { RegionInfo } from '../types';

const W = 900;
const PAD = 34;
const MIN_H = 300;
const MAX_H = 520;

export interface RegionPreviewProps {
  region: RegionInfo | null;
  /** Sites the person supplied, drawn over the region so placement is visible. */
  customSites?: CoordRow[];
  /** When set, the region's own candidate sites are dimmed as unused. */
  usingCustomSites?: boolean;
  className?: string;
}

/**
 * Where the network will be designed, drawn from what the server has loaded.
 * Only fields the region file actually carries are shown -- nothing is scored
 * here, because nothing has been measured yet.
 */
export const RegionPreview: React.FC<RegionPreviewProps> = ({
  region,
  customSites = [],
  usingCustomSites,
  className,
}) => {
  const { project, height } = useMemo(() => {
    const pts: [number, number][] = [];
    region?.suppliers.forEach((s) => pts.push([s.lat, s.lon]));
    region?.customers.forEach((c) => pts.push([c.lat, c.lon]));
    region?.candidate_warehouses.forEach((c) => pts.push([c.lat, c.lon]));
    region?.hazard_zones.forEach((h) =>
      h.coordinates.forEach((ring) => ring.forEach(([lat, lon]) => pts.push([lat, lon])))
    );
    customSites.forEach((c) => pts.push([c.lat, c.lon]));
    return fitProjection(pts, { width: W, pad: PAD, minHeight: MIN_H, maxHeight: MAX_H });
  }, [region, customSites]);

  if (!region) {
    return (
      <Card className={className}>
        <EmptyState
          icon={<MapPin className="h-5 w-5" />}
          title="No region loaded"
          body="The server did not return a region file, so there is nothing to preview yet."
        />
      </Card>
    );
  }

  const maxDemand = Math.max(1, ...region.customers.map((c) => c.demand_units));

  return (
    <Card flush className={cn('overflow-hidden', className)}>
      <div className="bg-sunken/60">
        <svg
          viewBox={`0 0 ${W} ${height}`}
          className="mx-auto block h-auto max-h-[46vh] w-full"
          role="img"
          aria-label={`Map of ${region.region_name}`}
        >
          <defs>
            <pattern id="previewGrid" width="45" height="45" patternUnits="userSpaceOnUse">
              <path d="M45 0H0v45" fill="none" stroke="rgb(var(--c-line))" strokeWidth="1" />
            </pattern>
            <pattern
              id="previewHazard"
              width="7"
              height="7"
              patternUnits="userSpaceOnUse"
              patternTransform="rotate(45)"
            >
              <line x1="0" y1="0" x2="0" y2="7" stroke="rgb(var(--c-danger))" strokeWidth="1.4" opacity="0.28" />
            </pattern>
          </defs>

          <rect width={W} height={height} fill="url(#previewGrid)" opacity="0.7" />

          {region.hazard_zones.map((h) =>
            h.coordinates.map((ring, ri) => (
              <path
                key={`${h.hazard_id}-${ri}`}
                d={`${ring
                  .map(([lat, lon], i) => {
                    const p = project(lat, lon);
                    return `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
                  })
                  .join(' ')} Z`}
                fill="url(#previewHazard)"
                stroke="rgb(var(--c-danger))"
                strokeOpacity="0.35"
                strokeWidth="1.2"
                strokeDasharray="4 3"
              >
                <title>{`${h.description || h.hazard_type} — ${h.severity} severity`}</title>
              </path>
            ))
          )}

          {region.customers.map((c) => {
            const p = project(c.lat, c.lon);
            const r = 2.6 + (c.demand_units / maxDemand) * 5.4;
            return (
              <circle
                key={c.id}
                cx={p.x}
                cy={p.y}
                r={r}
                fill={c.priority >= 3 ? 'rgb(var(--c-info))' : 'rgb(var(--c-muted))'}
                fillOpacity={c.priority >= 3 ? 0.75 : 0.42}
                stroke="rgb(var(--c-surface))"
                strokeWidth="1"
              >
                <title>{`${c.name} — ${num(c.demand_units)} units, ${num(c.service_sla_minutes)} min window`}</title>
              </circle>
            );
          })}

          {region.candidate_warehouses.map((c) => {
            const p = project(c.lat, c.lon);
            return (
              <circle
                key={c.id}
                cx={p.x}
                cy={p.y}
                r="5"
                fill="rgb(var(--c-surface))"
                stroke={usingCustomSites ? 'rgb(var(--c-line-strong))' : 'rgb(var(--c-accent))'}
                strokeOpacity={usingCustomSites ? 0.5 : 1}
                strokeWidth="1.6"
                strokeDasharray="2.5 2"
              >
                <title>{`${c.name} — candidate site`}</title>
              </circle>
            );
          })}

          {customSites.map((c, i) => {
            const p = project(c.lat, c.lon);
            return (
              <g key={`custom-${i}`}>
                <rect
                  x={p.x - 6}
                  y={p.y - 6}
                  width="12"
                  height="12"
                  rx="3"
                  fill="rgb(var(--c-accent))"
                  stroke="rgb(var(--c-surface))"
                  strokeWidth="2"
                >
                  <title>{`${c.name ?? 'Your site'} — ${c.lat.toFixed(4)}, ${c.lon.toFixed(4)}`}</title>
                </rect>
              </g>
            );
          })}

          {region.suppliers.map((s) => {
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
              >
                <title>{`${s.name} — ${num(s.capacity_units)} units of supply`}</title>
              </rect>
            );
          })}
        </svg>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-surface px-4 py-2.5">
        <Legend swatch={<span className="h-3 w-3 rounded-[2px] border-[1.5px] border-ink bg-surface" />} label={`${region.suppliers.length} suppliers`} />
        <Legend swatch={<span className="h-2.5 w-2.5 rounded-full bg-muted/50" />} label={`${region.customers.length} demand zones`} />
        <Legend
          swatch={<span className="h-3 w-3 rounded-full border-[1.5px] border-dashed border-accent bg-surface" />}
          label={`${region.candidate_warehouses.length} candidate sites`}
        />
        {customSites.length > 0 && (
          <Legend swatch={<span className="h-3 w-3 rounded-[3px] bg-accent" />} label={`${customSites.length} of yours`} />
        )}
        <Legend
          swatch={<span className="h-3 w-3 rounded-[2px] bg-danger/25 ring-1 ring-dashed ring-danger/40" />}
          label={`${region.hazard_zones.length} hazard zones`}
        />
        <span className="ml-auto text-2xs text-faint">Point size tracks demand volume</span>
      </div>
    </Card>
  );
};

const Legend: React.FC<{ swatch: React.ReactNode; label: string }> = ({ swatch, label }) => (
  <span className="inline-flex items-center gap-1.5 text-2xs text-muted">
    {swatch}
    {label}
  </span>
);
