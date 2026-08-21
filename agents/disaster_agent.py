import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional

from schemas.state import (
    LogisticsGraph,
    WarehouseNode,
    Disruption,
    AgentTraceEvent,
)
from schemas.mireye import MireyeHazardPolygon
from agents.mireye_gateway_agent import MireyeGatewayAgent, haversine_distance_km

logger = logging.getLogger(__name__)


@dataclass
class DisasterConfig:
    """
    All tuneable parameters for the Disaster Simulation Agent.

    Pass a custom DisasterConfig to DisasterSimulationAgent to override any
    value without touching source code.
    """
    # --- Region queried against Mireye for hazard layers ---
    region_name: str = "Puget Sound Logistics Corridor"
    bounding_box: List[float] = field(
        default_factory=lambda: [47.10, -122.50, 47.90, -121.90]
    )

    # --- Flood scenario ---
    flood_demand_multiplier: float = 1.1
    flood_depth_m_default: float = 1.85
    # Fallback signal (used only if the Mireye hazard-layer call fails):
    # warehouses at/above this flood_risk_score are treated as flooded.
    flood_risk_fallback_threshold: float = 0.4

    # --- Road closure scenario ---
    # Radius around a Mireye-reported road closure point within which an
    # edge's endpoint is considered impacted.
    road_closure_radius_km: float = 8.0
    road_closure_edge_limit: int = 20

    # --- Demand surge scenario ---
    surge_demand_multiplier: float = 1.45

    def validate(self):
        if len(self.bounding_box) != 4:
            raise ValueError(
                f"DisasterConfig.bounding_box must have 4 elements "
                f"[min_lat, min_lon, max_lat, max_lon], got {self.bounding_box}."
            )
        if self.road_closure_radius_km <= 0:
            raise ValueError(
                f"DisasterConfig.road_closure_radius_km must be > 0, "
                f"got {self.road_closure_radius_km}."
            )


def _point_in_polygon(lat: float, lon: float, coordinates: List[List[float]]) -> bool:
    """
    Ray-casting point-in-polygon test.

    `coordinates` follows this codebase's GeoJSON convention of [lon, lat]
    pairs (see MireyeGatewayAgent.get_routing's geometry_geojson).
    """
    if not coordinates or len(coordinates) < 3:
        return False
    inside = False
    n = len(coordinates)
    j = n - 1
    for i in range(n):
        xi, yi = coordinates[i][0], coordinates[i][1]
        xj, yj = coordinates[j][0], coordinates[j][1]
        if (yi > lat) != (yj > lat):
            x_intersect = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_intersect:
                inside = not inside
        j = i
    return inside


def _find_flood_affected_warehouses(
    warehouses: List[WarehouseNode],
    hazards: List[MireyeHazardPolygon],
) -> Tuple[List[str], Dict[str, str]]:
    """
    Spatially matches warehouses against real Mireye flood hazard polygons.
    Returns (affected_warehouse_ids, {warehouse_id: hazard_description}).
    """
    affected: List[str] = []
    reasons: Dict[str, str] = {}
    flood_hazards = [h for h in hazards if h.hazard_type.lower() in ("floodzone", "flood")]
    for wh in warehouses:
        for hz in flood_hazards:
            if _point_in_polygon(wh.lat, wh.lon, hz.coordinates):
                affected.append(wh.id)
                reasons[wh.id] = hz.description
                break
    return affected, reasons


def _fallback_flood_affected_warehouses(
    warehouses: List[WarehouseNode], cfg: DisasterConfig
) -> List[str]:
    """Degraded-mode fallback: use each warehouse's own flood_risk_score."""
    affected = [w.id for w in warehouses if w.flood_risk_score > cfg.flood_risk_fallback_threshold]
    if not affected and warehouses:
        affected = [max(warehouses, key=lambda w: w.flood_risk_score).id]
    return affected


def _build_node_coord_map(graph: LogisticsGraph) -> Dict[str, Tuple[float, float]]:
    coords: Dict[str, Tuple[float, float]] = {}
    for s in graph.suppliers:
        coords[s.id] = (s.lat, s.lon)
    for w in graph.warehouses:
        coords[w.id] = (w.lat, w.lon)
    for c in graph.customers:
        coords[c.id] = (c.lat, c.lon)
    return coords


def _edges_near_point(
    graph: LogisticsGraph,
    lat: float,
    lon: float,
    radius_km: float,
    node_coords: Dict[str, Tuple[float, float]],
) -> List[str]:
    """Finds edges whose source or target endpoint falls within radius_km of a point."""
    affected = []
    for e in graph.edges:
        src = node_coords.get(e.source_id)
        tgt = node_coords.get(e.target_id)
        near = (src is not None and haversine_distance_km(lat, lon, src[0], src[1]) <= radius_km) or (
            tgt is not None and haversine_distance_km(lat, lon, tgt[0], tgt[1]) <= radius_km
        )
        if near:
            affected.append(e.id)
    return affected


