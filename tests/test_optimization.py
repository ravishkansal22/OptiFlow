import pytest
from schemas.state import (
    LogisticsGraph,
    SupplierNode,
    WarehouseNode,
    CustomerNode,
    LogisticsEdge,
    InputSpec
)
from agents.optimization_agent import OptimizationAgent


def create_mini_logistics_graph() -> LogisticsGraph:
    suppliers = [
        SupplierNode(id="sup_1", name="Supplier Port", lat=47.27, lon=-122.41, capacity_units=50000, unit_supply_cost=8.0),
    ]
    warehouses = [
        WarehouseNode(id="wh_1", candidate_id="wh_1", name="Kent Valley Hub", lat=47.41, lon=-122.24, capacity_units=25000, fixed_operating_cost=120000, flood_risk_score=0.1),
        WarehouseNode(id="wh_2", candidate_id="wh_2", name="Auburn Hub", lat=47.30, lon=-122.22, capacity_units=30000, fixed_operating_cost=130000, flood_risk_score=0.05),
        WarehouseNode(id="wh_3", candidate_id="wh_3", name="Highland Hub", lat=47.57, lon=-122.16, capacity_units=20000, fixed_operating_cost=180000, flood_risk_score=0.01),
    ]
    customers = [
        CustomerNode(id="cust_1", name="Downtown Zone", lat=47.61, lon=-122.34, demand_units=5000, service_sla_minutes=45),
        CustomerNode(id="cust_2", name="Bellevue Tech", lat=47.61, lon=-122.19, demand_units=4000, service_sla_minutes=45),
        CustomerNode(id="cust_3", name="Tacoma Core", lat=47.25, lon=-122.44, demand_units=3500, service_sla_minutes=50),
    ]
    edges = []
    for sup in suppliers:
        for wh in warehouses:
            edges.append(LogisticsEdge(
                id=f"{sup.id}_{wh.id}",
                source_id=sup.id,
                target_id=wh.id,
                distance_km=25.0,
                travel_time_min=30.0,
                transport_cost_usd=120.0
            ))
    for wh in warehouses:
        for cust in customers:
            edges.append(LogisticsEdge(
                id=f"{wh.id}_{cust.id}",
                source_id=wh.id,
                target_id=cust.id,
                distance_km=20.0,
                travel_time_min=25.0,
                transport_cost_usd=150.0
            ))

    return LogisticsGraph(
        suppliers=suppliers,
        warehouses=warehouses,
        customers=customers,
        edges=edges
    )


def test_milp_baseline_and_pareto_frontier():
    graph = create_mini_logistics_graph()
    inputs = InputSpec(target_warehouses_to_open=2)
    optimizer = OptimizationAgent()

    frontier, baseline = optimizer.generate_pareto_frontier(graph, inputs)
    assert len(frontier) >= 1
    assert baseline is not None
    assert baseline.is_baseline_cost_only is True
    assert len(baseline.selected_warehouse_ids) <= 2
    assert baseline.total_cost > 0
    assert 0.0 <= baseline.resilience_score <= 1.0

    # Ensure each customer is assigned
    for cust in graph.customers:
        assert cust.id in baseline.customer_assignments
