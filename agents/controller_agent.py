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

        # Compile LangGraph StateGraph
        self.graph = self._build_langgraph_workflow()

    def _load_dataset(self) -> Dict[str, Any]:
        if os.path.exists(self.dataset_path):
            with open(self.dataset_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _emit_events(self, state: NetworkState, new_events: List[AgentTraceEvent]):
        if "trace_events" not in state or state["trace_events"] is None:
            state["trace_events"] = []
        for event in new_events:
            state["trace_events"].append(event)
            if self.event_callback:
                try:
                    self.event_callback(event)
                except Exception:
                    pass

    # ==================== LangGraph Node Callbacks ====================

    async def _node_site_generation(self, state: NetworkState) -> Dict[str, Any]:
        raw_candidates = self.raw_data.get("candidate_warehouses", [])
        candidates, events = await self.site_agent.execute(state, raw_candidates)
        self._emit_events(state, events)
        return {"candidates": candidates}

    async def _node_risk_scoring(self, state: NetworkState) -> Dict[str, Any]:
        candidates = state.get("candidates", [])
        raw_seeds_map = {c["id"]: c for c in self.raw_data.get("candidate_warehouses", [])}
        updated_candidates, events = await self.risk_agent.execute(candidates, raw_seeds_map)
        self._emit_events(state, events)
        return {"candidates": updated_candidates}

    async def _node_route_graph_building(self, state: NetworkState) -> Dict[str, Any]:
        candidates = state.get("candidates", [])
        inputs = state.get("inputs", InputSpec())
        suppliers_raw = self.raw_data.get("suppliers", [])
        customers_raw = self.raw_data.get("customers", [])
        hazards_raw = self.raw_data.get("hazard_zones", [])
        
        logistics_graph, events = await self.route_agent.execute(
            suppliers_raw=suppliers_raw,
            candidates=candidates,
            customers_raw=customers_raw,
            hazard_zones_raw=hazards_raw,
            region_name=inputs.region_name if hasattr(inputs, "region_name") else "Puget Sound Logistics Corridor",
            bounding_box=inputs.bounding_box if hasattr(inputs, "bounding_box") else [47.10, -122.50, 47.90, -121.90]
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

        report, events = self.critic_agent.execute_audit(candidates, logistics_graph, active_sol)
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
            critic_report=critic_report
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

    # ==================== High Level Orchestrator Methods ====================

    async def run_full_pipeline(self, inputs: Optional[InputSpec] = None) -> NetworkState:
        """Runs the entire 10-Agent pipeline start to finish."""
        initial_state: NetworkState = {
            "inputs": inputs or InputSpec(),
            "mireye_cache": {},
            "candidates": [],
            "graph": LogisticsGraph(),
            "frontier": [],
            "active_solution_id": "",
            "disruption_log": [],
            "critic_flags": [],
            "critic_report": None,
            "narrative": "",
            "trace_events": []
        }

        # Run compiled LangGraph state machine
        final_state = await self.graph.ainvoke(initial_state)
        return final_state

    async def trigger_disruption(
        self,
        current_state: NetworkState,
        scenario_type: str = "flood_green_river"
    ) -> NetworkState:
        """
        Triggers a geographically grounded disruption scenario and performs
        a warm-started sub-60s recovery re-solve.
        """
        graph = current_state.get("graph")
        frontier = current_state.get("frontier", [])
        active_id = current_state.get("active_solution_id")
        active_sol = next((s for s in frontier if s.solution_id == active_id), frontier[0] if frontier else None)

        if not graph or not active_sol:
            return current_state

        # 1. Disaster Simulation Agent generates scenario
        disruption, dis_events = await self.disaster_agent.generate_scenario(scenario_type, graph)
        self._emit_events(current_state, dis_events)

        if "disruption_log" not in current_state or current_state["disruption_log"] is None:
            current_state["disruption_log"] = []
        current_state["disruption_log"].append(disruption)

        # 2. Recovery / Verification Agent executes warm-started re-optimization
        recovered_sol, mutated_graph, elapsed_sec, rec_events = await self.recovery_agent.execute_recovery(
            original_graph=graph,
            active_solution=active_sol,
            disruption=disruption
        )
        self._emit_events(current_state, rec_events)

        # Update state with recovered network
        current_state["graph"] = mutated_graph
        current_state["frontier"].insert(0, recovered_sol)
        current_state["active_solution_id"] = recovered_sol.solution_id

        # 3. Critic audits post-recovery state
        candidates = current_state.get("candidates", [])
        report, crit_events = self.critic_agent.execute_audit(candidates, mutated_graph, recovered_sol)
        self._emit_events(current_state, crit_events)
        current_state["critic_report"] = report

        # 4. Narrator updates explanation
        inputs = current_state.get("inputs", InputSpec())
        region_name = inputs.region_name if hasattr(inputs, "region_name") else "Puget Sound Corridor"
        narrative, nar_events = self.narrator_agent.generate_narrative(
            inputs_region=region_name,
            candidates=candidates,
            graph=mutated_graph,
            frontier=current_state["frontier"],
            active_solution=recovered_sol,
            disruption=disruption,
            critic_report=report
        )
        self._emit_events(current_state, nar_events)
        current_state["narrative"] = narrative

        return current_state
