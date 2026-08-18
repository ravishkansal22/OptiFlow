import React, { useState } from 'react';
import { Layers, Eye, EyeOff, ShieldAlert, Waves, MapPin, Navigation, Info } from 'lucide-react';
import { LogisticsGraph, Candidate, NetworkSolution, ProvenanceTag } from '../types';

interface MapViewProps {
  graph: LogisticsGraph | null;
  candidates: Candidate[];
  activeSolution: NetworkSolution | null;
  onInspectNode: (title: string, data: Record<string, any>, tag?: ProvenanceTag) => void;
}

export const MapView: React.FC<MapViewProps> = ({
  graph,
  candidates,
  activeSolution,
  onInspectNode
}) => {
  const [showFloodZones, setShowFloodZones] = useState(true);
  const [showRoutes, setShowRoutes] = useState(true);
  const [showCustomers, setShowCustomers] = useState(true);
  const [showRejected, setShowRejected] = useState(true);
  const [hoveredNode, setHoveredNode] = useState<{ id: string; name: string; type: string; details: any; x: number; y: number } | null>(null);

  // Puget Sound Map Projection Transformation
  const mapBounds = {
    minLat: 47.10,
    maxLat: 48.05,
    minLon: -122.58,
    maxLon: -121.95
  };

  const projectCoord = (lat: number, lon: number): { x: number; y: number } => {
    const width = 800;
    const height = 620;
    const x = ((lon - mapBounds.minLon) / (mapBounds.maxLon - mapBounds.minLon)) * width;
    const y = height - ((lat - mapBounds.minLat) / (mapBounds.maxLat - mapBounds.minLat)) * height;
    return { x: Math.max(20, Math.min(width - 20, x)), y: Math.max(20, Math.min(height - 20, y)) };
  };

  if (!graph) {
    return (
      <div className="h-[520px] rounded-2xl glass-panel flex flex-col items-center justify-center border border-surface-border text-slate-400">
        <div className="p-4 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 mb-3 animate-pulse">
          <Navigation className="w-8 h-8" />
        </div>
        <p className="font-semibold text-slate-300">Initializing Logistics Graph...</p>
        <p className="text-xs text-slate-500">Querying Mireye terrain, flood, and routing layers</p>
      </div>
    );
  }

  const selectedWhSet = new Set(activeSolution?.selected_warehouse_ids || []);
  const candMap = new Map(candidates.map((c) => [c.id, c]));

  return (
    <div className="relative rounded-2xl glass-panel border border-surface-border overflow-hidden flex flex-col h-[560px]">
      {/* Top Map Toolbar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border/80 bg-surface/80 backdrop-blur-md z-10">
        <div className="flex items-center space-x-2">
          <div className="p-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <Layers className="w-4 h-4" />
          </div>
          <span className="text-xs font-bold text-white uppercase tracking-wider">
            Puget Sound Spatial Logistics Grid
          </span>
          <span className="text-[10px] text-slate-400 font-mono px-2 py-0.5 rounded bg-surface-elevated">
            Mireye Geohash-7
          </span>
        </div>

        {/* Layer Toggles */}
        <div className="flex items-center space-x-2 text-xs">
          <button
            onClick={() => setShowFloodZones(!showFloodZones)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all ${
              showFloodZones ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40' : 'bg-surface-elevated text-slate-500 border-surface-border'
            }`}
          >
            <Waves className="w-3.5 h-3.5" />
            <span>Flood Zones</span>
          </button>

          <button
            onClick={() => setShowRoutes(!showRoutes)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all ${
              showRoutes ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' : 'bg-surface-elevated text-slate-500 border-surface-border'
            }`}
          >
            <Navigation className="w-3.5 h-3.5" />
            <span>Flow Arcs</span>
          </button>

          <button
            onClick={() => setShowCustomers(!showCustomers)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all ${
              showCustomers ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' : 'bg-surface-elevated text-slate-500 border-surface-border'
            }`}
          >
            <span>Demand</span>
          </button>

          <button
            onClick={() => setShowRejected(!showRejected)}
            className={`flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all ${
              showRejected ? 'bg-slate-700 text-slate-300 border-slate-600' : 'bg-surface-elevated text-slate-500 border-surface-border'
            }`}
          >
            <span>Screened Out</span>
          </button>
        </div>
      </div>

      {/* SVG Canvas Map */}
      <div className="relative flex-1 bg-[#070B12] overflow-hidden">
        {/* Background Grid Pattern */}
        <svg className="w-full h-full" viewBox="0 0 800 620" preserveAspectRatio="xMidYMid slice">
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255, 255, 255, 0.03)" strokeWidth="1" />
            </pattern>
            {/* Water Gradient */}
            <linearGradient id="floodGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#06B6D4" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#3B82F6" stopOpacity="0.10" />
            </linearGradient>
            <linearGradient id="routeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#10B981" stopOpacity="0.8" />
              <stop offset="100%" stopColor="#06B6D4" stopOpacity="0.8" />
            </linearGradient>
            <filter id="glowGreen" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
            <filter id="glowRed" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          <rect width="100%" height="100%" fill="url(#grid)" />

          {/* 1. Flood Hazard Inundation Polygons */}
          {showFloodZones && graph.hazards?.map((hz) => {
            const pathData = hz.coordinates[0].map((coord, idx) => {
              const pt = projectCoord(coord[0], coord[1]);
              return `${idx === 0 ? 'M' : 'L'} ${pt.x} ${pt.y}`;
            }).join(' ') + ' Z';

            return (
              <g key={hz.hazard_id}>
                <path
                  d={pathData}
                  fill="url(#floodGrad)"
                  stroke="#06B6D4"
                  strokeWidth="1.5"
                  strokeDasharray="4 3"
                  className="transition-all duration-300 hover:fill-cyan-500/30 cursor-pointer"
                  onClick={() => onInspectNode(`Mireye Flood Inundation Polygon (${hz.hazard_id})`, {
                    hazard_type: hz.hazard_type,
                    severity: hz.severity,
                    description: hz.description,
                    coordinates: hz.coordinates
                  })}
                />
              </g>
            );
          })}

          {/* 2. Routing Arcs & Active Customer Deliveries */}
          {showRoutes && activeSolution && (
            <g className="transition-opacity duration-300">
              {/* Customer Delivery Lines */}
              {graph.customers.map((cust) => {
                const assignedWhId = activeSolution.customer_assignments[cust.id];
                const wh = graph.warehouses.find((w) => w.id === assignedWhId);
                if (!wh) return null;

                const ptWh = projectCoord(wh.lat, wh.lon);
                const ptCust = projectCoord(cust.lat, cust.lon);
                const isDisrupted = wh.status === 'flooded' || wh.status === 'offline';

                return (
                  <line
                    key={`route_${wh.id}_${cust.id}`}
                    x1={ptWh.x}
                    y1={ptWh.y}
                    x2={ptCust.x}
                    y2={ptCust.y}
                    stroke={isDisrupted ? '#F43F5E' : 'url(#routeGrad)'}
                    strokeWidth={isDisrupted ? 1.5 : 1.2}
                    strokeDasharray={isDisrupted ? '4 4' : 'none'}
                    strokeOpacity={isDisrupted ? 0.6 : 0.4}
                  />
                );
              })}

              {/* Supplier -> Warehouse Flow Lines */}
              {activeSolution.flows.map((flow, idx) => {
                const sup = graph.suppliers.find((s) => s.id === flow.source_id);
                const wh = graph.warehouses.find((w) => w.id === flow.target_id);
                if (!sup || !wh) return null;

                const ptSup = projectCoord(sup.lat, sup.lon);
                const ptWh = projectCoord(wh.lat, wh.lon);

                return (
                  <line
                    key={`sup_flow_${idx}`}
                    x1={ptSup.x}
                    y1={ptSup.y}
                    x2={ptWh.x}
                    y2={ptWh.y}
                    stroke="#3B82F6"
                    strokeWidth="2.5"
                    strokeOpacity="0.6"
                  />
                );
              })}
            </g>
          )}

          {/* 3. Screened-Out / Rejected Candidates */}
          {showRejected && candidates.filter((c) => !c.passed_screening).map((cand) => {
            const pt = projectCoord(cand.lat, cand.lon);
            return (
              <g
                key={cand.id}
                className="cursor-pointer group"
                onClick={() => onInspectNode(`Screened Candidate: ${cand.name}`, {
                  id: cand.id,
                  passed: false,
                  rejection_reasons: cand.rejection_reasons,
                  slope_pct: cand.terrain_slope_pct,
                  elevation_m: cand.elevation_m,
                  land_cover: cand.land_cover,
                  flood_risk_score: cand.flood_risk_score
                }, cand.provenance?.terrain)}
                onMouseEnter={() => setHoveredNode({
                  id: cand.id,
                  name: cand.name,
                  type: 'Rejected Site',
                  details: cand.rejection_reasons.join(', '),
                  x: pt.x,
                  y: pt.y
                })}
                onMouseLeave={() => setHoveredNode(null)}
              >
                <circle cx={pt.x} cy={pt.y} r="5" fill="#4B5563" stroke="#1F2937" strokeWidth="2" opacity="0.6" />
                <path d={`M ${pt.x - 3} ${pt.y - 3} L ${pt.x + 3} ${pt.y + 3} M ${pt.x + 3} ${pt.y - 3} L ${pt.x - 3} ${pt.y + 3}`} stroke="#9CA3AF" strokeWidth="1" />
              </g>
            );
          })}

          {/* 4. Customer Demand Nodes */}
          {showCustomers && graph.customers.map((cust) => {
            const pt = projectCoord(cust.lat, cust.lon);
            const radius = Math.max(3, Math.min(8, cust.demand_units / 800));

            return (
              <g
                key={cust.id}
                className="cursor-pointer"
                onClick={() => onInspectNode(`Customer Demand Zone: ${cust.name}`, {
                  id: cust.id,
                  demand_units: cust.demand_units,
                  service_sla_minutes: cust.service_sla_minutes,
                  priority: cust.priority,
                  assigned_warehouse: activeSolution?.customer_assignments[cust.id]
                })}
                onMouseEnter={() => setHoveredNode({
                  id: cust.id,
                  name: cust.name,
                  type: 'Customer Demand',
                  details: `${cust.demand_units.toLocaleString()} units • SLA ${cust.service_sla_minutes}m`,
                  x: pt.x,
                  y: pt.y
                })}
                onMouseLeave={() => setHoveredNode(null)}
              >
                <circle
                  cx={pt.x}
                  cy={pt.y}
                  r={radius}
                  fill="#F59E0B"
                  stroke="#78350F"
                  strokeWidth="1.5"
                  opacity="0.85"
                />
              </g>
            );
          })}

          {/* 5. Suppliers (Blue Diamonds) */}
          {graph.suppliers.map((sup) => {
            const pt = projectCoord(sup.lat, sup.lon);
            return (
              <g
                key={sup.id}
                className="cursor-pointer"
                onClick={() => onInspectNode(`Supplier Terminal: ${sup.name}`, {
                  id: sup.id,
                  capacity_units: sup.capacity_units,
                  unit_supply_cost_usd: sup.unit_supply_cost
                })}
                onMouseEnter={() => setHoveredNode({
                  id: sup.id,
                  name: sup.name,
                  type: 'Supply Source',
                  details: `Cap: ${sup.capacity_units.toLocaleString()} • $${sup.unit_supply_cost}/unit`,
                  x: pt.x,
                  y: pt.y
                })}
                onMouseLeave={() => setHoveredNode(null)}
              >
                <polygon
                  points={`${pt.x},${pt.y - 9} ${pt.x + 9},${pt.y} ${pt.x},${pt.y + 9} ${pt.x - 9},${pt.y}`}
                  fill="#3B82F6"
                  stroke="#93C5FD"
                  strokeWidth="2"
                  filter="url(#glowGreen)"
                />
              </g>
            );
          })}

          {/* 6. Warehouses (Active, Flooded, or Unselected) */}
          {graph.warehouses.map((wh) => {
            const pt = projectCoord(wh.lat, wh.lon);
            const isSelected = selectedWhSet.has(wh.id);
            const isFlooded = wh.status === 'flooded';
            const isOffline = wh.status === 'offline';
            const cand = candMap.get(wh.id);

            let fillColor = '#10B981';
            let strokeColor = '#6EE7B7';
            let filterId: string | undefined = 'url(#glowGreen)';

            if (isFlooded || isOffline) {
              fillColor = '#F43F5E';
              strokeColor = '#FDA4AF';
              filterId = 'url(#glowRed)';
            } else if (!isSelected) {
              fillColor = '#374151';
              strokeColor = '#6B7280';
              filterId = undefined;
            }

            return (
              <g
                key={wh.id}
                className="cursor-pointer"
                onClick={() => onInspectNode(`Distribution Facility: ${wh.name}`, {
                  id: wh.id,
                  status: wh.status,
                  selected_in_plan: isSelected,
                  capacity_units: wh.capacity_units,
                  annual_fixed_cost_usd: wh.fixed_operating_cost,
                  flood_risk_score: wh.flood_risk_score,
                  terrain_slope_pct: cand?.terrain_slope_pct,
                  elevation_m: cand?.elevation_m
                }, cand?.provenance?.flood || cand?.provenance?.terrain)}
                onMouseEnter={() => setHoveredNode({
                  id: wh.id,
                  name: wh.name,
                  type: isFlooded ? 'FLOODED HUB' : isSelected ? 'Active Distribution Center' : 'Qualified Standby Hub',
                  details: `Cap: ${wh.capacity_units.toLocaleString()} • Flood Risk: ${wh.flood_risk_score.toFixed(2)}`,
                  x: pt.x,
                  y: pt.y
                })}
                onMouseLeave={() => setHoveredNode(null)}
              >
                {/* Pulsing ring if flooded */}
                {(isFlooded || isOffline) && (
                  <circle cx={pt.x} cy={pt.y} r="16" fill="none" stroke="#F43F5E" strokeWidth="1.5" className="animate-ping opacity-60" />
                )}

                {/* Hexagon Facility Marker */}
                <polygon
                  points={`${pt.x},${pt.y - 10} ${pt.x + 9},${pt.y - 5} ${pt.x + 9},${pt.y + 5} ${pt.x},${pt.y + 10} ${pt.x - 9},${pt.y + 5} ${pt.x - 9},${pt.y - 5}`}
                  fill={fillColor}
                  stroke={strokeColor}
                  strokeWidth="2"
                  filter={filterId}
                />
              </g>
            );
          })}
        </svg>

        {/* Hover Tooltip Card */}
        {hoveredNode && (
          <div
            className="absolute z-20 pointer-events-none p-3 rounded-xl glass-panel-elevated text-xs border border-surface-border shadow-2xl transition-all"
            style={{
              left: `${Math.min(620, Math.max(10, hoveredNode.x + 15))}px`,
              top: `${Math.min(480, Math.max(10, hoveredNode.y - 10))}px`
            }}
          >
            <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-400 block mb-0.5">
              {hoveredNode.type}
            </span>
            <p className="font-semibold text-white">{hoveredNode.name}</p>
            <p className="text-slate-400 mt-1">{hoveredNode.details}</p>
            <span className="text-[9px] text-emerald-400 font-mono mt-1.5 flex items-center gap-1">
              <Info className="w-3 h-3" /> Click to inspect Mireye telemetry
            </span>
          </div>
        )}

        {/* Map Legend */}
        <div className="absolute bottom-3 left-3 p-2.5 rounded-xl glass-panel text-[11px] border border-surface-border flex items-center gap-4 text-slate-300">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rotate-45 bg-blue-500 rounded-sm" />
            <span>Supplier Terminal</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 bg-emerald-500 rounded-sm" />
            <span>Active Hub</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 bg-rose-500 rounded-sm animate-pulse" />
            <span>Flooded / Offline</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
            <span>Customer Zone</span>
          </div>
        </div>
      </div>
    </div>
  );
};
