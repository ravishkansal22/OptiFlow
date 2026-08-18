import uuid
from typing import List, Dict, Any, Tuple
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


class RouteGraphBuilderAgent:
    """
    Route / Graph Builder Agent:
    Calls the Mireye Gateway's routing and accessibility endpoints for every
    supplier -> warehouse and warehouse -> customer pair (batched) and builds
    the weighted logistics graph with real road distance, transit duration, cost, and hazard risk.
    """

    def __init__(self, gateway: MireyeGatewayAgent):
        self.gateway = gateway
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
        trace_events = []

        start_event = AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="GraphConstruction",
            status="start",
            message="Constructing weighted multimodal logistics graph with Mireye routing.",
            timestamp=""
        )
        trace_events.append(start_event)

        # 1. Build Supplier Nodes
        suppliers = [SupplierNode(**s) for s in suppliers_raw]

        # 2. Build Qualified Warehouse Nodes (only from surviving candidates)
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

        # 3. Build Customer Nodes
        customers = [CustomerNode(**c) for c in customers_raw]

        # 4. Fetch Regional Hazards via Gateway
        hazards_resp = await self.gateway.get_regional_hazards(region_name, bounding_box, known_hazards=hazard_zones_raw)

        # 5. Batched Routing Queries for Edges
        edges: List[LogisticsEdge] = []

        # (a) Supplier -> Warehouse Edges
        for sup in suppliers:
            for wh in warehouses:
                routing = await self.gateway.get_routing(
                    origin=[sup.lat, sup.lon],
                    destination=[wh.lat, wh.lon],
                    mode="heavy_truck"
                )
                edge_id = f"edge_{sup.id}_to_{wh.id}"
                edge = LogisticsEdge(
                    id=edge_id,
                    source_id=sup.id,
                    target_id=wh.id,
                    distance_km=routing.distance_km,
                    travel_time_min=routing.duration_minutes,
                    transport_cost_usd=routing.fuel_cost_usd,
                    route_risk_score=routing.route_risk_score,
                    status="active",
                    provenance=routing.provenance
                )
                edges.append(edge)

        # (b) Warehouse -> Customer Edges
        for wh in warehouses:
            for cust in customers:
                routing = await self.gateway.get_routing(
                    origin=[wh.lat, wh.lon],
                    destination=[cust.lat, cust.lon],
                    mode="heavy_truck"
                )
                edge_id = f"edge_{wh.id}_to_{cust.id}"
                edge = LogisticsEdge(
                    id=edge_id,
                    source_id=wh.id,
                    target_id=cust.id,
                    distance_km=routing.distance_km,
                    travel_time_min=routing.duration_minutes,
                    transport_cost_usd=routing.fuel_cost_usd,
                    route_risk_score=routing.route_risk_score,
                    status="active",
                    provenance=routing.provenance
                )
                edges.append(edge)

        graph = LogisticsGraph(
            suppliers=suppliers,
            warehouses=warehouses,
            customers=customers,
            edges=edges,
            hazards=hazards_resp.hazards
        )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="GraphConstruction",
            status="complete",
            message=f"Logistics graph assembled: {len(suppliers)} suppliers, {len(warehouses)} qualified warehouses, {len(customers)} customers, and {len(edges)} weighted edges.",
            details={
                "suppliers_count": len(suppliers),
                "warehouses_count": len(warehouses),
                "customers_count": len(customers),
                "edges_count": len(edges)
            },
            timestamp=""
        ))

        return graph, trace_events
