"""
tests/test_disaster_agent.py

Tests for the upgraded DisasterSimulationAgent, covering:
  1. Flood scenario — warehouse spatially inside a real Mireye hazard
     polygon is matched (point-in-polygon), warehouse outside is not.
  2. Flood scenario falls back to flood_risk_score threshold when Mireye
     returns no hazards, or when returned hazards don't intersect anything.
  3. Flood fallback picks the single highest-risk warehouse when none
     exceed the configured threshold.
  4. Flood scenario degrades gracefully on gateway failure — fallback
     signals used, upstream_degraded=True, MIREYE_MOCK_MODE noted, no crash.
  5. Road closure scenario — edges near a real Mireye closure point matched;
     edge_limit respected.
  6. Road closure scenario degrades to the original name-matching heuristic
     when the gateway fails, or when no active closures are returned.
  7. Demand surge scenario — multiplier applied, no facilities/edges touched.
  8. Unknown scenario type defaults to single warehouse failure.
  9. DisasterConfig validation (bounding_box, road_closure_radius_km).
 10. Trace events — start/complete present, status reflects degradation.
 11. _point_in_polygon unit-level checks.
 12. known_hazards_raw is forwarded to the gateway call.
"""
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.disaster_agent import DisasterSimulationAgent, DisasterConfig, _point_in_polygon


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_warehouse(id: str, name: str, lat: float, lon: float, flood_risk_score: float = 0.1):
    return SimpleNamespace(id=id, name=name, lat=lat, lon=lon, flood_risk_score=flood_risk_score, capacity_units=1000)


def _make_edge(id: str, source_id: str, target_id: str):
    return SimpleNamespace(id=id, source_id=source_id, target_id=target_id)


def _make_graph(warehouses=None, customers=None, edges=None, suppliers=None):
    return SimpleNamespace(
        warehouses=warehouses or [],
        customers=customers or [],
        edges=edges or [],
        suppliers=suppliers or [],
    )


def _make_hazard_polygon(hazard_type: str = "floodzone", coordinates=None, description: str = "Test flood zone"):
    return SimpleNamespace(hazard_type=hazard_type, coordinates=coordinates or [], description=description)


def _make_hazard_response(hazards=None, active_road_closures=None, provenance=None):
    return SimpleNamespace(
        hazards=hazards or [],
        active_road_closures=active_road_closures or [],
        provenance=provenance,
    )


def _make_gateway(hazard_resp=None, side_effect=None):
    gw = MagicMock()
    if side_effect is not None:
        gw.get_regional_hazards = AsyncMock(side_effect=side_effect)
    else:
        gw.get_regional_hazards = AsyncMock(return_value=hazard_resp or _make_hazard_response())
    return gw


_SQUARE_POLYGON = [[-122.4, 47.3], [-122.2, 47.3], [-122.2, 47.5], [-122.4, 47.5], [-122.4, 47.3]]


# ---------------------------------------------------------------------------
# 1. Flood scenario — real polygon matching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flood_scenario_matches_warehouse_inside_hazard_polygon():
    hazard = _make_hazard_polygon(coordinates=_SQUARE_POLYGON, description="Green River 100-yr flood zone")
    wh_in = _make_warehouse("wh-in", "Inside WH", lat=47.4, lon=-122.3)
    wh_out = _make_warehouse("wh-out", "Outside WH", lat=48.0, lon=-120.0)
    edge_in = _make_edge("e1", "wh-in", "cust-1")
    edge_out = _make_edge("e2", "wh-out", "cust-2")
    graph = _make_graph(warehouses=[wh_in, wh_out], edges=[edge_in, edge_out])

    gw = _make_gateway(_make_hazard_response(hazards=[hazard]))
    agent = DisasterSimulationAgent(gw)
    disruption, _ = await agent.generate_scenario("flood_green_river", graph)

    assert disruption.affected_warehouse_ids == ["wh-in"]
    assert "e1" in disruption.affected_edge_ids
    assert "e2" not in disruption.affected_edge_ids
    assert "Green River 100-yr flood zone" in disruption.description


