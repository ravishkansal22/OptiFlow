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

    @staticmethod
    def _chunk_destinations(n_origins: int, destinations: List, max_pairs: int = 3500, max_dim: int = 500) -> List[List]:
        """
        Splits a destination list into chunks so each (origins x chunk) matrix
        stays inside Mireye's /v1/proximity per-request caps (<=500 per side,
        <=3,500 pairs — see get_routing_matrix's docstring). For OptiFlow's
        normal dataset sizes this returns a single chunk (one API call).
        """
        if n_origins == 0 or not destinations:
            return []
        chunk_size = max(1, min(max_dim, max_pairs // max(1, n_origins)))
        return [destinations[i:i + chunk_size] for i in range(0, len(destinations), chunk_size)]

    def _haversine_edge(
        self, edge_id: str, source_id: str, origin: List[float], target_id: str, dest: List[float], error: str
    ) -> LogisticsEdge:
        """Builds a degraded-mode edge from straight-line distance when Mireye can't resolve a pair."""
        cfg = self.config
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
            "error": error
        }

        return LogisticsEdge(
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

    async def _resolve_edges_batch(
        self,
        sources: List[Tuple[str, List[float]]],
        targets: List[Tuple[str, List[float]]],
    ) -> Tuple[List[LogisticsEdge], int]:
        """
        Resolves every (source -> target) edge for one direction (e.g. all
        suppliers -> all warehouses) using as few /v1/proximity calls as
        possible: one batched get_routing_matrix() call per destination
        chunk, instead of one call per pair. Pairs Mireye can't resolve (or
        chunks where the whole call fails) fall back to a Haversine estimate,
        same as before.
        """
        edges: List[LogisticsEdge] = []
        degraded = 0
        if not sources or not targets:
            return edges, degraded

        cfg = self.config
        source_ids = [s[0] for s in sources]
        source_pts = [s[1] for s in sources]
        chunks = self._chunk_destinations(len(source_pts), targets)
        sem = asyncio.Semaphore(max(1, cfg.max_concurrency))

        async def _fetch_chunk(dest_chunk: List[Tuple[str, List[float]]]):
            dest_ids = [t[0] for t in dest_chunk]
            dest_pts = [t[1] for t in dest_chunk]
            async with sem:
                try:
                    matrix = await self.gateway.get_routing_matrix(source_pts, dest_pts, mode=cfg.routing_mode)
                except Exception as exc:
                    logger.warning(
                        "[%s] Batched routing matrix call failed for %d origins x %d destinations (%s). "
                        "Using Haversine fallback for this chunk.",
                        self.name, len(source_pts), len(dest_pts), exc
                    )
                    matrix = [None] * (len(source_pts) * len(dest_pts))

            chunk_edges = []
            chunk_degraded = 0
            for oi, (src_id, origin) in enumerate(zip(source_ids, source_pts)):
                for di, (tgt_id, dest) in enumerate(zip(dest_ids, dest_pts)):
                    idx = oi * len(dest_pts) + di
                    routing = matrix[idx] if idx < len(matrix) else None
                    edge_id = f"edge_{src_id}_to_{tgt_id}"
                    if routing is not None:
                        chunk_edges.append(LogisticsEdge(
                            id=edge_id,
                            source_id=src_id,
                            target_id=tgt_id,
                            distance_km=routing.distance_km,
                            travel_time_min=routing.duration_minutes,
                            transport_cost_usd=routing.fuel_cost_usd,
                            route_risk_score=routing.route_risk_score,
                            status="active",
                            provenance=routing.provenance
                        ))
                    else:
                        chunk_edges.append(self._haversine_edge(
                            edge_id, src_id, origin, tgt_id, dest,
                            error="pair unresolved or batch call failed"
                        ))
                        chunk_degraded += 1
            return chunk_edges, chunk_degraded

        results = await asyncio.gather(*[_fetch_chunk(chunk) for chunk in chunks])
        for chunk_edges, chunk_degraded in results:
            edges.extend(chunk_edges)
            degraded += chunk_degraded
        return edges, degraded

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

        # 3. Batched Routing Queries
        #
        # Each direction (Supplier->Warehouse, Warehouse->Customer) is fetched
        # as ONE /v1/proximity distance-matrix call covering every pair at
        # once (chunked only if the matrix exceeds Mireye's per-request
        # limits), instead of one API call per O-D pair. For this pipeline's
        # typical sizes (a handful of suppliers/warehouses, a few dozen
        # customers) that means 2 API calls total to build the whole graph,
        # rather than len(suppliers)*len(warehouses) + len(warehouses)*len(customers).
        cfg = self.config

        sup_wh_edges, sup_wh_degraded = await self._resolve_edges_batch(
            [(sup.id, [sup.lat, sup.lon]) for sup in suppliers],
            [(wh.id, [wh.lat, wh.lon]) for wh in warehouses],
        )
        wh_cust_edges, wh_cust_degraded = await self._resolve_edges_batch(
            [(wh.id, [wh.lat, wh.lon]) for wh in warehouses],
            [(cust.id, [cust.lat, cust.lon]) for cust in customers],
        )
        edges = sup_wh_edges + wh_cust_edges
        degraded_edges_count = sup_wh_degraded + wh_cust_degraded

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
