import pytest
from schemas.state import (
    NetworkState,
    InputSpec,
    Candidate,
    SupplierNode,
    WarehouseNode,
    CustomerNode,
    LogisticsEdge,
    LogisticsGraph,
    NetworkSolution,
    Disruption
)
from schemas.mireye import ProvenanceTag


def test_provenance_tag_creation():
    tag = ProvenanceTag(
        endpoint="/v1/geospatial/terrain-elevation",
        params={"lat": 47.4124, "lon": -122.2415},
        timestamp="2026-08-18T18:00:00Z",
        response_hash="a1b2c3d4e5f6",
        cached=False,
        latency_ms=12.5
    )
    assert tag.endpoint == "/v1/geospatial/terrain-elevation"
    assert tag.response_hash == "a1b2c3d4e5f6"
    assert tag.latency_ms == 12.5


def test_candidate_serialization():
    cand = Candidate(
        id="cand_1",
        name="Kent Logistics Center",
        lat=47.38,
        lon=-122.23,
        terrain_slope_pct=1.2,
        elevation_m=15.0,
        land_cover="Industrial",
        parcel_area_sqm=55000.0,
        is_occupied=False,
        flood_risk_score=0.25,
        composite_risk=0.30,
        passed_screening=True,
        fixed_operating_cost=120000.0,
        capacity_units=20000.0
    )
    dumped = cand.model_dump()
    assert dumped["id"] == "cand_1"
    assert dumped["passed_screening"] is True
    assert dumped["capacity_units"] == 20000.0


def test_network_solution_resilience_formula():
    demand_retained = 95.0
    norm_recov_cost = 0.15
    # Resilience = 0.6 * (demand_retained/100) + 0.4 * (1 - norm_recovery_cost)
    expected_resilience = round(0.6 * (95.0 / 100.0) + 0.4 * (1.0 - 0.15), 3)

    sol = NetworkSolution(
        solution_id="sol_test",
        name="Test Resilient Plan",
        selected_warehouse_ids=["cand_1", "cand_2"],
        total_fixed_cost=250000.0,
        total_transport_cost=180000.0,
        total_cost=430000.0,
        demand_retained_pct=demand_retained,
        normalized_recovery_cost=norm_recov_cost,
        resilience_score=expected_resilience,
        is_baseline_cost_only=False
    )
    assert sol.resilience_score == 0.91
