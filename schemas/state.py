from typing import List, Dict, Any, Optional, TypedDict
from pydantic import BaseModel, Field
from .mireye import ProvenanceTag, MireyeHazardPolygon


class InputSpec(BaseModel):
    region_name: str = "Puget Sound Logistics Corridor"
    bounding_box: List[float] = Field(
        default_factory=lambda: [47.10, -122.50, 47.90, -121.90],
        description="[min_lat, min_lon, max_lat, max_lon]"
    )
    max_candidate_warehouses: int = 20
    target_warehouses_to_open: int = 4
    service_radius_minutes: float = 60.0
    budget_limit_usd: float = 2500000.0
    resilience_weight: float = 0.6  # combined = 0.6 * demand_retained + 0.4 * (1 - norm_recovery_cost)


class Candidate(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    demand_weight: float = 0.0
    terrain_slope_pct: float = 0.0
    elevation_m: float = 0.0
    land_cover: str = "Industrial"
    parcel_area_sqm: float = 50000.0
    is_occupied: bool = False
    flood_risk_score: float = 0.0
    hazard_score: float = 0.0
    composite_risk: float = 0.0
    passed_screening: bool = True
    rejection_reasons: List[str] = Field(default_factory=list)
    fixed_operating_cost: float = 120000.0
    capacity_units: float = 15000.0
    provenance: Dict[str, ProvenanceTag] = Field(default_factory=dict)


class SupplierNode(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    capacity_units: float = 50000.0
    unit_supply_cost: float = 10.0


class WarehouseNode(BaseModel):
    id: str
    candidate_id: str
    name: str
    lat: float
    lon: float
    capacity_units: float
    fixed_operating_cost: float
    flood_risk_score: float
    status: str = "active"  # "active", "offline", "flooded"


class CustomerNode(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    demand_units: float
    service_sla_minutes: float = 60.0
    priority: int = 1  # 1 (standard) to 3 (critical hospital/medical)


class LogisticsEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    distance_km: float
    travel_time_min: float
    transport_cost_usd: float
    route_risk_score: float = 0.0
    status: str = "active"  # "active", "disrupted", "closed"
    provenance: Optional[ProvenanceTag] = None


class LogisticsGraph(BaseModel):
    suppliers: List[SupplierNode] = Field(default_factory=list)
    warehouses: List[WarehouseNode] = Field(default_factory=list)
    customers: List[CustomerNode] = Field(default_factory=list)
    edges: List[LogisticsEdge] = Field(default_factory=list)
    hazards: List[MireyeHazardPolygon] = Field(default_factory=list)


class FlowRecord(BaseModel):
    source_id: str
    target_id: str
    units_shipped: float
    cost_usd: float


class NetworkSolution(BaseModel):
    solution_id: str
    name: str
    selected_warehouse_ids: List[str]
    customer_assignments: Dict[str, str] = Field(
        default_factory=dict,
        description="customer_id -> warehouse_id"
    )
    supplier_assignments: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="supplier_id -> list of warehouse_ids"
    )
    flows: List[FlowRecord] = Field(default_factory=list)
    total_fixed_cost: float
    total_transport_cost: float
    total_cost: float
    demand_retained_pct: float = 100.0  # % of demand served within SLA
    normalized_recovery_cost: float = 0.0  # 0 to 1
    resilience_score: float = 1.0  # calculated via 0.6 * demand_retained/100 + 0.4 * (1 - normalized_recovery_cost)
    is_baseline_cost_only: bool = False
    rank: int = 1
    description: str = ""
    unmet_demand_pct: float = 0.0  # % of total customer demand left unassigned to any
    # warehouse because approved facility capacity was insufficient to cover it. 0.0
    # means every customer was fully assigned. A customer contributing to this is left
    # OUT of customer_assignments (not assigned to a facility that can't actually serve
    # them), so critic_agent's existing "unassigned customer" check surfaces it as a
    # constraint violation for visibility rather than the pipeline silently reporting
    # 100% coverage that wasn't real.


class Disruption(BaseModel):
    disruption_id: str
    disruption_type: str  # "flood", "warehouse_failure", "road_closure", "demand_surge"
    title: str
    description: str
    affected_warehouse_ids: List[str] = Field(default_factory=list)
    affected_edge_ids: List[str] = Field(default_factory=list)
    demand_multiplier: float = 1.0
    flood_depth_m: Optional[float] = None
    timestamp: str
    provenance: Optional[ProvenanceTag] = None


class CriticReport(BaseModel):
    passed: bool
    flags: List[str] = Field(default_factory=list)
    evidence_coverage_pct: float = 100.0
    stale_provenance_count: int = 0
    missing_provenance_count: int = 0
    constraint_violations: List[str] = Field(default_factory=list)
    timestamp: str = ""


class AgentTraceEvent(BaseModel):
    event_id: str
    agent_name: str
    action: str
    status: str  # "start", "progress", "complete", "warning", "error"
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str
    provenance: Optional[ProvenanceTag] = None


# TypedDict contract required by LangGraph StateGraph
class NetworkState(TypedDict, total=False):
    inputs: InputSpec
    mireye_cache: Dict[str, Any]  # raw + normalized Mireye responses, keyed by (lat, lon, layer)
    candidates: List[Candidate]   # after screening, with risk scores
    graph: LogisticsGraph         # nodes = warehouses/customers/suppliers + edges
    frontier: List[NetworkSolution]  # Pareto-optimal solutions from NSGA-II
    active_solution_id: str
    disruption_log: List[Disruption]
    critic_flags: List[str]       # evidence / constraint violations
    critic_report: Optional[CriticReport]
    narrative: str                # LLM-generated explanation of current state
    trace_events: List[AgentTraceEvent]
