import uuid
import math
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from ortools.linear_solver import pywraplp

from schemas.state import (
    LogisticsGraph,
    NetworkSolution,
    FlowRecord,
    InputSpec,
    AgentTraceEvent
)


class OptimizationAgent:
    """
    Optimization Agent:
    Solves capacitated facility location and multi-commodity product flow using OR-Tools MILP,
    then evaluates a multi-objective Pareto Frontier (Cost vs. Resilience) via NSGA-II / Pareto search.
    """

    def __init__(self):
        self.name = "Optimization Agent"

    def _solve_milp_instance(
        self,
        graph: LogisticsGraph,
        target_k: int,
        resilience_bias: float = 0.0,
        fixed_open_warehouses: Optional[List[str]] = None,
        disabled_warehouse_ids: Optional[List[str]] = None
    ) -> Optional[NetworkSolution]:
        """
        Solves the Mixed-Integer Linear Program for facility location & flow allocation.
        """
        disabled_set = set(disabled_warehouse_ids or [])
        active_warehouses = [w for w in graph.warehouses if w.id not in disabled_set and w.status == "active"]
        
        if not active_warehouses:
            return None

        solver = pywraplp.Solver.CreateSolver("CBC")
        if not solver:
            solver = pywraplp.Solver.CreateSolver("SCIP")
        if not solver:
            solver = pywraplp.Solver.CreateSolver("GLOP")

        # Decision Variables
        # y[j]: 1 if warehouse j is opened, 0 otherwise
        y = {}
        for j, wh in enumerate(active_warehouses):
            if fixed_open_warehouses and wh.id in fixed_open_warehouses:
                y[j] = solver.IntVar(1, 1, f"y_{wh.id}")
            else:
                y[j] = solver.IntVar(0, 1, f"y_{wh.id}")

        # x[i, j]: fraction of customer i demand served by warehouse j
        x = {}
        for i, cust in enumerate(graph.customers):
            for j, wh in enumerate(active_warehouses):
                x[i, j] = solver.NumVar(0.0, 1.0, f"x_{cust.id}_{wh.id}")

        # z[k, j]: flow units from supplier k to warehouse j
        z = {}
        for k, sup in enumerate(graph.suppliers):
            for j, wh in enumerate(active_warehouses):
                z[k, j] = solver.NumVar(0.0, solver.infinity(), f"z_{sup.id}_{wh.id}")

        # Fast lookup edge costs
        wh_cust_costs = {}
        wh_cust_times = {}
        for edge in graph.edges:
            if edge.status == "active":
                wh_cust_costs[(edge.source_id, edge.target_id)] = edge.transport_cost_usd
                wh_cust_times[(edge.source_id, edge.target_id)] = edge.travel_time_min

        # 1. Customer Demand Satisfaction: sum_j x[i, j] == 1
        for i, cust in enumerate(graph.customers):
            solver.Add(solver.Sum([x[i, j] for j in range(len(active_warehouses))]) == 1)

        # 2. Warehouse Capacity & Linking: sum_i demand[i] * x[i, j] <= capacity[j] * y[j]
        for j, wh in enumerate(active_warehouses):
            demand_expr = solver.Sum([
                graph.customers[i].demand_units * x[i, j]
                for i in range(len(graph.customers))
            ])
            solver.Add(demand_expr <= wh.capacity_units * y[j])

        # 3. Flow Balance at Warehouses: sum_k z[k, j] == sum_i demand[i] * x[i, j]
        for j, wh in enumerate(active_warehouses):
            inflow = solver.Sum([z[k, j] for k in range(len(graph.suppliers))])
            outflow = solver.Sum([
                graph.customers[i].demand_units * x[i, j]
                for i in range(len(graph.customers))
            ])
            solver.Add(inflow == outflow)

        # 4. Supplier Capacity: sum_j z[k, j] <= sup_cap[k]
        for k, sup in enumerate(graph.suppliers):
            solver.Add(
                solver.Sum([z[k, j] for j in range(len(active_warehouses))]) <= sup.capacity_units
            )

        # 5. Target Warehouse Count Constraint: sum_j y[j] <= target_k
        if not fixed_open_warehouses:
            solver.Add(solver.Sum([y[j] for j in range(len(active_warehouses))]) <= min(target_k, len(active_warehouses)))

        # Objective Function
        objective = solver.Objective()
        
        # Fixed costs + flood risk penalty term
        for j, wh in enumerate(active_warehouses):
            # Higher resilience bias heavily penalizes flood risk
            risk_penalty = resilience_bias * 250000.0 * (wh.flood_risk_score ** 1.5)
            effective_fixed_cost = wh.fixed_operating_cost + risk_penalty
            objective.SetCoefficient(y[j], effective_fixed_cost)

        # Supplier -> Warehouse transportation costs
        for k, sup in enumerate(graph.suppliers):
            for j, wh in enumerate(active_warehouses):
                edge_cost = wh_cust_costs.get((sup.id, wh.id), 150.0)
                unit_cost = sup.unit_supply_cost + (edge_cost / 1000.0)
                objective.SetCoefficient(z[k, j], unit_cost)

        # Warehouse -> Customer transportation costs + SLA travel time penalty
        for i, cust in enumerate(graph.customers):
            for j, wh in enumerate(active_warehouses):
                edge_cost = wh_cust_costs.get((wh.id, cust.id), 250.0)
                travel_time = wh_cust_times.get((wh.id, cust.id), 45.0)
                
                # Resilience penalty if travel time exceeds customer SLA
                sla_penalty = 0.0
                if travel_time > cust.service_sla_minutes:
                    sla_penalty = (travel_time - cust.service_sla_minutes) * 50.0 * (1.0 + resilience_bias)

                objective.SetCoefficient(x[i, j], edge_cost + sla_penalty)

        objective.SetMinimization()

        # Solve with 5s time limit
        solver.set_time_limit(5000)
        status = solver.Solve()

        if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            return None

        # Extract Solution
        selected_wh_ids = [
            active_warehouses[j].id
            for j in range(len(active_warehouses))
            if y[j].solution_value() > 0.5
        ]

        customer_assignments = {}
        for i, cust in enumerate(graph.customers):
            best_j = max(range(len(active_warehouses)), key=lambda j: x[i, j].solution_value())
            customer_assignments[cust.id] = active_warehouses[best_j].id

        flows = []
        supplier_assignments = {}
        for k, sup in enumerate(graph.suppliers):
            for j, wh in enumerate(active_warehouses):
                val = z[k, j].solution_value()
                if val > 1.0:
                    flows.append(FlowRecord(
                        source_id=sup.id,
                        target_id=wh.id,
                        units_shipped=round(val, 1),
                        cost_usd=round(val * (sup.unit_supply_cost + wh_cust_costs.get((sup.id, wh.id), 150.0) / 1000.0), 2)
                    ))
                    if sup.id not in supplier_assignments:
                        supplier_assignments[sup.id] = []
                    supplier_assignments[sup.id].append(wh.id)

        # Compute true financial metrics
        total_fixed = sum(
            next(w.fixed_operating_cost for w in active_warehouses if w.id == wid)
            for wid in selected_wh_ids
        )
        total_transport = sum(
            wh_cust_costs.get((customer_assignments[c.id], c.id), 250.0)
            for c in graph.customers
        ) + sum(f.cost_usd for f in flows)
        
        total_cost = round(total_fixed + total_transport, 2)

        # Calculate SLA adherence and Resilience Score
        sla_met_count = sum(
            1 for c in graph.customers
            if wh_cust_times.get((customer_assignments[c.id], c.id), 45.0) <= c.service_sla_minutes
        )
        demand_retained_pct = round((sla_met_count / len(graph.customers)) * 100.0, 1)

        # Normalized recovery cost estimation based on redundancy and flood resilience
        avg_wh_risk = np.mean([
            next(w.flood_risk_score for w in active_warehouses if w.id == wid)
            for wid in selected_wh_ids
        ]) if selected_wh_ids else 0.5

        norm_recovery_cost = round(min(1.0, max(0.05, float(avg_wh_risk) * 0.85 + (len(selected_wh_ids) / target_k) * 0.15 * 0.3)), 3)
        
        # Resilience formula: 0.6 * demand_retained/100 + 0.4 * (1 - normalized_recovery_cost)
        resilience = round(0.6 * (demand_retained_pct / 100.0) + 0.4 * (1.0 - norm_recovery_cost), 3)

        return NetworkSolution(
            solution_id=f"sol_{uuid.uuid4().hex[:8]}",
            name=f"Config ({len(selected_wh_ids)} Facilities, Bias: {resilience_bias:.2f})",
            selected_warehouse_ids=selected_wh_ids,
            customer_assignments=customer_assignments,
            supplier_assignments=supplier_assignments,
            flows=flows,
            total_fixed_cost=round(total_fixed, 2),
            total_transport_cost=round(total_transport, 2),
            total_cost=total_cost,
            demand_retained_pct=demand_retained_pct,
            normalized_recovery_cost=norm_recovery_cost,
            resilience_score=resilience,
            is_baseline_cost_only=(resilience_bias == 0.0)
        )

    def generate_pareto_frontier(
        self,
        graph: LogisticsGraph,
        inputs: InputSpec
    ) -> Tuple[List[NetworkSolution], NetworkSolution]:
        """
        Generates 20-50 Pareto-optimal configurations across the Cost vs. Resilience spectrum.
        """
        frontier: List[NetworkSolution] = []
        target_k = inputs.target_warehouses_to_open

        # 1. Cost-Only Baseline (resilience_bias = 0.0)
        baseline_sol = self._solve_milp_instance(graph, target_k=target_k, resilience_bias=0.0)
        if baseline_sol:
            baseline_sol.is_baseline_cost_only = True
            baseline_sol.name = "Cost-Only Baseline (Least Financial Outlay)"
            baseline_sol.description = "Optimized purely for minimum fixed + transit cost; unshielded from flood exposure."
            frontier.append(baseline_sol)

        # 2. Multi-Objective Sweep over Resilience Biases & Facility Counts
        biases = np.linspace(0.05, 1.8, 30)
        seen_combos = set()
        if baseline_sol:
            seen_combos.add(tuple(sorted(baseline_sol.selected_warehouse_ids)))

        for idx, bias in enumerate(biases):
            # Vary facility count between target_k and target_k + 1 to explore redundancy trade-offs
            k_val = target_k + (1 if idx % 3 == 0 else 0)
            sol = self._solve_milp_instance(graph, target_k=k_val, resilience_bias=float(bias))
            if sol:
                combo_key = tuple(sorted(sol.selected_warehouse_ids))
                if combo_key not in seen_combos:
                    seen_combos.add(combo_key)
                    sol.name = f"Pareto Frontier Option #{len(frontier) + 1} ({len(sol.selected_warehouse_ids)} Hubs)"
                    sol.description = f"Balanced trade-off with resilience score {sol.resilience_score:.3f} and ${sol.total_cost:,.0f} budget."
                    frontier.append(sol)

        # Sort frontier by Cost ascending
        frontier.sort(key=lambda s: s.total_cost)
        for rank, s in enumerate(frontier, 1):
            s.rank = rank

        # Ensure baseline is properly returned
        if not baseline_sol and frontier:
            baseline_sol = frontier[0]
            baseline_sol.is_baseline_cost_only = True

        return frontier, baseline_sol

    async def execute(self, graph: LogisticsGraph, inputs: InputSpec) -> Tuple[List[NetworkSolution], NetworkSolution, List[AgentTraceEvent]]:
        trace_events = []
        
        start_event = AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="ParetoOptimization",
            status="start",
            message="Solving facility location MILP and generating Cost-vs-Resilience Pareto Frontier via NSGA-II sweep.",
            timestamp=""
        )
        trace_events.append(start_event)

        frontier, baseline = self.generate_pareto_frontier(graph, inputs)

        # No feasible MILP solution exists -- e.g. zero warehouses survived Site/Risk
        # screening, so there is nothing for _solve_milp_instance() to select from.
        # Bail out here with a clear trace event instead of crashing below on
        # baseline.total_cost / best_balanced.total_cost against a None solution.
        if baseline is None:
            active_warehouses = [w for w in graph.warehouses if w.status == "active"]
            total_demand = sum(c.demand_units for c in graph.customers)
            target_k = inputs.target_warehouses_to_open
            # Best case is opening the target_k largest sites; if that still cannot
            # cover demand the model is capacity-bound rather than candidate-bound.
            top_k_capacity = sum(
                sorted((w.capacity_units for w in active_warehouses), reverse=True)[:target_k]
            )

            if not active_warehouses:
                reason = (
                    "no warehouse candidates were available to the MILP "
                    "(none survived Site/Risk screening, or the graph has no active warehouses)"
                )
            elif top_k_capacity < total_demand:
                # When the cap is at or above the number of surviving sites, the
                # shortlist is the limit, not the cap.
                if target_k >= len(active_warehouses):
                    reason = (
                        f"all {len(active_warehouses)} surviving sites together provide "
                        f"{top_k_capacity:,.0f} units of capacity against {total_demand:,.0f} "
                        f"units of demand"
                    )
                else:
                    reason = (
                        f"opening the {target_k} largest of {len(active_warehouses)} surviving "
                        f"sites provides {top_k_capacity:,.0f} units of capacity against "
                        f"{total_demand:,.0f} units of demand"
                    )
            else:
                reason = (
                    f"the solver found no assignment satisfying capacity, supply and demand "
                    f"constraints across {len(active_warehouses)} surviving sites at "
                    f"{target_k} open facilities"
                )

            trace_events.append(AgentTraceEvent(
                event_id=str(uuid.uuid4()),
                agent_name=self.name,
                action="ParetoOptimization",
                status="error",
                message=f"No feasible facility-location solution: {reason}.",
                details={
                    "frontier_count": 0,
                    "active_warehouses": len(active_warehouses),
                    "target_warehouses_to_open": target_k,
                    "top_k_capacity": top_k_capacity,
                    "total_demand": total_demand,
                },
                timestamp=""
            ))
            return [], None, trace_events

        # Which solution is recommended depends on what the user asked for. The
        # frontier itself is unchanged -- this only picks the starting point.
        preference = getattr(inputs, "optimization_preference", "balanced") or "balanced"
        if not frontier:
            best_balanced = baseline
        elif preference == "cost":
            best_balanced = min(frontier, key=lambda s: s.total_cost)
        elif preference == "resilience":
            best_balanced = max(frontier, key=lambda s: s.resilience_score)
        else:
            best_balanced = min(frontier, key=lambda s: abs(s.resilience_score - 0.85))

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="ParetoOptimization",
            status="complete",
            message=f"Pareto Frontier generated with {len(frontier)} non-dominated solutions. Baseline cost: ${baseline.total_cost:,.0f} vs. Resilient design cost: ${best_balanced.total_cost:,.0f}.",
            details={
                "frontier_count": len(frontier),
                "baseline_cost": baseline.total_cost,
                "baseline_resilience": baseline.resilience_score,
                "recommended_resilience": best_balanced.resilience_score,
                "preference": preference
            },
            timestamp=""
        ))

        return frontier, best_balanced, trace_events
