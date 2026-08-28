import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from schemas.state import (
    LogisticsGraph,
    NetworkSolution,
    Disruption,
    ImpactReport,
    AgentTraceEvent
)
from agents.mireye_gateway_agent import MireyeGatewayAgent
from agents.network_metrics import evaluate_network


def _point_in_ring(lat: float, lon: float, ring: List[List[float]]) -> bool:
    """Ray casting over a [lat, lon] ring."""
    inside = False
    n = len(ring)
    for i in range(n):
        y1, x1 = ring[i][0], ring[i][1]
        y2, x2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            x_at = x1 + (lat - y1) * (x2 - x1) / ((y2 - y1) or 1e-12)
            if lon < x_at:
                inside = not inside
    return inside


def _in_hazard(lat: float, lon: float, hazard) -> bool:
    return any(_point_in_ring(lat, lon, ring) for ring in hazard.coordinates)


class DisasterSimulationAgent:
    """
    Disaster Simulation Agent:
    Uses Mireye's real regional flood hazard layers, elevation profiles, and road networks
    to generate geographically grounded disruption scenarios (warehouse flood failure,
    road closures, storm surge) rather than artificial random edge drops.

    It also measures what a scenario did to the network, so the impact shown to the
    user is read off the graph rather than described in prose alone.
    """

    #: Scenario ids this agent branches on. The UI reads the catalogue from
    #: /api/scenarios rather than restating any of it.
    SCENARIOS = [
        "warehouse_failure",
        "road_closure_corridor",
        "flood_green_river",
        "surge_demand",
        "combined_disaster",
        "auto",
    ]

    DEFAULT_FLOOD_DEPTH_M = 1.85
    DEFAULT_SURGE_MULTIPLIER = 1.45

    def __init__(self, gateway: MireyeGatewayAgent):
        self.gateway = gateway
        self.name = "Disaster Simulation Agent"

    # ------------------------------------------------------------------ catalogue

    def catalogue(
        self,
        graph: Optional[LogisticsGraph],
        solution: Optional[NetworkSolution] = None
    ) -> List[Dict[str, Any]]:
        """
        The scenarios that can run against the network as it stands, with the
        choices each one offers. Options are built from the graph, so a scenario
        never offers a facility or a hazard zone that is not there.
        """
        open_ids = set(solution.selected_warehouse_ids) if solution else set()
        warehouses = [
            {"id": w.id, "label": w.name, "detail": "flood risk %.2f" % w.flood_risk_score}
            for w in (graph.warehouses if graph else [])
            if not open_ids or w.id in open_ids
        ]
        hazards = [
            {
                "id": h.hazard_id,
                "label": h.description or h.hazard_type,
                "detail": "%s severity" % h.severity,
            }
            for h in (graph.hazards if graph else [])
        ]

        return [
            {
                "id": "warehouse_failure",
                "title": "Warehouse failure",
                "summary": "One facility shuts down and stops shipping.",
                "parameters": [
                    {
                        "key": "target_warehouse_id",
                        "label": "Facility",
                        "type": "select",
                        "options": warehouses,
                        "default": warehouses[0]["id"] if warehouses else None,
                    }
                ],
                "available": bool(warehouses),
            },
            {
                "id": "road_closure_corridor",
                "title": "Road closure",
                "summary": "The main corridor closes and the lanes through it stop moving.",
                "parameters": [],
                "available": bool(graph and graph.edges),
            },
            {
                "id": "flood_green_river",
                "title": "Flood",
                "summary": "A flood inundates a hazard zone and everything sited inside it.",
                "parameters": [
                    {
                        "key": "hazard_id",
                        "label": "Affected area",
                        "type": "select",
                        "options": hazards,
                        "default": hazards[0]["id"] if hazards else None,
                    },
                    {
                        "key": "flood_depth_m",
                        "label": "Flood depth",
                        "type": "number",
                        "unit": "m",
                        "default": self.DEFAULT_FLOOD_DEPTH_M,
                        "min": 0.2,
                        "max": 6.0,
                        "step": 0.05,
                    },
                ],
                "available": bool(graph and graph.warehouses),
            },
            {
                "id": "surge_demand",
                "title": "Demand surge",
                "summary": "Orders jump across every zone at once.",
                "parameters": [
                    {
                        "key": "demand_multiplier",
                        "label": "Demand",
                        "type": "number",
                        "unit": "x",
                        "default": self.DEFAULT_SURGE_MULTIPLIER,
                        "min": 1.05,
                        "max": 3.0,
                        "step": 0.05,
                    }
                ],
                "available": bool(graph and graph.customers),
            },
            {
                "id": "combined_disaster",
                "title": "Combined disaster",
                "summary": "A flood and a corridor closure at the same time.",
                "parameters": [
                    {
                        "key": "hazard_id",
                        "label": "Affected area",
                        "type": "select",
                        "options": hazards,
                        "default": hazards[0]["id"] if hazards else None,
                    }
                ],
                "available": bool(graph and graph.warehouses and graph.edges),
            },
            {
                "id": "auto",
                "title": "Auto stress test",
                "summary": "OptiFlow picks the scenario this network is most exposed to.",
                "parameters": [],
                "available": bool(graph and graph.warehouses),
            },
        ]

    # ------------------------------------------------------------------ selection

    def _flooded_warehouses(
        self,
        graph: LogisticsGraph,
        hazard_id: Optional[str]
    ) -> Tuple[List[str], Optional[Any], str]:
        """Warehouses standing inside the chosen hazard polygon, and the reason why."""
        hazard = None
        if graph.hazards:
            hazard = next((h for h in graph.hazards if h.hazard_id == hazard_id), graph.hazards[0])

        if hazard:
            inside = [w.id for w in graph.warehouses if _in_hazard(w.lat, w.lon, hazard)]
            if inside:
                return inside, hazard, "sited inside %s" % (hazard.description or hazard.hazard_type)

        # No polygon containment: fall back to the flood risk the Risk Agent scored.
        exposed = [w.id for w in graph.warehouses if w.flood_risk_score > 0.4]
        if exposed:
            return exposed, hazard, "flood risk score above 0.40"
        if graph.warehouses:
            worst = max(graph.warehouses, key=lambda w: w.flood_risk_score)
            return [worst.id], hazard, "highest flood risk in the network (%.2f)" % worst.flood_risk_score
        return [], hazard, "no warehouses in the network"

    def _corridor_edges(self, graph: LogisticsGraph) -> List[str]:
        """
        The costliest lanes in the graph. Closing a corridor takes out the legs
        that actually carry the freight rather than an arbitrary slice of edges.
        """
        lanes = sorted(graph.edges, key=lambda e: e.transport_cost_usd, reverse=True)
        return [e.id for e in lanes[:20]]

    def choose_scenario(
        self,
        graph: LogisticsGraph,
        solution: Optional[NetworkSolution]
    ) -> Tuple[str, Dict[str, Any], str]:
        """
        Picks the scenario this network is most exposed to, and says why. The
        choice is made from graph values only.
        """
        open_ids = set(solution.selected_warehouse_ids) if solution else set()
        open_whs = [w for w in graph.warehouses if not open_ids or w.id in open_ids]

        # 1. Anything open standing inside a mapped hazard polygon is the clearest exposure.
        for hazard in graph.hazards:
            inside = [w for w in open_whs if _in_hazard(w.lat, w.lon, hazard)]
            if inside:
                names = ", ".join(w.name for w in inside)
                return (
                    "flood_green_river",
                    {"hazard_id": hazard.hazard_id},
                    "%d open %s inside %s (%s)." % (
                        len(inside),
                        "facility is" if len(inside) == 1 else "facilities are",
                        hazard.description or hazard.hazard_type,
                        names,
                    ),
                )

        # 2. Otherwise the hub carrying the most demand is the single biggest dependency.
        if solution and open_whs:
            load: Dict[str, float] = {}
            for cust in graph.customers:
                wid = solution.customer_assignments.get(cust.id)
                if wid:
                    load[wid] = load.get(wid, 0.0) + cust.demand_units
            if load:
                worst_id = max(load, key=load.get)
                worst = next((w for w in graph.warehouses if w.id == worst_id), None)
                total = sum(load.values()) or 1.0
                if worst:
                    return (
                        "warehouse_failure",
                        {"target_warehouse_id": worst_id},
                        "%s carries %.0f%% of all demand, the largest single dependency in this plan." % (
                            worst.name, load[worst_id] / total * 100.0
                        ),
                    )

        # 3. Nothing facility-specific stands out, so test the transit corridor.
        return (
            "road_closure_corridor",
            {},
            "No single facility dominates and nothing open sits in a mapped hazard zone, "
            "so the transit corridor is the network's most exposed element.",
        )

    # ------------------------------------------------------------------ scenarios

    async def generate_scenario(
        self,
        scenario_type: str,
        graph: LogisticsGraph,
        params: Optional[Dict[str, Any]] = None,
        solution: Optional[NetworkSolution] = None
    ) -> Tuple[Disruption, List[AgentTraceEvent]]:
        trace_events: List[AgentTraceEvent] = []
        params = dict(params or {})
        disruption_id = "disrupt_%s" % uuid.uuid4().hex[:8]
        chosen_reason = ""

        if scenario_type == "auto":
            scenario_type, auto_params, chosen_reason = self.choose_scenario(graph, solution)
            params = dict(auto_params, **params)
            trace_events.append(AgentTraceEvent(
                event_id=str(uuid.uuid4()),
                agent_name=self.name,
                action="SelectScenario",
                status="progress",
                message="Auto stress test selected '%s': %s" % (scenario_type, chosen_reason),
                details={"scenario_type": scenario_type, "reason": chosen_reason, "params": params},
                timestamp=""
            ))

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="SimulateDisaster",
            status="start",
            message="Generating geographically grounded disruption scenario: '%s' using Mireye flood layers." % scenario_type,
            timestamp=""
        ))

        now = datetime.now(timezone.utc).isoformat()

        if scenario_type == "flood_green_river":
            affected_warehouses, hazard, reason = self._flooded_warehouses(graph, params.get("hazard_id"))
            affected_edges = [
                e.id for e in graph.edges
                if e.source_id in affected_warehouses or e.target_id in affected_warehouses
            ]
            depth = float(params.get("flood_depth_m") or self.DEFAULT_FLOOD_DEPTH_M)
            area = (hazard.description or hazard.hazard_type) if hazard else "the regional flood corridor"

            disruption = Disruption(
                disruption_id=disruption_id,
                disruption_type="flood",
                title="Flood across %s" % area,
                description=(
                    "A flood %.2f m deep inundates %s. %d %s knocked out (%s) and every lane "
                    "through them stops moving.%s" % (
                        depth, area, len(affected_warehouses),
                        "facility is" if len(affected_warehouses) == 1 else "facilities are",
                        reason,
                        (" " + chosen_reason) if chosen_reason else "",
                    )
                ),
                affected_warehouse_ids=affected_warehouses,
                affected_edge_ids=affected_edges,
                demand_multiplier=1.1,
                flood_depth_m=depth,
                timestamp=now
            )

        elif scenario_type == "road_closure_corridor":
            affected_edges = self._corridor_edges(graph)
            disruption = Disruption(
                disruption_id=disruption_id,
                disruption_type="road_closure",
                title="Main corridor closure",
                description=(
                    "The corridor carrying the network's costliest freight legs closes. "
                    "%d transport lanes stop moving; every facility stays standing.%s" % (
                        len(affected_edges), (" " + chosen_reason) if chosen_reason else "",
                    )
                ),
                affected_warehouse_ids=[],
                affected_edge_ids=affected_edges,
                demand_multiplier=1.0,
                flood_depth_m=None,
                timestamp=now
            )

        elif scenario_type == "surge_demand":
            multiplier = float(params.get("demand_multiplier") or self.DEFAULT_SURGE_MULTIPLIER)
            disruption = Disruption(
                disruption_id=disruption_id,
                disruption_type="demand_surge",
                title="Regional demand surge (+%.0f%%)" % ((multiplier - 1.0) * 100.0),
                description=(
                    "Orders rise to %.2fx normal across all %d demand zones at once. No facility "
                    "fails; anything above a warehouse's capacity simply cannot be shipped.%s" % (
                        multiplier, len(graph.customers),
                        (" " + chosen_reason) if chosen_reason else "",
                    )
                ),
                affected_warehouse_ids=[],
                affected_edge_ids=[],
                demand_multiplier=multiplier,
                flood_depth_m=None,
                timestamp=now
            )

        elif scenario_type == "combined_disaster":
            affected_warehouses, hazard, reason = self._flooded_warehouses(graph, params.get("hazard_id"))
            flood_edges = [
                e.id for e in graph.edges
                if e.source_id in affected_warehouses or e.target_id in affected_warehouses
            ]
            affected_edges = list(dict.fromkeys(flood_edges + self._corridor_edges(graph)))
            depth = float(params.get("flood_depth_m") or self.DEFAULT_FLOOD_DEPTH_M)
            area = (hazard.description or hazard.hazard_type) if hazard else "the regional flood corridor"

            disruption = Disruption(
                disruption_id=disruption_id,
                disruption_type="combined",
                title="Flood and corridor closure together",
                description=(
                    "A %.2f m flood across %s takes out %d %s (%s) while the main corridor closes, "
                    "blocking %d lanes in total." % (
                        depth, area, len(affected_warehouses),
                        "facility" if len(affected_warehouses) == 1 else "facilities",
                        reason, len(affected_edges),
                    )
                ),
                affected_warehouse_ids=affected_warehouses,
                affected_edge_ids=affected_edges,
                demand_multiplier=1.1,
                flood_depth_m=depth,
                timestamp=now
            )

        else:
            # Single facility outage. The caller may name the facility; otherwise
            # the first warehouse in the graph is used, as before.
            target_wh = params.get("target_warehouse_id")
            if not target_wh or not any(w.id == target_wh for w in graph.warehouses):
                target_wh = graph.warehouses[0].id if graph.warehouses else "cand_kent_south"
            wh_name = next((w.name for w in graph.warehouses if w.id == target_wh), target_wh)
            affected_edges = [e.id for e in graph.edges if e.source_id == target_wh or e.target_id == target_wh]
            disruption = Disruption(
                disruption_id=disruption_id,
                disruption_type="warehouse_failure",
                title="Outage at %s" % wh_name,
                description=(
                    "A power substation failure forces %s to shut down and evacuate. %d lanes "
                    "into and out of it stop moving.%s" % (
                        wh_name, len(affected_edges),
                        (" " + chosen_reason) if chosen_reason else "",
                    )
                ),
                affected_warehouse_ids=[target_wh],
                affected_edge_ids=affected_edges,
                demand_multiplier=1.0,
                flood_depth_m=None,
                timestamp=now
            )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="SimulateDisaster",
            status="complete",
            message="Disruption scenario active: %s. Impacted %d facilities and %d transport edges." % (
                disruption.title, len(disruption.affected_warehouse_ids), len(disruption.affected_edge_ids)
            ),
            details={
                "disruption_id": disruption.disruption_id,
                "type": disruption.disruption_type,
                "affected_warehouses": disruption.affected_warehouse_ids,
                "affected_edges_count": len(disruption.affected_edge_ids),
                "selected_by": "auto" if chosen_reason else "user",
            },
            timestamp=disruption.timestamp
        ))

        return disruption, trace_events

    # ------------------------------------------------------------------ impact

    def assess_impact(
        self,
        original_graph: LogisticsGraph,
        disrupted_graph: LogisticsGraph,
        solution: NetworkSolution,
        disruption: Disruption
    ) -> Tuple[ImpactReport, List[AgentTraceEvent]]:
        """
        Measures the network before and after the disruption with the plan's own
        assignments left in place. Nothing is re-optimised here: this is what
        happens if the network is not touched.
        """
        before = evaluate_network(original_graph, solution)
        after = evaluate_network(disrupted_graph, solution, demand_multiplier=disruption.demand_multiplier)

        failed = set(disruption.affected_warehouse_ids)
        blocked = set(disruption.affected_edge_ids)
        affected_customers = [
            c.id for c in disrupted_graph.customers
            if solution.customer_assignments.get(c.id) in failed
            or ("edge_%s_to_%s" % (solution.customer_assignments.get(c.id), c.id)) in blocked
        ]

        wh_names = [
            next((w.name for w in original_graph.warehouses if w.id == wid), wid)
            for wid in disruption.affected_warehouse_ids
        ]

        if wh_names:
            lead = "%s became unavailable, affecting %d customer %s." % (
                ", ".join(wh_names),
                len(affected_customers),
                "zone" if len(affected_customers) == 1 else "zones",
            )
        elif disruption.disruption_type == "demand_surge":
            lead = (
                "Every zone ordered %.2fx its usual volume, pushing demand past the capacity of "
                "the open facilities." % disruption.demand_multiplier
            )
        else:
            lead = "%d transport lanes closed, cutting %d customer %s off from their assigned facility." % (
                len(disruption.affected_edge_ids),
                len(affected_customers),
                "zone" if len(affected_customers) == 1 else "zones",
            )

        drop = before.demand_served_pct - after.demand_served_pct
        explanation = (
            "%s Demand served falls from %.1f%% to %.1f%% (%.1f points) with the plan left as it is." % (
                lead, before.demand_served_pct, after.demand_served_pct, drop
            )
        )

        report = ImpactReport(
            disruption_id=disruption.disruption_id,
            disruption_type=disruption.disruption_type,
            title=disruption.title,
            before=before,
            after=after,
            failed_warehouse_ids=disruption.affected_warehouse_ids,
            disrupted_edge_ids=disruption.affected_edge_ids,
            affected_customer_ids=affected_customers,
            explanation=explanation,
            timestamp=disruption.timestamp,
        )

        events = [AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="AssessImpact",
            status="warning" if drop > 0 else "complete",
            message=explanation,
            details={
                "demand_served_pct_before": before.demand_served_pct,
                "demand_served_pct_after": after.demand_served_pct,
                "avg_delivery_minutes_before": before.avg_delivery_minutes,
                "avg_delivery_minutes_after": after.avg_delivery_minutes,
                "affected_customers": len(affected_customers),
            },
            timestamp=disruption.timestamp
        )]

        return report, events