class DisasterSimulationAgent:
    """
    Disaster Simulation Agent.

    Uses Mireye's real regional flood hazard layers, elevation profiles, and
    road closure data (via MireyeGatewayAgent.get_regional_hazards) to
    generate geographically grounded disruption scenarios instead of
    string-matching warehouse names.

    Upgrade dimensions vs. original:
    - DisasterConfig: region/bbox/thresholds/multipliers are constructor args.
    - Real hazard data: flood scenario spatially matches warehouses against
      actual Mireye hazard polygons (point-in-polygon), not
      `"kent" in w.name.lower()` string matching.
    - Real road closures: road closure scenario finds edges within
      `road_closure_radius_km` of a Mireye-reported closure point, not
      `"tukwila" in e.source_id` string matching.
    - Graceful Mireye degradation: gateway exceptions → fall back to
      flood_risk_score threshold (flood) or the original name-matching
      (road closure), flagged via upstream_degraded in the trace event.
    - Provenance: Disruption.provenance is now populated from the Mireye
      hazard-layer response instead of always being None.
    - Interface: generate_scenario(scenario_type, graph) → unchanged;
      known_hazards_raw is an optional new kwarg for wiring real seed data.
    """

    def __init__(
        self,
        gateway: MireyeGatewayAgent,
        config: Optional[DisasterConfig] = None,
    ):
        self.gateway = gateway
        self.config = config or DisasterConfig()
        self.config.validate()
        self.name = "Disaster Simulation Agent"

    async def generate_scenario(
        self,
        scenario_type: str,
        graph: LogisticsGraph,
        known_hazards_raw: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Disruption, List[AgentTraceEvent]]:
        cfg = self.config
        trace_events: List[AgentTraceEvent] = []
        disruption_id = f"disrupt_{uuid.uuid4().hex[:8]}"

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="SimulateDisaster",
            status="start",
            message=f"Generating geographically grounded disruption scenario: '{scenario_type}' using Mireye flood layers.",
            timestamp="",
        ))

        # ── Fetch real regional hazard layer, with graceful degradation ─────
        upstream_degraded = False
        hazard_resp = None
        try:
            hazard_resp = await self.gateway.get_regional_hazards(
                region_name=cfg.region_name,
                bounding_box=cfg.bounding_box,
                known_hazards=known_hazards_raw,
            )
        except Exception as exc:
            upstream_degraded = True
            logger.warning(
                "[%s] Regional hazard fetch failed (%s: %s) — "
                "falling back to conservative local signals for scenario '%s'.",
                self.name, type(exc).__name__, exc, scenario_type,
            )

        if scenario_type == "flood_green_river":
            if hazard_resp and hazard_resp.hazards:
                affected_warehouses, hazard_reasons = _find_flood_affected_warehouses(
                    graph.warehouses, hazard_resp.hazards
                )
                if not affected_warehouses:
                    # Hazard layer returned but nothing intersected — fall back
                    # to the risk-score signal rather than reporting no impact.
                    affected_warehouses = _fallback_flood_affected_warehouses(graph.warehouses, cfg)
                    hazard_reasons = {}
            else:
                affected_warehouses = _fallback_flood_affected_warehouses(graph.warehouses, cfg)
                hazard_reasons = {}

            affected_edges = [
                e.id for e in graph.edges
                if e.source_id in affected_warehouses or e.target_id in affected_warehouses
            ]

            description = (
                "Severe atmospheric river triggers 100-year flood event along the region's "
                "low-elevation corridor. Warehouses in Mireye-mapped flood hazard polygons "
                "inundated and connecting transit disrupted."
            )
            if hazard_reasons:
                description = (
                    f"{description} Confirmed hazard: "
                    f"{next(iter(hazard_reasons.values()))}"
                )
            if upstream_degraded:
                description += (
                    " NOTE: Mireye hazard layer unavailable — affected facilities "
                    "were selected via flood_risk_score fallback (MIREYE_MOCK_MODE)."
                )

            disruption = Disruption(
                disruption_id=disruption_id,
                disruption_type="flood",
                title="100-Year Regional Flood Inundation",
                description=description,
                affected_warehouse_ids=affected_warehouses,
                affected_edge_ids=affected_edges,
                demand_multiplier=cfg.flood_demand_multiplier,
                flood_depth_m=cfg.flood_depth_m_default,
                timestamp=datetime.now(timezone.utc).isoformat(),
                provenance=hazard_resp.provenance if hazard_resp else None,
            )

        elif scenario_type == "road_closure_corridor":
            if hazard_resp and hazard_resp.active_road_closures and not upstream_degraded:
                node_coords = _build_node_coord_map(graph)
                affected_edges: List[str] = []
                closure_names = []
                for closure in hazard_resp.active_road_closures:
                    closure_names.append(closure.get("road_name", "Unnamed closure"))
                    affected_edges.extend(_edges_near_point(
                        graph, closure["lat"], closure["lon"],
                        cfg.road_closure_radius_km, node_coords,
                    ))
                affected_edges = list(dict.fromkeys(affected_edges))[:cfg.road_closure_edge_limit]
                title = closure_names[0] if closure_names else "Regional Road Closure"
                description = (
                    f"Mireye-reported road closure(s) ({', '.join(closure_names)}) "
                    f"severely disrupting heavy truck throughput on {len(affected_edges)} routes."
                )
            else:
                # Degraded fallback: original heuristic name-matching.
                affected_edges = [
                    e.id for e in graph.edges
                    if "tukwila" in e.source_id or "tukwila" in e.target_id or "renton" in e.source_id
                ][:cfg.road_closure_edge_limit]
                title = "I-5 / I-405 Southcenter Interchange Collapse"
                description = (
                    "Major structural failure and road closure at key highway junction "
                    "severely disrupting heavy truck throughput."
                )
                if upstream_degraded:
                    description += (
                        " NOTE: Mireye hazard layer unavailable — impacted routes were "
                        "selected via corridor-name heuristic fallback (MIREYE_MOCK_MODE)."
                    )

            disruption = Disruption(
                disruption_id=disruption_id,
                disruption_type="road_closure",
                title=title,
                description=description,
                affected_warehouse_ids=[],
                affected_edge_ids=affected_edges,
                demand_multiplier=1.0,
                flood_depth_m=None,
                timestamp=datetime.now(timezone.utc).isoformat(),
                provenance=hazard_resp.provenance if (hazard_resp and not upstream_degraded) else None,
            )

        elif scenario_type == "surge_demand":
            disruption = Disruption(
                disruption_id=disruption_id,
                disruption_type="demand_surge",
                title="Regional Emergency Medical & Urban Demand Surge",
                description=(
                    f"Regional emergency spikes demand across hospitals and downtown "
                    f"commercial centers by +{(cfg.surge_demand_multiplier - 1) * 100:.0f}%."
                ),
                affected_warehouse_ids=[],
                affected_edge_ids=[],
                demand_multiplier=cfg.surge_demand_multiplier,
                flood_depth_m=None,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        else:
            # Single Warehouse Outage (e.g. Primary facility failure)
            target_wh = graph.warehouses[0].id if graph.warehouses else "cand_kent_south"
            affected_edges = [e.id for e in graph.edges if e.source_id == target_wh or e.target_id == target_wh]
            disruption = Disruption(
                disruption_id=disruption_id,
                disruption_type="warehouse_failure",
                title=f"Catastrophic Outage at Facility {target_wh}",
                description="Power substation failure and structural shutdown forces immediate facility evacuation.",
                affected_warehouse_ids=[target_wh],
                affected_edge_ids=affected_edges,
                demand_multiplier=1.0,
                flood_depth_m=None,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        if not upstream_degraded:
            logger.info(
                "[%s] Scenario '%s' generated — %d warehouses, %d edges impacted.",
                self.name, scenario_type,
                len(disruption.affected_warehouse_ids), len(disruption.affected_edge_ids),
            )
        else:
            logger.warning(
                "[%s] Scenario '%s' generated in DEGRADED mode (Mireye unavailable) — "
                "%d warehouses, %d edges impacted via fallback signals.",
                self.name, scenario_type,
                len(disruption.affected_warehouse_ids), len(disruption.affected_edge_ids),
            )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="SimulateDisaster",
            status="complete" if not upstream_degraded else "warning",
            message=(
                f"Disruption scenario active: {disruption.title}. "
                f"Impacted {len(disruption.affected_warehouse_ids)} facilities and "
                f"{len(disruption.affected_edge_ids)} transport edges."
            ),
            details={
                "disruption_id": disruption.disruption_id,
                "type": disruption.disruption_type,
                "affected_warehouses": disruption.affected_warehouse_ids,
                "affected_edges_count": len(disruption.affected_edge_ids),
                "upstream_degraded": upstream_degraded,
            },
            timestamp=disruption.timestamp,
            provenance=disruption.provenance,
        ))

        return disruption, trace_events