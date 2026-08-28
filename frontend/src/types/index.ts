/**
 * Mirrors schemas/state.py and schemas/mireye.py on the FastAPI backend.
 * Keep this file in sync whenever a backend Pydantic model changes.
 */

export interface ProvenanceTag {
  endpoint: string;
  params: Record<string, any>;
  timestamp: string;
  response_hash: string;
  cached: boolean;
  latency_ms: number;
  /** True only if the value came from a successful Mireye API response. */
  live: boolean;
  /** 'live' | 'cache' | 'cache-simulation' | 'simulation' */
  source: string;
}

/** Reported by GET /api/data-source and embedded in health + evaluations. */
export interface DataSource {
  api_key_configured: boolean;
  strict_live: boolean;
  base_url: string;
  live_values: number;
  simulated_values: number;
  total_values: number;
  live_pct: number;
  cached_entries: number;
  last_live_error: string | null;
  request_timeout_s: number;
  max_attempts: number;
  /** Present on an evaluate-sites response. */
  live_values_this_request?: number;
  simulated_values_this_request?: number;
}

export interface Candidate {
  id: string;
  name: string;
  lat: number;
  lon: number;
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
  /** 0-1 weighted suitability written by the Risk agent; 0 for anything rejected. */
  suitability_score: number;
  score_components: Record<string, number>;
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
  provenance?: ProvenanceTag | null;
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
  flood_depth_m?: number | null;
  timestamp: string;
  provenance?: ProvenanceTag | null;
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

export type TraceStatus = 'start' | 'progress' | 'complete' | 'warning' | 'error';

export interface AgentTraceEvent {
  event_id: string;
  agent_name: string;
  action: string;
  status: TraceStatus;
  message: string;
  details?: Record<string, any>;
  timestamp: string;
  provenance?: ProvenanceTag | null;
}

export interface InputSpec {
  region_name: string;
  bounding_box: number[];
  max_candidate_warehouses: number;
  target_warehouses_to_open: number;
  service_radius_minutes: number;
  budget_limit_usd: number;
  resilience_weight: number;
  /** Which point on the finished frontier is recommended first. */
  optimization_preference: OptimizationPreference;
  /** 0 means the user set no coverage requirement. */
  min_demand_coverage_pct: number;
}

export type OptimizationPreference = 'cost' | 'balanced' | 'resilience';

/** How a network performs against one concrete graph state. */
export interface MetricSnapshot {
  demand_total_units: number;
  demand_served_units: number;
  demand_served_pct: number;
  on_time_pct: number;
  avg_delivery_minutes: number;
  transport_cost_usd: number;
  fixed_cost_usd: number;
  total_cost_usd: number;
  customers_served: number;
  /** Zones that got some of their order but not all of it. */
  customers_partial: number;
  customers_unserved: number;
  active_warehouses: number;
  disrupted_lanes: number;
}

/** What a disruption did, measured before any recovery. */
export interface ImpactReport {
  disruption_id: string;
  disruption_type: string;
  title: string;
  before: MetricSnapshot;
  after: MetricSnapshot;
  failed_warehouse_ids: string[];
  disrupted_edge_ids: string[];
  affected_customer_ids: string[];
  explanation: string;
  timestamp: string;
}

/** What the recovery re-solve changed, measured against the disrupted state. */
export interface RecoveryReport {
  disruption_id: string;
  before: MetricSnapshot;
  after: MetricSnapshot;
  recovery_seconds: number;
  customers_reassigned: number;
  routes_changed: number;
  warehouses_activated: string[];
  warehouses_deactivated: string[];
  added_cost_usd: number;
  summary: string;
  timestamp: string;
}

/** Where the backend is in the workflow, from GET /api/state. */
export type BackendStage =
  | 'idle'
  | 'analyzing'
  | 'analyzed'
  | 'optimizing'
  | 'optimized'
  | 'disrupting'
  | 'disrupted'
  | 'recovering'
  | 'recovered';

export interface ScenarioOption {
  id: string;
  label: string;
  detail?: string;
}

export interface ScenarioParam {
  key: string;
  label: string;
  type: 'select' | 'number';
  options?: ScenarioOption[];
  default?: string | number | null;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
}

/** One entry of GET /api/scenarios, built from the live graph. */
export interface ScenarioDef {
  id: string;
  title: string;
  summary: string;
  parameters: ScenarioParam[];
  available: boolean;
}

export interface ScenarioCatalogue {
  ready: boolean;
  scenarios: ScenarioDef[];
}

/** GET /api/region -- what the server has loaded, for the setup preview. */
export interface RegionInfo {
  region_name: string;
  bounding_box: number[];
  suppliers: SupplierSeed[];
  customers: CustomerSeed[];
  candidate_warehouses: CandidateSeed[];
  hazard_zones: HazardZone[];
  defaults: InputSpec;
}

export interface SupplierSeed {
  id: string;
  name: string;
  lat: number;
  lon: number;
  capacity_units: number;
  unit_supply_cost: number;
}

export interface CustomerSeed {
  id: string;
  name: string;
  lat: number;
  lon: number;
  demand_units: number;
  service_sla_minutes: number;
  priority: number;
}

export interface CandidateSeed {
  id: string;
  name: string;
  lat: number;
  lon: number;
  base_capacity?: number;
  fixed_cost?: number;
}

export interface NetworkStateResponse {
  inputs: InputSpec;
  candidates: Candidate[];
  graph: LogisticsGraph | null;
  frontier: NetworkSolution[];
  active_solution_id: string;
  disruption_log: Disruption[];
  impact_report: ImpactReport | null;
  recovery_report: RecoveryReport | null;
  critic_flags: string[];
  critic_report: CriticReport | null;
  narrative: string;
  trace_events: AgentTraceEvent[];
  /** Where the backend is in the workflow. */
  stage: BackendStage;
  /** True once a disruption has been applied and the healthy graph is held. */
  can_restore: boolean;
  /** The design in place before the first disruption, if there has been one. */
  pre_disruption_solution_id: string;
}

export interface HealthResponse {
  status: string;
  service: string;
  mireye_cache_count: number;
  active_ws_clients: number;
  data_source?: DataSource;
}

export interface NarratorAnswer {
  answer: string;
  related_candidate_id?: string;
  provenance?: Record<string, ProvenanceTag>;
  frontier_count?: number;
  high_risk_warehouses?: string[];
}

export interface MireyeCallRecord {
  endpoint?: string;
  params?: Record<string, any>;
  timestamp?: string;
  cached?: boolean;
  latency_ms?: number;
  [k: string]: any;
}

/** A user-supplied location for POST /api/evaluate-sites. */
export interface SiteInput {
  id?: string;
  name?: string;
  lat: number;
  lon: number;
  capacity_units?: number;
  fixed_cost?: number;
}

export type ScoreComponent =
  | 'hazard_headroom'
  | 'slope_headroom'
  | 'parcel_adequacy'
  | 'capacity_share';

export interface EvaluatedSite {
  id: string;
  name: string;
  lat: number;
  lon: number;
  passed: boolean;
  rejection_reasons: string[];
  suitability_score: number;
  score_components: Record<ScoreComponent, number>;
  terrain_slope_pct: number;
  elevation_m: number;
  land_cover: string;
  parcel_area_sqm: number;
  is_occupied: boolean;
  flood_risk_score: number;
  composite_risk: number;
  capacity_units: number;
  fixed_operating_cost: number;
  provenance: Record<string, ProvenanceTag>;
  /** Per-layer origin: true = from the API, false = simulated. */
  layer_live: Record<string, boolean>;
  /** True only when every layer for this site came from the API. */
  all_live: boolean;
  /** 1-based among sites that passed; null for rejects. */
  rank: number | null;
}

export interface EvaluateSitesResponse {
  evaluated: number;
  passed: number;
  rejected: number;
  best_site_id: string | null;
  /** Set when nothing could be recommended because every candidate used simulated values. */
  best_blocked_reason?: string | null;
  weights: Record<ScoreComponent, number>;
  sites: EvaluatedSite[];
  data_source: DataSource;
  trace_events: AgentTraceEvent[];
}

/** Parameters accepted by POST /api/run and POST /api/analyze. */
export interface RunParams {
  region_name: string;
  target_warehouses: number;
  service_radius_minutes: number;
  budget_limit_usd: number;
  optimization_preference?: OptimizationPreference;
  /** Share of demand the plan must serve in the window; 0 sets no requirement. */
  min_demand_coverage_pct?: number;
  /** Each of these replaces the matching part of the region dataset for the run. */
  custom_sites?: SiteInput[];
  custom_suppliers?: SupplierInput[];
  custom_customers?: CustomerInput[];
}

/** A user-supplied supply origin. */
export interface SupplierInput {
  id?: string;
  name?: string;
  lat: number;
  lon: number;
  capacity_units?: number;
  unit_supply_cost?: number;
}

/** A user-supplied demand zone. */
export interface CustomerInput {
  id?: string;
  name?: string;
  lat: number;
  lon: number;
  demand_units?: number;
  service_sla_minutes?: number;
  priority?: number;
}