# ---------------------------------------------------------------------------
# 2. Flood scenario fallback (no hazards / no intersection)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flood_scenario_falls_back_when_no_hazards_returned():
    cfg = DisasterConfig(flood_risk_fallback_threshold=0.4)
    wh_high = _make_warehouse("wh-high", "High Risk WH", lat=47.4, lon=-122.3, flood_risk_score=0.6)
    wh_low = _make_warehouse("wh-low", "Low Risk WH", lat=47.5, lon=-122.1, flood_risk_score=0.1)
    graph = _make_graph(warehouses=[wh_high, wh_low])

    gw = _make_gateway(_make_hazard_response(hazards=[]))
    agent = DisasterSimulationAgent(gw, config=cfg)
    disruption, _ = await agent.generate_scenario("flood_green_river", graph)

    assert disruption.affected_warehouse_ids == ["wh-high"]


@pytest.mark.asyncio
async def test_flood_scenario_falls_back_when_hazard_polygon_does_not_intersect():
    far_away_polygon = [[10.0, 10.0], [10.0, 11.0], [11.0, 11.0], [11.0, 10.0], [10.0, 10.0]]
    hazard = _make_hazard_polygon(coordinates=far_away_polygon)
    wh_high = _make_warehouse("wh-high", "High Risk WH", lat=47.4, lon=-122.3, flood_risk_score=0.6)
    graph = _make_graph(warehouses=[wh_high])

    gw = _make_gateway(_make_hazard_response(hazards=[hazard]))
    agent = DisasterSimulationAgent(gw, config=DisasterConfig(flood_risk_fallback_threshold=0.4))
    disruption, _ = await agent.generate_scenario("flood_green_river", graph)

    assert disruption.affected_warehouse_ids == ["wh-high"]


# ---------------------------------------------------------------------------
# 3. Flood fallback picks max-risk warehouse when none exceed threshold
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flood_fallback_picks_max_risk_when_none_exceed_threshold():
    cfg = DisasterConfig(flood_risk_fallback_threshold=0.9)
    wh_a = _make_warehouse("wh-a", "A", lat=47.4, lon=-122.3, flood_risk_score=0.3)
    wh_b = _make_warehouse("wh-b", "B", lat=47.5, lon=-122.1, flood_risk_score=0.5)
    graph = _make_graph(warehouses=[wh_a, wh_b])

    gw = _make_gateway(_make_hazard_response(hazards=[]))
    agent = DisasterSimulationAgent(gw, config=cfg)
    disruption, _ = await agent.generate_scenario("flood_green_river", graph)

    assert disruption.affected_warehouse_ids == ["wh-b"]


