export interface ProvenanceTag {
  endpoint: string;
  params: Record<string, any>;
  timestamp: string;
  response_hash: string;
  cached: boolean;
  latency_ms: number;
}

export interface Candidate {
  id: string;
  name: string;
  lat: float;
  lon: float;
  demand_weight: number;
  terrain_slope_pct: number;
  elevation_m: number;
  land_cover: string;
  parcel_area_sqm: number;
  is_occupied: boolean;
  flood_risk_score: number;
  hazard_score: number;
  composite_risk: number;
  passed_screening: boolean;
  rejection_reasons: string[];
  fixed_operating_cost: number;
  capacity_units: number;
  provenance: Record<string, ProvenanceTag>;
}

export interface SupplierNode {
  id: string;
  name: string;
  lat: number;
  lon: number;
  capacity_units: number;
  unit_supply_cost: number;
}

export interface WarehouseNode {
  id: string;
  candidate_id: string;
  name: string;
  lat: number;
  lon: number;
  capacity_units: number;
  fixed_operating_cost: number;
  flood_risk_score: number;
  status: 'active' | 'offline' | 'flooded';
}

export interface CustomerNode {
  id: string;
  name: string;
  lat: number;
  lon: number;
  demand_units: number;
  service_sla_minutes: number;
  priority: number;
}

export interface LogisticsEdge {
  id: string;
  source_id: string;
  target_id: string;
  distance_km: number;
  travel_time_min: number;
  transport_cost_usd: number;
  route_risk_score: number;
  status: 'active' | 'disrupted' | 'closed';
  provenance?: ProvenanceTag;
}

export interface HazardZone {
  hazard_id: string;
  hazard_type: string;
  severity: string;
  description: string;
  coordinates: number[][][];
}

export interface LogisticsGraph {
  suppliers: SupplierNode[];
  warehouses: WarehouseNode[];
  customers: CustomerNode[];
  edges: LogisticsEdge[];
  hazards: HazardZone[];
}

export interface FlowRecord {
  source_id: string;
  target_id: string;
  units_shipped: number;
  cost_usd: number;
}

export interface NetworkSolution {
  solution_id: string;
  name: string;
  selected_warehouse_ids: string[];
  customer_assignments: Record<string, string>;
  supplier_assignments: Record<string, string[]>;
  flows: FlowRecord[];
  total_fixed_cost: number;
  total_transport_cost: number;
  total_cost: number;
  demand_retained_pct: number;
  normalized_recovery_cost: number;
  resilience_score: number;
  is_baseline_cost_only: boolean;
  rank: number;
  description?: string;
}

export interface Disruption {
  disruption_id: string;
  disruption_type: string;
  title: string;
  description: string;
  affected_warehouse_ids: string[];
  affected_edge_ids: string[];
  demand_multiplier: number;
  flood_depth_m?: number;
  timestamp: string;
  provenance?: ProvenanceTag;
}

export interface CriticReport {
  passed: boolean;
  flags: string[];
  evidence_coverage_pct: number;
  stale_provenance_count: number;
  missing_provenance_count: number;
  constraint_violations: string[];
  timestamp: string;
}

export interface AgentTraceEvent {
  event_id: string;
  agent_name: string;
  action: string;
  status: 'start' | 'progress' | 'complete' | 'warning' | 'error';
  message: string;
  details?: Record<string, any>;
  timestamp: string;
  provenance?: ProvenanceTag;
}

export interface InputSpec {
  region_name: string;
  bounding_box: number[];
  max_candidate_warehouses: number;
  target_warehouses_to_open: number;
  service_radius_minutes: number;
  budget_limit_usd: number;
  resilience_weight: number;
}

export interface NetworkStateResponse {
  inputs: InputSpec;
  candidates: Candidate[];
  graph: LogisticsGraph | null;
  frontier: NetworkSolution[];
  active_solution_id: string;
  disruption_log: Disruption[];
  critic_flags: string[];
  critic_report: CriticReport | null;
  narrative: string;
  trace_events: AgentTraceEvent[];
}

export type float = number;
