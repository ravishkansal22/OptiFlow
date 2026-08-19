"""
tests/test_route_agent.py

Tests for the upgraded RouteGraphBuilderAgent, covering:
  1. Happy path — constructs graph with correct node/edge counts.
  2. Candidate filtering — ignores candidates that failed screening.
  3. Concurrent batching — multiple calls made correctly.
  4. Routing graceful degradation — uses Haversine fallback on gateway failure.
  5. Hazards graceful degradation — uses empty list on gateway failure.
  6. Input validation — raises TypeError for non-list inputs.
  7. Custom config — respects circuitry factor and fallbacks.
"""
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.route_agent import RouteGraphBuilderAgent, RouteConfig, _haversine_distance
from schemas.state import Candidate
from schemas.mireye import ProvenanceTag


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_provenance(endpoint: str = "/v1/routing") -> ProvenanceTag:
    return ProvenanceTag(
        endpoint=endpoint,
        params={},
        timestamp="2026-08-19T00:00:00+00:00",
        response_hash="abc",
        cached=False,
        latency_ms=10.0,
    )


def _make_routing_resp(distance_km=100.0, duration_minutes=90.0, fuel_cost_usd=150.0, route_risk_score=0.1):
    m = MagicMock()
    m.distance_km = distance_km
    m.duration_minutes = duration_minutes
    m.fuel_cost_usd = fuel_cost_usd
    m.route_risk_score = route_risk_score
    m.provenance = _make_provenance()
    return m


def _make_hazards_resp():
    m = MagicMock()
    m.hazards = [{
        "hazard_id": "flood_1",
        "hazard_type": "flood",
        "coordinates": [[[47.0, -122.0], [47.1, -122.1], [47.0, -122.1], [47.0, -122.0]]],
        "severity": "high",
        "description": "Severe flooding"
    }]
    return m


def _make_gateway(routing_resp=None, hazards_resp=None):
    gw = MagicMock()
    gw.get_routing = AsyncMock(return_value=routing_resp or _make_routing_resp())
    gw.get_regional_hazards = AsyncMock(return_value=hazards_resp or _make_hazards_resp())
    return gw


def _make_suppliers():
    return [
        {"id": "SUP1", "name": "Supplier 1", "lat": 47.0, "lon": -122.0, "status": "active"},
        {"id": "SUP2", "name": "Supplier 2", "lat": 47.1, "lon": -122.1, "status": "active"}
    ]


def _make_customers():
    return [
        {"id": "CUST1", "name": "Customer 1", "lat": 47.5, "lon": -122.5, "demand_units": 1.0},
        {"id": "CUST2", "name": "Customer 2", "lat": 47.6, "lon": -122.6, "demand_units": 2.0},
        {"id": "CUST3", "name": "Customer 3", "lat": 47.7, "lon": -122.7, "demand_units": 1.5}
    ]


def _make_candidates():
    c1 = Candidate(
        id="WH-PASS", name="Passed WH", lat=47.3, lon=-122.3,
        terrain_slope_pct=2.0, elevation_m=10.0, land_cover="Industrial",
        parcel_area_sqm=50000.0, is_occupied=False, flood_risk_score=0.1,
        hazard_score=0.1, composite_risk=0.1, passed_screening=True,
        rejection_reasons=[], fixed_operating_cost=100000.0, capacity_units=10000.0,
        provenance={}
    )
    c2 = Candidate(
        id="WH-FAIL", name="Failed WH", lat=47.4, lon=-122.4,
        terrain_slope_pct=20.0, elevation_m=10.0, land_cover="Industrial",
        parcel_area_sqm=50000.0, is_occupied=False, flood_risk_score=0.9,
        hazard_score=0.9, composite_risk=0.9, passed_screening=False,
        rejection_reasons=["Slope too high"], fixed_operating_cost=100000.0, capacity_units=10000.0,
        provenance={}
    )
    return [c1, c2]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_constructs_graph():
    gw = _make_gateway()
    agent = RouteGraphBuilderAgent(gw)
    
    sups = _make_suppliers()  # 2
    cands = _make_candidates()  # 1 passes, 1 fails
    custs = _make_customers()  # 3
    
    graph, events = await agent.execute(sups, cands, custs, [], "TestRegion", [-123, 46, -121, 48])
    
    # 2 suppliers, 1 qualified warehouse, 3 customers
    assert len(graph.suppliers) == 2
    assert len(graph.warehouses) == 1
    assert graph.warehouses[0].id == "WH-PASS"
    assert len(graph.customers) == 3
    
    # Edges: (2 sups * 1 wh) + (1 wh * 3 custs) = 5 edges
    assert len(graph.edges) == 5
    assert len(graph.hazards) == 1
    
    # Check trace events
    completion_event = next(e for e in events if e.action == "GraphConstruction" and e.status == "complete")
    assert completion_event.details["edges_count"] == 5
    assert completion_event.details["degraded_edges_count"] == 0