# ---------------------------------------------------------------------------
# 4. Graceful degradation on gateway failure — flood scenario
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flood_scenario_degrades_gracefully_on_gateway_failure(caplog):
    cfg = DisasterConfig(flood_risk_fallback_threshold=0.4)
    wh_high = _make_warehouse("wh-high", "High Risk WH", lat=47.4, lon=-122.3, flood_risk_score=0.6)
    graph = _make_graph(warehouses=[wh_high])

    gw = _make_gateway(side_effect=ConnectionError("Mireye down"))
    agent = DisasterSimulationAgent(gw, config=cfg)
    with caplog.at_level(logging.WARNING, logger="agents.disaster_agent"):
        disruption, events = await agent.generate_scenario("flood_green_river", graph)

    assert disruption.affected_warehouse_ids == ["wh-high"]
    assert "MIREYE_MOCK_MODE" in disruption.description
    assert disruption.provenance is None

    complete_event = events[-1]
    assert complete_event.details["upstream_degraded"] is True
    assert complete_event.status == "warning"
    assert any("Regional hazard fetch failed" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 5. Road closure scenario — real closure-point matching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_road_closure_scenario_matches_edges_near_closure_point():
    cfg = DisasterConfig(road_closure_radius_km=8.0)
    closure = {"road_name": "I-5 Southbound", "lat": 47.45, "lon": -122.25}
    wh_near = _make_warehouse("wh-near", "Near WH", lat=47.45, lon=-122.25)
    wh_far = _make_warehouse("wh-far", "Far WH", lat=48.5, lon=-120.0)
    edge_near = _make_edge("e-near", "wh-near", "cust-x")
    edge_far = _make_edge("e-far", "wh-far", "cust-y")
    graph = _make_graph(warehouses=[wh_near, wh_far], edges=[edge_near, edge_far])

    gw = _make_gateway(_make_hazard_response(active_road_closures=[closure]))
    agent = DisasterSimulationAgent(gw, config=cfg)
    disruption, _ = await agent.generate_scenario("road_closure_corridor", graph)

    assert "e-near" in disruption.affected_edge_ids
    assert "e-far" not in disruption.affected_edge_ids
    assert disruption.title == "I-5 Southbound"


@pytest.mark.asyncio
async def test_road_closure_scenario_respects_edge_limit():
    cfg = DisasterConfig(road_closure_radius_km=100.0, road_closure_edge_limit=2)
    closure = {"road_name": "Big Closure", "lat": 47.4, "lon": -122.3}
    warehouses = [_make_warehouse(f"wh-{i}", f"WH {i}", lat=47.4, lon=-122.3) for i in range(5)]
    edges = [_make_edge(f"e{i}", f"wh-{i}", "cust-x") for i in range(5)]
    graph = _make_graph(warehouses=warehouses, edges=edges)

    gw = _make_gateway(_make_hazard_response(active_road_closures=[closure]))
    agent = DisasterSimulationAgent(gw, config=cfg)
    disruption, _ = await agent.generate_scenario("road_closure_corridor", graph)

    assert len(disruption.affected_edge_ids) == 2


# ---------------------------------------------------------------------------
# 6. Road closure scenario — degraded fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_road_closure_scenario_degrades_to_name_heuristic_on_failure():
    edge_tukwila = _make_edge("e-tuk", "tukwila_wh", "cust-1")
    edge_other = _make_edge("e-other", "kent_wh", "cust-2")
    graph = _make_graph(edges=[edge_tukwila, edge_other])

    gw = _make_gateway(side_effect=RuntimeError("timeout"))
    agent = DisasterSimulationAgent(gw)
    disruption, events = await agent.generate_scenario("road_closure_corridor", graph)

    assert disruption.affected_edge_ids == ["e-tuk"]
    assert disruption.title == "I-5 / I-405 Southcenter Interchange Collapse"
    assert "MIREYE_MOCK_MODE" in disruption.description
    assert disruption.provenance is None

    complete_event = events[-1]
    assert complete_event.details["upstream_degraded"] is True
    assert complete_event.status == "warning"


@pytest.mark.asyncio
async def test_road_closure_falls_back_without_note_when_gateway_ok_but_no_closures():
    edge_tukwila = _make_edge("e-tuk", "tukwila_wh", "cust-1")
    graph = _make_graph(edges=[edge_tukwila])

    gw = _make_gateway(_make_hazard_response(active_road_closures=[]))
    agent = DisasterSimulationAgent(gw)
    disruption, events = await agent.generate_scenario("road_closure_corridor", graph)

    assert disruption.affected_edge_ids == ["e-tuk"]
    assert "MIREYE_MOCK_MODE" not in disruption.description

    complete_event = events[-1]
    assert complete_event.status == "complete"
    assert complete_event.details["upstream_degraded"] is False


# ---------------------------------------------------------------------------
# 7. Demand surge scenario
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_surge_demand_scenario():
    cfg = DisasterConfig(surge_demand_multiplier=1.5)
    gw = _make_gateway()
    agent = DisasterSimulationAgent(gw, config=cfg)
    disruption, _ = await agent.generate_scenario("surge_demand", _make_graph())

    assert disruption.disruption_type == "demand_surge"
    assert disruption.demand_multiplier == 1.5
    assert "+50%" in disruption.description
    assert disruption.affected_warehouse_ids == []
    assert disruption.affected_edge_ids == []


# ---------------------------------------------------------------------------
# 8. Unknown scenario type → warehouse failure default
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_scenario_defaults_to_warehouse_failure():
    wh = _make_warehouse("wh-1", "Primary WH", lat=47.4, lon=-122.3)
    edge = _make_edge("e1", "wh-1", "cust-1")
    graph = _make_graph(warehouses=[wh], edges=[edge])
    gw = _make_gateway()
    agent = DisasterSimulationAgent(gw)
    disruption, _ = await agent.generate_scenario("some_unrecognized_type", graph)

    assert disruption.disruption_type == "warehouse_failure"
    assert disruption.affected_warehouse_ids == ["wh-1"]
    assert "e1" in disruption.affected_edge_ids


@pytest.mark.asyncio
async def test_unknown_scenario_with_no_warehouses_uses_default_target():
    gw = _make_gateway()
    agent = DisasterSimulationAgent(gw)
    disruption, _ = await agent.generate_scenario("some_unrecognized_type", _make_graph())

    assert disruption.affected_warehouse_ids == ["cand_kent_south"]


# ---------------------------------------------------------------------------
# 9. DisasterConfig validation
# ---------------------------------------------------------------------------

def test_disaster_config_bad_bounding_box_raises():
    with pytest.raises(ValueError, match="bounding_box"):
        DisasterConfig(bounding_box=[1.0, 2.0, 3.0]).validate()


def test_disaster_config_bad_radius_raises():
    with pytest.raises(ValueError, match="road_closure_radius_km"):
        DisasterConfig(road_closure_radius_km=0).validate()


def test_disaster_config_good_values_ok():
    DisasterConfig(road_closure_radius_km=5.0).validate()  # should not raise


def test_disaster_agent_rejects_invalid_config_at_construction():
    with pytest.raises(ValueError):
        DisasterSimulationAgent(_make_gateway(), config=DisasterConfig(road_closure_radius_km=-1))


# ---------------------------------------------------------------------------
# 10. Trace events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trace_events_start_and_complete_present():
    gw = _make_gateway()
    agent = DisasterSimulationAgent(gw)
    _, events = await agent.generate_scenario("surge_demand", _make_graph())

    actions = [e.action for e in events]
    assert actions.count("SimulateDisaster") == 2
    assert events[0].status == "start"
    assert events[-1].status in ("complete", "warning")


# ---------------------------------------------------------------------------
# 11. _point_in_polygon unit checks
# ---------------------------------------------------------------------------

def test_point_in_polygon_true_for_interior_point():
    assert _point_in_polygon(47.4, -122.3, _SQUARE_POLYGON) is True


def test_point_in_polygon_false_for_exterior_point():
    assert _point_in_polygon(48.0, -120.0, _SQUARE_POLYGON) is False


def test_point_in_polygon_degenerate_polygon_returns_false():
    assert _point_in_polygon(47.4, -122.3, [[-122.4, 47.3], [-122.2, 47.3]]) is False


def test_point_in_polygon_empty_coordinates_returns_false():
    assert _point_in_polygon(47.4, -122.3, []) is False


# ---------------------------------------------------------------------------
# 12. known_hazards_raw forwarded to gateway
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_known_hazards_raw_forwarded_to_gateway():
    gw = _make_gateway()
    agent = DisasterSimulationAgent(gw)
    seeds = [{"type": "flood", "lat": 47.4, "lon": -122.3}]
    await agent.generate_scenario("flood_green_river", _make_graph(), known_hazards_raw=seeds)

    gw.get_regional_hazards.assert_awaited_once()
    _, kwargs = gw.get_regional_hazards.call_args
    assert kwargs["known_hazards"] == seeds