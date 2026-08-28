"""
Shared measurement helpers.

One function, `evaluate_network`, measures how a solution performs against a
concrete graph state. The Disaster and Recovery agents both report through it,
so a "before" and an "after" figure are always produced the same way and stay
comparable. Nothing here estimates: every number is read off the graph, the
solution's own assignments and the edges the Route agent built.
"""

from typing import Dict, List, Optional, Tuple

from schemas.state import (
    LogisticsGraph,
    MetricSnapshot,
    NetworkSolution,
)


def _lane_index(graph: LogisticsGraph) -> Dict[Tuple[str, str], object]:
    return {(e.source_id, e.target_id): e for e in graph.edges}


def evaluate_network(
    graph: LogisticsGraph,
    solution: NetworkSolution,
    demand_multiplier: float = 1.0,
    assignments: Optional[Dict[str, str]] = None,
) -> MetricSnapshot:
    """
    Measures a solution against the graph exactly as it stands.

    A customer counts as served only when its assigned warehouse is still active
    and the lane to it is still open. Demand above a warehouse's capacity is not
    served either, which is what a demand surge actually does to the network.
    """
    lanes = _lane_index(graph)
    wh_by_id = {w.id: w for w in graph.warehouses}
    assign = assignments if assignments is not None else solution.customer_assignments

    served_units = 0.0
    on_time_units = 0.0
    total_units = 0.0
    transport_cost = 0.0
    weighted_minutes = 0.0
    customers_served = 0
    customers_partial = 0
    customers_unserved = 0
    disrupted_lanes = 0

    # Capacity is shared, so demand has to be accumulated per warehouse before
    # anything can be called served.
    per_wh: Dict[str, List[tuple]] = {}

    for cust in graph.customers:
        demand = cust.demand_units * demand_multiplier
        total_units += demand
        wh_id = assign.get(cust.id)
        wh = wh_by_id.get(wh_id) if wh_id else None
        lane = lanes.get((wh_id, cust.id)) if wh_id else None

        if wh is None or wh.status != "active":
            customers_unserved += 1
            continue
        if lane is not None and lane.status != "active":
            disrupted_lanes += 1
            customers_unserved += 1
            continue

        per_wh.setdefault(wh.id, []).append((cust, demand, lane))

    for wh_id, rows in per_wh.items():
        wh = wh_by_id[wh_id]
        requested = sum(r[1] for r in rows)
        # Above capacity, every customer on this hub loses the same share of its
        # order rather than an arbitrary few losing everything.
        ratio = 1.0 if requested <= wh.capacity_units else (wh.capacity_units / requested if requested else 0.0)

        for cust, demand, lane in rows:
            fulfilled = demand * ratio
            served_units += fulfilled
            if ratio >= 1.0:
                customers_served += 1
            elif fulfilled > 0:
                customers_partial += 1
            else:
                customers_unserved += 1
            minutes = lane.travel_time_min if lane else 0.0
            cost = lane.transport_cost_usd if lane else 0.0
            transport_cost += cost * ratio
            weighted_minutes += minutes * fulfilled
            if minutes <= cust.service_sla_minutes:
                on_time_units += fulfilled

    # Supplier -> warehouse legs the active plan already pays for.
    open_ids = set(solution.selected_warehouse_ids)
    flow_cost = sum(f.cost_usd for f in solution.flows if f.target_id in open_ids)
    transport_cost += flow_cost

    active_open = [w for w in graph.warehouses if w.id in open_ids and w.status == "active"]
    fixed_cost = sum(w.fixed_operating_cost for w in active_open)

    return MetricSnapshot(
        demand_total_units=round(total_units, 1),
        demand_served_units=round(served_units, 1),
        demand_served_pct=round((served_units / total_units) * 100.0, 1) if total_units else 0.0,
        on_time_pct=round((on_time_units / total_units) * 100.0, 1) if total_units else 0.0,
        avg_delivery_minutes=round(weighted_minutes / served_units, 1) if served_units else 0.0,
        transport_cost_usd=round(transport_cost, 2),
        fixed_cost_usd=round(fixed_cost, 2),
        total_cost_usd=round(transport_cost + fixed_cost, 2),
        customers_served=customers_served,
        customers_partial=customers_partial,
        customers_unserved=customers_unserved,
        active_warehouses=len(active_open),
        disrupted_lanes=disrupted_lanes,
    )