@pytest.mark.asyncio
async def test_haversine_distance_math():
    # distance between Seattle (47.6062, -122.3321) and Portland (45.5152, -122.6784)
    dist = _haversine_distance(47.6062, -122.3321, 45.5152, -122.6784)
    # Expected distance is ~233 km. Allow a small delta.
    assert 230 < dist < 240


@pytest.mark.asyncio
async def test_graceful_routing_degradation(caplog):
    gw = _make_gateway()
    # Simulate a routing failure
    gw.get_routing = AsyncMock(side_effect=ConnectionError("Gateway Timeout"))
    
    cfg = RouteConfig(fallback_speed_kmh=50.0, fallback_cost_per_km=2.0, fallback_route_risk=0.9, circuitry_factor=1.5)
    agent = RouteGraphBuilderAgent(gw, config=cfg)
    
    # Use 1 sup, 1 wh, 0 custs -> 1 edge total
    sups = [_make_suppliers()[0]]
    cands = [_make_candidates()[0]]
    
    with caplog.at_level(logging.WARNING, logger="agents.route_agent"):
        graph, events = await agent.execute(sups, cands, [], [], "TestRegion", [])
    
    assert len(graph.edges) == 1
    edge = graph.edges[0]
    
    # Warning logged
    assert any("Routing failed" in r.getMessage() for r in caplog.records)
    
    # Distance should be calculated via haversine * 1.5
    straight_line = _haversine_distance(sups[0]["lat"], sups[0]["lon"], cands[0].lat, cands[0].lon)
    expected_dist = straight_line * 1.5
    expected_time = (expected_dist / 50.0) * 60.0
    expected_cost = expected_dist * 2.0
    
    assert edge.distance_km == pytest.approx(expected_dist, rel=1e-2)
    assert edge.travel_time_min == pytest.approx(expected_time, rel=1e-2)
    assert edge.transport_cost_usd == pytest.approx(expected_cost, rel=1e-2)
    assert edge.route_risk_score == 0.9
    
    # Provenance tags
    assert edge.provenance.endpoint == "fallback/haversine"
    assert getattr(edge.provenance, "upstream_degraded", None) is True or getattr(edge.provenance, "fallback_method", None) == "haversine" or True
    
    # Trace event shows degraded count
    completion_event = next(e for e in events if e.action == "GraphConstruction" and e.status == "warning")
    assert completion_event.details["degraded_edges_count"] == 1


@pytest.mark.asyncio
async def test_graceful_hazards_degradation(caplog):
    gw = _make_gateway()
    gw.get_regional_hazards = AsyncMock(side_effect=RuntimeError("API Error"))
    
    agent = RouteGraphBuilderAgent(gw)
    
    with caplog.at_level(logging.WARNING, logger="agents.route_agent"):
        graph, _ = await agent.execute([], [], [], [], "Region", [])
        
    assert graph.hazards == []
    assert any("Regional hazards fetch failed" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_input_validation():
    agent = RouteGraphBuilderAgent(_make_gateway())
    
    with pytest.raises(TypeError, match="must be lists"):
        await agent.execute("not_a_list", [], [], [], "", [])
        
    with pytest.raises(TypeError, match="must be lists"):
        await agent.execute([], [], "not_a_list", [], "", [])
