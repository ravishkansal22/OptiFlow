import logging
import os
import json
import uuid
from typing import Dict, Any, List, Optional, Callable
from langgraph.graph import StateGraph, END

from schemas.state import (
    NetworkState,
    InputSpec,
    Candidate,
    LogisticsGraph,
    NetworkSolution,
    Disruption,
    CriticReport,
    ImpactReport,
    RecoveryReport,
    AgentTraceEvent
)
from agents.mireye_gateway_agent import MireyeGatewayAgent
from agents.site_agent import SiteGenerationAgent
from agents.risk_agent import RiskAgent
from agents.route_agent import RouteGraphBuilderAgent
from agents.optimization_agent import OptimizationAgent
from agents.disaster_agent import DisasterSimulationAgent
from agents.recovery_agent import RecoveryVerificationAgent
from agents.critic_agent import CriticAgent
from agents.narrator_agent import NarratorAgent
from agents.network_metrics import evaluate_network

log = logging.getLogger("optiflow.pipeline")


class ControllerAgent:
    """
    Controller / Supervisor Agent:
    Orchestrates the 10-Agent LangGraph State Machine passing NetworkState.
    Controls execution flow, state checkpointing, WebSocket event emission,
    and sub-60s disaster recovery re-entry.
    """

    def __init__(
        self,
        gateway: Optional[MireyeGatewayAgent] = None,
        event_callback: Optional[Callable[[AgentTraceEvent], Any]] = None
    ):
        self.gateway = gateway or MireyeGatewayAgent()
        self.event_callback = event_callback
        # Events already handed to the callback as they happened, so the batch
        # emit at the end of a node does not send them a second time.
        self._streamed_event_ids: set = set()
        
        # Instantiate 9 domain agents
        self.site_agent = SiteGenerationAgent(self.gateway)
        self.risk_agent = RiskAgent(self.gateway)
        self.route_agent = RouteGraphBuilderAgent(self.gateway)
        self.opt_agent = OptimizationAgent()
        self.disaster_agent = DisasterSimulationAgent(self.gateway)
        self.recovery_agent = RecoveryVerificationAgent(self.gateway, self.opt_agent)
        self.critic_agent = CriticAgent()
        self.narrator_agent = NarratorAgent()

        # Load pilot region dataset
        self.dataset_path = os.path.join(os.path.dirname(__file__), "..", "data", "sample_region.json")
        self.raw_data = self._load_dataset()

        # Set for the duration of a run when the caller supplies its own
        # candidate warehouses (see run_full_pipeline). None means use the dataset.
        self._candidate_seed_override: Optional[List[Dict[str, Any]]] = None
        # Same idea for the demand and supply side of the graph.
        self._supplier_override: Optional[List[Dict[str, Any]]] = None
        self._customer_override: Optional[List[Dict[str, Any]]] = None

        # Compile LangGraph StateGraph
        self.graph = self._build_langgraph_workflow()
        # The same nodes, split at the point where a person reviews the shortlist:
        # everything geospatial runs first, the solver runs on demand afterwards.
        self.screening_graph = self._build_screening_workflow()
        self.optimization_graph = self._build_optimization_workflow()

    def _candidate_seeds(self) -> List[Dict[str, Any]]:
        """Candidate warehouses for the active run: caller override, else dataset."""
        if self._candidate_seed_override is not None:
            return self._candidate_seed_override
        return self.raw_data.get("candidate_warehouses", [])

    def _suppliers(self) -> List[Dict[str, Any]]:
        if self._supplier_override is not None:
            return self._supplier_override
        return self.raw_data.get("suppliers", [])

    def _customers(self) -> List[Dict[str, Any]]:
        if self._customer_override is not None:
            return self._customer_override
        return self.raw_data.get("customers", [])

    def _load_dataset(self) -> Dict[str, Any]:
        if os.path.exists(self.dataset_path):
            with open(self.dataset_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _stream_event(self, event: AgentTraceEvent):
        """
        Hands one event to the callback the moment an agent produces it.

        Agents that work through long lists (every candidate site, every routed
        leg) call this so the UI can follow along instead of waiting for the
        whole node to finish.
        """
        if not self.event_callback:
            return
        self._streamed_event_ids.add(event.event_id)
        try:
            self.event_callback(event)
        except Exception:
            pass

    def _emit_events(self, state: NetworkState, new_events: List[AgentTraceEvent]):
        if "trace_events" not in state or state["trace_events"] is None:
            state["trace_events"] = []
        for event in new_events:
            state["trace_events"].append(event)
            level = {
                "error": logging.ERROR,
                "warning": logging.WARNING,
                "complete": logging.INFO,
                "start": logging.INFO,
            }.get(event.status, logging.DEBUG)
            log.log(level, "[%-28s] %-8s %s", event.agent_name, event.status, event.message)
            if self.event_callback and event.event_id not in self._streamed_event_ids:
                try:
                    self.event_callback(event)
                except Exception:
                    pass
            self._streamed_event_ids.discard(event.event_id)

    # ==================== LangGraph Node Callbacks ====================

    async def _node_site_generation(self, state: NetworkState) -> Dict[str, Any]:
        raw_candidates = self._candidate_seeds()
        candidates, events = await self.site_agent.execute(
            state, raw_candidates, on_event=self._stream_event
        )
        self._emit_events(state, events)
        return {"candidates": candidates}

    async def _node_risk_scoring(self, state: NetworkState) -> Dict[str, Any]:
        candidates = state.get("candidates", [])
        raw_seeds_map = {c["id"]: c for c in self._candidate_seeds()}
        updated_candidates, events = await self.risk_agent.execute(
            candidates, raw_seeds_map, on_event=self._stream_event
        )
        self._emit_events(state, events)
        return {"candidates": updated_candidates}

    async def _node_route_graph_building(self, state: NetworkState) -> Dict[str, Any]:
        candidates = state.get("candidates", [])
        inputs = state.get("inputs", InputSpec())
        suppliers_raw = self._suppliers()
        customers_raw = self._customers()
        hazards_raw = self.raw_data.get("hazard_zones", [])
        
        logistics_graph, events = await self.route_agent.execute(
            suppliers_raw=suppliers_raw,
            candidates=candidates,
            customers_raw=customers_raw,
            hazard_zones_raw=hazards_raw,
            region_name=inputs.region_name if hasattr(inputs, "region_name") else "Puget Sound Logistics Corridor",
            bounding_box=inputs.bounding_box if hasattr(inputs, "bounding_box") else [47.10, -122.50, 47.90, -121.90],
            on_event=self._stream_event
        )
        self._emit_events(state, events)
        return {"graph": logistics_graph}

    async def _node_optimization(self, state: NetworkState) -> Dict[str, Any]:
        logistics_graph = state.get("graph")
        inputs = state.get("inputs", InputSpec())
        if not isinstance(inputs, InputSpec):
            inputs = InputSpec(**inputs)

        frontier, best_sol, events = await self.opt_agent.execute(logistics_graph, inputs)
        self._emit_events(state, events)
        return {
            "frontier": frontier,
            "active_solution_id": best_sol.solution_id if best_sol else ""
        }

    async def _node_critic_audit(self, state: NetworkState) -> Dict[str, Any]:
        candidates = state.get("candidates", [])
        logistics_graph = state.get("graph")
        frontier = state.get("frontier", [])
        active_id = state.get("active_solution_id")
        active_sol = next((s for s in frontier if s.solution_id == active_id), frontier[0] if frontier else None)

        if not active_sol:
            return {"critic_flags": ["No active solution found to audit."]}

        inputs = state.get("inputs", InputSpec())
        if not isinstance(inputs, InputSpec):
            inputs = InputSpec(**inputs)
        report, events = self.critic_agent.execute_audit(
            candidates,
            logistics_graph,
            active_sol,
            budget_limit_usd=inputs.budget_limit_usd,
            min_demand_coverage_pct=inputs.min_demand_coverage_pct,
        )
        self._emit_events(state, events)
        return {
            "critic_report": report,
            "critic_flags": report.flags + report.constraint_violations
        }

    async def _node_narrator_reporting(self, state: NetworkState) -> Dict[str, Any]:
        inputs = state.get("inputs", InputSpec())
        region_name = inputs.region_name if hasattr(inputs, "region_name") else "Puget Sound Corridor"
        candidates = state.get("candidates", [])
        logistics_graph = state.get("graph")
        frontier = state.get("frontier", [])
        active_id = state.get("active_solution_id")
        active_sol = next((s for s in frontier if s.solution_id == active_id), frontier[0] if frontier else None)
        disruption_log = state.get("disruption_log", [])
        latest_disruption = disruption_log[-1] if disruption_log else None
        critic_report = state.get("critic_report")

        narrative, events = self.narrator_agent.generate_narrative(
            inputs_region=region_name,
            candidates=candidates,
            graph=logistics_graph,
            frontier=frontier,
            active_solution=active_sol,
            disruption=latest_disruption,
            critic_report=critic_report,
            target_warehouses=getattr(inputs, "target_warehouses_to_open", None)
        )
        self._emit_events(state, events)
        return {"narrative": narrative}

    def _build_langgraph_workflow(self):
        """Builds the compiled LangGraph StateGraph pipeline."""
        workflow = StateGraph(NetworkState)

        # Add Nodes
        workflow.add_node("site_generation", self._node_site_generation)
        workflow.add_node("risk_scoring", self._node_risk_scoring)
        workflow.add_node("route_graph_building", self._node_route_graph_building)
        workflow.add_node("optimization", self._node_optimization)
        workflow.add_node("critic_audit", self._node_critic_audit)
        workflow.add_node("narrator_reporting", self._node_narrator_reporting)

        # Add Sequential Edges
        workflow.set_entry_point("site_generation")
        workflow.add_edge("site_generation", "risk_scoring")
        workflow.add_edge("risk_scoring", "route_graph_building")
        workflow.add_edge("route_graph_building", "optimization")
        workflow.add_edge("optimization", "critic_audit")
        workflow.add_edge("critic_audit", "narrator_reporting")
        workflow.add_edge("narrator_reporting", END)

        return workflow.compile()

    def _build_screening_workflow(self):
        """Site -> Risk -> Route. Everything needed to review candidate sites."""
        workflow = StateGraph(NetworkState)
        workflow.add_node("site_generation", self._node_site_generation)
        workflow.add_node("risk_scoring", self._node_risk_scoring)
        workflow.add_node("route_graph_building", self._node_route_graph_building)
        workflow.set_entry_point("site_generation")
        workflow.add_edge("site_generation", "risk_scoring")
        workflow.add_edge("risk_scoring", "route_graph_building")
        workflow.add_edge("route_graph_building", END)
        return workflow.compile()

    def _build_optimization_workflow(self):
        """Optimization -> Critic -> Narrator, over an already-screened graph."""
        workflow = StateGraph(NetworkState)
        workflow.add_node("optimization", self._node_optimization)
        workflow.add_node("critic_audit", self._node_critic_audit)
        workflow.add_node("narrator_reporting", self._node_narrator_reporting)
        workflow.set_entry_point("optimization")
        workflow.add_edge("optimization", "critic_audit")
        workflow.add_edge("critic_audit", "narrator_reporting")
        workflow.add_edge("narrator_reporting", END)
        return workflow.compile()

    # ==================== High Level Orchestrator Methods ====================

    @staticmethod
    def _blank_state(inputs: Optional[InputSpec] = None) -> NetworkState:
        return {
            "inputs": inputs or InputSpec(),
            "mireye_cache": {},
            "candidates": [],
            "graph": LogisticsGraph(),
            "frontier": [],
            "active_solution_id": "",
            "disruption_log": [],
            "impact_report": None,
            "recovery_report": None,
            "pre_disruption_graph": None,
            "pre_disruption_solution_id": "",
            "critic_flags": [],
            "critic_report": None,
            "narrative": "",
            "trace_events": []
        }

    async def run_screening_pipeline(
        self,
        inputs: Optional[InputSpec] = None,
        candidate_seeds: Optional[List[Dict[str, Any]]] = None,
        suppliers: Optional[List[Dict[str, Any]]] = None,
        customers: Optional[List[Dict[str, Any]]] = None
    ) -> NetworkState:
        """
        Phase one: Site Generation, Risk and Route/Graph Building.

        Produces the screened candidate list and the weighted logistics graph so
        the shortlist can be reviewed before any solver time is spent.
        """
        initial_state = self._blank_state(inputs)
        self._candidate_seed_override = candidate_seeds
        self._supplier_override = suppliers
        self._customer_override = customers
        try:
            return await self.screening_graph.ainvoke(initial_state)
        finally:
            self._candidate_seed_override = None
            self._supplier_override = None
            self._customer_override = None

    async def run_optimization_pipeline(self, current_state: NetworkState) -> NetworkState:
        """
        Phase two: MILP + NSGA-II, the Critic audit and the Narrator report,
        run against a state that already holds a screened graph.
        """
        if not current_state.get("graph"):
            raise ValueError("No logistics graph in state. Run the screening phase first.")
        result = await self.optimization_graph.ainvoke(current_state)
        merged = dict(current_state)
        merged.update(result)
        return merged

    async def run_full_pipeline(
        self,
        inputs: Optional[InputSpec] = None,
        candidate_seeds: Optional[List[Dict[str, Any]]] = None,
        suppliers: Optional[List[Dict[str, Any]]] = None,
        customers: Optional[List[Dict[str, Any]]] = None
    ) -> NetworkState:
        """
        Runs the entire 10-Agent pipeline start to finish.

        candidate_seeds, when given, replaces the region dataset's candidate
        warehouses for this run. Suppliers, customers and hazards still come
        from the dataset.
        """
        initial_state: NetworkState = self._blank_state(inputs)

        # Run compiled LangGraph state machine
        self._candidate_seed_override = candidate_seeds
        self._supplier_override = suppliers
        self._customer_override = customers
        try:
            final_state = await self.graph.ainvoke(initial_state)
        finally:
            self._candidate_seed_override = None
            self._supplier_override = None
            self._customer_override = None
        return final_state

    async def apply_disruption(
        self,
        current_state: NetworkState,
        scenario_type: str = "flood_green_river",
        params: Optional[Dict[str, Any]] = None
    ) -> NetworkState:
        """
        Runs the Disaster Simulation Agent only: generates a geographically
        grounded scenario, marks the graph accordingly and measures what it did
        to the current plan. No recovery is attempted here, so the damage is
        visible before the network is repaired.
        """
        graph = current_state.get("graph")
        frontier = current_state.get("frontier", [])
        active_id = current_state.get("active_solution_id")
        active_sol = next((s for s in frontier if s.solution_id == active_id), frontier[0] if frontier else None)

        if not graph or not active_sol:
            return current_state

        # Keep a clean copy the first time round so another scenario can be run
        # against the same starting network.
        if not current_state.get("pre_disruption_graph"):
            current_state["pre_disruption_graph"] = graph.model_copy(deep=True)
            current_state["pre_disruption_solution_id"] = active_sol.solution_id

        healthy_graph = current_state["pre_disruption_graph"]

        disruption, dis_events = await self.disaster_agent.generate_scenario(
            scenario_type, healthy_graph, params=params, solution=active_sol
        )
        self._emit_events(current_state, dis_events)

        # Mark the graph: affected facilities go down, their lanes stop moving.
        mutated_graph = healthy_graph.model_copy(deep=True)
        disabled_wh = set(disruption.affected_warehouse_ids)
        disabled_edges = set(disruption.affected_edge_ids)
        for wh in mutated_graph.warehouses:
            if wh.id in disabled_wh:
                wh.status = "flooded" if disruption.disruption_type in ("flood", "combined") else "offline"
        for edge in mutated_graph.edges:
            if edge.id in disabled_edges or edge.source_id in disabled_wh or edge.target_id in disabled_wh:
                edge.status = "disrupted"

        report, impact_events = self.disaster_agent.assess_impact(
            healthy_graph, mutated_graph, active_sol, disruption
        )
        self._emit_events(current_state, impact_events)

        if not current_state.get("disruption_log"):
            current_state["disruption_log"] = []
        current_state["disruption_log"].append(disruption)
        current_state["graph"] = mutated_graph
        current_state["impact_report"] = report
        current_state["recovery_report"] = None

        return current_state

    async def recover_from_disruption(self, current_state: NetworkState) -> NetworkState:
        """
        Runs the Recovery / Verification Agent against the latest disruption,
        then re-audits with the Critic and re-writes the Narrator report. The
        recovered network is measured the same way the impact was measured, so
        the before and after figures are comparable.
        """
        graph = current_state.get("graph")
        disruption_log = current_state.get("disruption_log", [])
        impact = current_state.get("impact_report")
        if not graph or not disruption_log or not impact:
            return current_state

        disruption = disruption_log[-1]
        frontier = current_state.get("frontier", [])
        pre_id = current_state.get("pre_disruption_solution_id") or current_state.get("active_solution_id")
        pre_sol = next((s for s in frontier if s.solution_id == pre_id), frontier[0] if frontier else None)
        if not pre_sol:
            return current_state

        recovered_sol, mutated_graph, elapsed_sec, rec_events = await self.recovery_agent.execute_recovery(
            original_graph=graph,
            active_solution=pre_sol,
            disruption=disruption
        )
        self._emit_events(current_state, rec_events)

        current_state["graph"] = mutated_graph
        current_state["frontier"].insert(0, recovered_sol)
        current_state["active_solution_id"] = recovered_sol.solution_id

        # Measure the recovered network exactly as the impact was measured.
        after = evaluate_network(
            mutated_graph, recovered_sol, demand_multiplier=disruption.demand_multiplier
        )
        reassigned = [
            c.id for c in mutated_graph.customers
            if pre_sol.customer_assignments.get(c.id) != recovered_sol.customer_assignments.get(c.id)
        ]
        was_open = set(pre_sol.selected_warehouse_ids)
        now_open = set(recovered_sol.selected_warehouse_ids)
        activated = sorted(now_open - was_open)
        deactivated = sorted(was_open - now_open)

        wh_names = {w.id: w.name for w in mutated_graph.warehouses}
        failed_names = [wh_names.get(w, w) for w in disruption.affected_warehouse_ids]
        taken_names = [wh_names.get(w, w) for w in sorted(now_open)]

        if failed_names:
            summary = (
                "%s was unavailable after %s. OptiFlow reassigned %d customer %s to %s and "
                "generated alternative routes while holding capacity constraints, taking demand "
                "served from %.1f%% back to %.1f%%." % (
                    ", ".join(failed_names), disruption.title.lower(), len(reassigned),
                    "zone" if len(reassigned) == 1 else "zones",
                    ", ".join(taken_names) or "the surviving facilities",
                    impact.after.demand_served_pct, after.demand_served_pct,
                )
            )
        elif disruption.affected_edge_ids:
            summary = (
                "No facility was lost, but %d lanes were blocked. OptiFlow re-routed %d customer "
                "%s across %s, taking demand served from %.1f%% back to %.1f%%." % (
                    len(disruption.affected_edge_ids), len(reassigned),
                    "zone" if len(reassigned) == 1 else "zones",
                    ", ".join(taken_names) or "the surviving facilities",
                    impact.after.demand_served_pct, after.demand_served_pct,
                )
            )
        else:
            # Nothing failed and nothing closed: the network is simply carrying
            # more than it was built for.
            shortfall = max(0.0, after.demand_total_units - after.demand_served_units)
            summary = (
                "No facility failed and no lane closed. Demand rose to %.2fx normal, and %s "
                "together can ship %.1f%% of it. OptiFlow re-checked every assignment against the "
                "higher volume; %s" % (
                    disruption.demand_multiplier,
                    ", ".join(taken_names) or "the open facilities",
                    after.demand_served_pct,
                    (
                        "%d zones were moved to a facility with room left."
                        % len(reassigned)
                        if reassigned
                        else "no reassignment helps, because every open facility is already at "
                             "capacity. Serving the remaining %s units needs more capacity, not "
                             "better routing." % format(round(shortfall), ",")
                    ),
                )
            )

        recovery_report = RecoveryReport(
            disruption_id=disruption.disruption_id,
            before=impact.after,
            after=after,
            recovery_seconds=round(elapsed_sec, 3),
            customers_reassigned=len(reassigned),
            routes_changed=len(reassigned),
            warehouses_activated=activated,
            warehouses_deactivated=deactivated,
            # What the recovered network costs above the healthy network it started from.
            added_cost_usd=round(after.total_cost_usd - impact.before.total_cost_usd, 2),
            summary=summary,
            timestamp=disruption.timestamp,
        )
        current_state["recovery_report"] = recovery_report

        # Critic re-audits the recovered plan.
        audit_inputs = current_state.get("inputs", InputSpec())
        if not isinstance(audit_inputs, InputSpec):
            audit_inputs = InputSpec(**audit_inputs)
        report, crit_events = self.critic_agent.execute_audit(
            current_state.get("candidates", []),
            mutated_graph,
            recovered_sol,
            budget_limit_usd=audit_inputs.budget_limit_usd,
            min_demand_coverage_pct=audit_inputs.min_demand_coverage_pct,
        )
        self._emit_events(current_state, crit_events)
        current_state["critic_report"] = report
        current_state["critic_flags"] = report.flags + report.constraint_violations

        # Narrator re-writes the explanation around the recovered plan.
        inputs = current_state.get("inputs", InputSpec())
        region_name = inputs.region_name if hasattr(inputs, "region_name") else "Puget Sound Corridor"
        narrative, nar_events = self.narrator_agent.generate_narrative(
            inputs_region=region_name,
            candidates=current_state.get("candidates", []),
            graph=mutated_graph,
            frontier=current_state["frontier"],
            active_solution=recovered_sol,
            disruption=disruption,
            critic_report=report
        )
        self._emit_events(current_state, nar_events)
        current_state["narrative"] = narrative

        return current_state

    async def trigger_disruption(
        self,
        current_state: NetworkState,
        scenario_type: str = "flood_green_river",
        params: Optional[Dict[str, Any]] = None
    ) -> NetworkState:
        """
        Disruption followed immediately by the warm-started sub-60s recovery.
        Kept for callers that want both halves in one step; the UI runs them
        separately so the damage is visible before the network is repaired.
        """
        state = await self.apply_disruption(current_state, scenario_type, params)
        return await self.recover_from_disruption(state)

    def restore_network(self, current_state: NetworkState) -> NetworkState:
        """
        Puts the network back as it was before the first disruption, so another
        scenario can be tested against the same starting point.
        """
        healthy = current_state.get("pre_disruption_graph")
        if not healthy:
            return current_state

        current_state["graph"] = healthy.model_copy(deep=True)
        pre_id = current_state.get("pre_disruption_solution_id")
        frontier = current_state.get("frontier", [])
        # Drop recovered plans; they only describe a network that no longer exists.
        current_state["frontier"] = [s for s in frontier if not s.solution_id.startswith("sol_recov_")]
        if pre_id and any(s.solution_id == pre_id for s in current_state["frontier"]):
            current_state["active_solution_id"] = pre_id
        elif current_state["frontier"]:
            current_state["active_solution_id"] = current_state["frontier"][0].solution_id
        current_state["impact_report"] = None
        current_state["recovery_report"] = None
        current_state["pre_disruption_graph"] = None
        current_state["pre_disruption_solution_id"] = ""
        return current_state
