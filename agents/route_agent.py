import uuid
import math
import asyncio
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional

from schemas.state import (
    LogisticsGraph,
    SupplierNode,
    WarehouseNode,
    CustomerNode,
    LogisticsEdge,
    Candidate,
    AgentTraceEvent
)
from agents.mireye_gateway_agent import MireyeGatewayAgent

logger = logging.getLogger(__name__)


@dataclass
class RouteConfig:
    """
    Configuration for the Route/Graph Builder Agent.
    """
    routing_mode: str = "heavy_truck"
    max_concurrency: int = 50

    # --- Fallback heuristics (when Mireye routing fails) ---
    fallback_speed_kmh: float = 60.0
    fallback_cost_per_km: float = 1.5
    fallback_route_risk: float = 0.8  # Pessimistic risk score
    circuitry_factor: float = 1.25    # Multiplier on straight-line distance


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute the great-circle distance between two points in km."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class RouteGraphBuilderAgent:
    """
    Route / Graph Builder Agent.

    Constructs the weighted logistics graph by fetching Mireye routing data
    for all Supplier -> Warehouse and Warehouse -> Customer pairs concurrently.

    Upgrades vs original:
    - RouteConfig: exposes concurrency limits, routing mode, and fallback constants.
    - Concurrency: `asyncio.gather` bounded by a semaphore replaces N*M sequential loops.
    - Graceful Degradation: routing failures trigger a Haversine fallback calculation
      (distance * circuitry factor) rather than crashing the pipeline.
    - Hazard Degradation: regional hazard fetch failures return an empty hazard list
      and log a warning, rather than crashing.
    - Validation: checks input structures.
    """

    def __init__(self, gateway: MireyeGatewayAgent, config: Optional[RouteConfig] = None):
        self.gateway = gateway
        self.config = config or RouteConfig()
        self.name = "Route / Graph Builder Agent"

    async def execute(
        self,
        suppliers_raw: List[Dict[str, Any]],
        candidates: List[Candidate],
        customers_raw: List[Dict[str, Any]],
        hazard_zones_raw: List[Dict[str, Any]],
        region_name: str,
        bounding_box: List[float]
    ) -> Tuple[LogisticsGraph, List[AgentTraceEvent]]:
        
        if not isinstance(suppliers_raw, list) or not isinstance(customers_raw, list):
            raise TypeError("suppliers_raw and customers_raw must be lists.")
            
        trace_events: List[AgentTraceEvent] = []

        start_event = AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="GraphConstruction",
            status="start",
            message="Constructing weighted multimodal logistics graph with Mireye routing.",
            timestamp=""
        )
        trace_events.append(start_event)

        # 1. Build Nodes
        suppliers = [SupplierNode(**s) for s in suppliers_raw]
        qual_candidates = [c for c in candidates if c.passed_screening]
        warehouses = [
            WarehouseNode(
                id=c.id,
                candidate_id=c.id,
                name=c.name,
                lat=c.lat,
                lon=c.lon,
                capacity_units=c.capacity_units,
                fixed_operating_cost=c.fixed_operating_cost,
                flood_risk_score=c.flood_risk_score,
                status="active"
            )
            for c in qual_candidates
        ]
        customers = [CustomerNode(**c) for c in customers_raw]
        
        logger.info(
            "[%s] Building graph for %d suppliers, %d qualified warehouses, %d customers.",
            self.name, len(suppliers), len(warehouses), len(customers)
        )

        # 2. Fetch Regional Hazards (with graceful fallback)
        try:
            hazards_resp = await self.gateway.get_regional_hazards(
                region_name, bounding_box, known_hazards=hazard_zones_raw
            )
            hazards = hazards_resp.hazards
        except Exception as exc:
            logger.warning(
                "[%s] Regional hazards fetch failed (%s: %s). Defaulting to empty hazards list.",
                self.name, type(exc).__name__, exc
            )
            hazards = []

        # 3. Concurrent Batched Routing Queries
        edges: List[LogisticsEdge] = []
        degraded_edges_count = 0
        
        sem = asyncio.Semaphore(self.config.max_concurrency)
        cfg = self.config

        async def _resolve_edge(source_id: str, origin: List[float], target_id: str, dest: List[float]) -> Tuple[LogisticsEdge, bool]:
            edge_id = f"edge_{source_id}_to_{target_id}"
            async with sem:
                try:
                    routing = await self.gateway.get_routing(
                        origin=origin,
                        destination=dest,
                        mode=cfg.routing_mode
                    )
                    edge = LogisticsEdge(
                        id=edge_id,
                        source_id=source_id,
                        target_id=target_id,
                        distance_km=routing.distance_km,
                        travel_time_min=routing.duration_minutes,
                        transport_cost_usd=routing.fuel_cost_usd,
                        route_risk_score=routing.route_risk_score,
                        status="active",
                        provenance=routing.provenance
                    )
                    return edge, False
                except Exception as exc:
                    logger.warning(
                        "[%s] Routing failed for %s -> %s (%s). Using Haversine fallback.",
                        self.name, source_id, target_id, exc
                    )
                    
                    # Haversine fallback
                    straight_line_km = _haversine_distance(origin[0], origin[1], dest[0], dest[1])
                    dist_adjusted_km = straight_line_km * cfg.circuitry_factor
                    time_min = (dist_adjusted_km / cfg.fallback_speed_kmh) * 60.0
                    cost_usd = dist_adjusted_km * cfg.fallback_cost_per_km
                    
                    prov = {
                        "endpoint": "fallback/haversine",
                        "params": {"origin": origin, "destination": dest},
                        "timestamp": "1970-01-01T00:00:00Z",
                        "response_hash": "fallback",
                        "cached": False,
                        "latency_ms": 0.0,
                        "upstream_degraded": True,
                        "fallback_method": "haversine",
                        "error": str(exc)
                    }
                    
                    edge = LogisticsEdge(
                        id=edge_id,
                        source_id=source_id,
                        target_id=target_id,
                        distance_km=round(dist_adjusted_km, 2),
                        travel_time_min=round(time_min, 2),
                        transport_cost_usd=round(cost_usd, 2),
                        route_risk_score=cfg.fallback_route_risk,
                        status="active",
                        provenance=prov
                    )
                    return edge, True

        tasks = []
        # (a) Supplier -> Warehouse Edges
        for sup in suppliers:
            for wh in warehouses:
                tasks.append(_resolve_edge(sup.id, [sup.lat, sup.lon], wh.id, [wh.lat, wh.lon]))
                
        # (b) Warehouse -> Customer Edges
        for wh in warehouses:
            for cust in customers:
                tasks.append(_resolve_edge(wh.id, [wh.lat, wh.lon], cust.id, [cust.lat, cust.lon]))

        if tasks:
            results = await asyncio.gather(*tasks)
            edges = [res[0] for res in results]
            degraded_edges_count = sum(1 for res in results if res[1])

        graph = LogisticsGraph(
            suppliers=suppliers,
            warehouses=warehouses,
            customers=customers,
            edges=edges,
            hazards=hazards
        )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="GraphConstruction",
            status="complete" if degraded_edges_count == 0 else "warning",
            message=(
                f"Logistics graph assembled: {len(suppliers)} suppliers, {len(warehouses)} warehouses, "
                f"{len(customers)} customers, and {len(edges)} weighted edges "
                f"({degraded_edges_count} degraded)."
            ),
            details={
                "suppliers_count": len(suppliers),
                "warehouses_count": len(warehouses),
                "customers_count": len(customers),
                "edges_count": len(edges),
                "degraded_edges_count": degraded_edges_count,
                "hazards_count": len(hazards),
                "routing_mode": cfg.routing_mode
            },
            timestamp=""
        ))

        return graph, trace_events
