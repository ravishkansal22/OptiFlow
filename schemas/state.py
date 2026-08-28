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
    # Which solution on the Pareto frontier is recommended once it is built:
    # "cost" -> the cost-only baseline, "balanced" -> mid-frontier, "resilience"
    # -> the highest resilience score. Does not change how the frontier is built.
    optimization_preference: str = "balanced"
    # Share of demand the plan must serve inside the delivery window. 0 means the
    # user set no requirement, so the Critic does not test it.
    min_demand_coverage_pct: float = 0.0


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
    # 0-1 weighted suitability, written by the Risk Agent once hazard scoring is
    # done. 0 for anything that failed screening.
    suitability_score: float = 0.0
    score_components: Dict[str, float] = Field(default_factory=dict)
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


class MetricSnapshot(BaseModel):
    """
    How a network actually performs, measured against a concrete graph state.

    Every field is computed from the graph and the solution's own assignments --
    nothing here is estimated or carried over from a previous measurement.
    """
    demand_total_units: float = 0.0
    demand_served_units: float = 0.0
    demand_served_pct: float = 0.0
    on_time_pct: float = 0.0
    avg_delivery_minutes: float = 0.0
    transport_cost_usd: float = 0.0
    fixed_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    customers_served: int = 0
    customers_partial: int = 0
    customers_unserved: int = 0
    active_warehouses: int = 0
    disrupted_lanes: int = 0


class ImpactReport(BaseModel):
    """What a disruption did to the network, before any recovery is attempted."""
    disruption_id: str
    disruption_type: str
    title: str
    before: MetricSnapshot
    after: MetricSnapshot
    failed_warehouse_ids: List[str] = Field(default_factory=list)
    disrupted_edge_ids: List[str] = Field(default_factory=list)
    affected_customer_ids: List[str] = Field(default_factory=list)
    explanation: str = ""
    timestamp: str = ""


class RecoveryReport(BaseModel):
    """What the recovery re-solve changed, measured against the disrupted state."""
    disruption_id: str
    before: MetricSnapshot
    after: MetricSnapshot
    recovery_seconds: float = 0.0
    customers_reassigned: int = 0
    routes_changed: int = 0
    warehouses_activated: List[str] = Field(default_factory=list)
    warehouses_deactivated: List[str] = Field(default_factory=list)
    added_cost_usd: float = 0.0
    summary: str = ""
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
    impact_report: Optional[ImpactReport]      # latest disruption, before recovery
    recovery_report: Optional[RecoveryReport]  # latest recovery re-solve
    # Snapshot taken before the first disruption so the network can be restored
    # and another scenario run against the same starting point.
    pre_disruption_graph: Optional[LogisticsGraph]
    pre_disruption_solution_id: str
    critic_flags: List[str]       # evidence / constraint violations
    critic_report: Optional[CriticReport]
    narrative: str                # LLM-generated explanation of current state
    trace_events: List[AgentTraceEvent]
