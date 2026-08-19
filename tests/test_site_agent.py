"""
tests/test_site_agent.py

Tests for the upgraded SiteGenerationAgent, covering:
  1. Happy path — valid seeds, all candidates pass or fail as expected.
  2. Custom config — thresholds honoured at boundary values.
  3. Graceful Mireye degradation — gateway exceptions caught, site rejected
     with explanation rather than crashing.
  4. Input validation — bad lat/lon triggers warning, not crash.
  5. Reasoning / why — assert that trace events contain populated reasoning.
  6. Confidence scoring — check score reflects marginal proximity to threshold.
  7. Empty input — zero seeds, no candidates, no crash.
"""
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.site_agent import SiteGenerationAgent, SiteConfig
from schemas.state import NetworkState, InputSpec
from schemas.mireye import ProvenanceTag


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_state() -> NetworkState:
    return NetworkState(
        inputs=InputSpec(),
        mireye_cache={},
        candidates=[],
        graph=None,
        frontier=[],
        active_solution_id="",
        disruption_log=[],
        critic_flags=[],
        critic_report=None,
        narrative="",
        trace_events=[],
    )


def _make_provenance(endpoint: str = "/v1/test") -> ProvenanceTag:
    """Real ProvenanceTag so Pydantic validation passes on Candidate.provenance."""
    return ProvenanceTag(
        endpoint=endpoint,
        params={},
        timestamp="2026-08-19T00:00:00+00:00",
        response_hash="abc123",
        cached=False,
        latency_ms=5.0,
    )


def _make_terrain(slope_pct=2.0, elevation_m=30.0):
    """Build a minimal mock MireyeTerrainResponse with a real ProvenanceTag."""
    m = MagicMock()
    m.slope_pct = slope_pct
    m.elevation_m = elevation_m
    m.provenance = _make_provenance("/v1/geospatial/terrain-elevation")
    return m


def _make_land_cover(
    land_cover="Industrial",
    parcel_sqm=60_000.0,
    is_occupied=False,
):
    """Build a minimal mock MireyeLandCoverResponse with a real ProvenanceTag."""
    m = MagicMock()
    m.primary_land_cover = land_cover
    m.available_parcel_sqm = parcel_sqm
    m.is_occupied = is_occupied
    m.provenance = _make_provenance("/v1/geospatial/land-cover-parcels")
    return m


def _make_gateway(slope_pct=2.0, elevation_m=30.0, parcel_sqm=60_000.0,
                  land_cover="Industrial", is_occupied=False):
    gw = MagicMock()
    gw.get_terrain_elevation = AsyncMock(
        return_value=_make_terrain(slope_pct=slope_pct, elevation_m=elevation_m)
    )
    gw.get_land_cover_buildings = AsyncMock(
        return_value=_make_land_cover(
            land_cover=land_cover,
            parcel_sqm=parcel_sqm,
            is_occupied=is_occupied,
        )
    )
    return gw


VALID_SEED = {
    "id": "WH-A",
    "name": "Warehouse Alpha",
    "lat": 47.41,
    "lon": -122.24,
    "base_capacity": 20_000.0,
    "fixed_cost": 130_000.0,
}


# ---------------------------------------------------------------------------
# 1. Happy path — well-within-limits site should PASS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_site_passes():
    gw = _make_gateway(slope_pct=2.0, elevation_m=30.0, parcel_sqm=60_000.0)
    agent = SiteGenerationAgent(gw)

    candidates, events = await agent.execute(_make_state(), [VALID_SEED])

    assert len(candidates) == 1
    c = candidates[0]
    assert c.id == "WH-A"
    assert c.passed_screening is True
    assert c.rejection_reasons == []
    assert c.terrain_slope_pct == 2.0
    assert c.elevation_m == 30.0


@pytest.mark.asyncio
async def test_happy_path_provenance_attached():
    gw = _make_gateway()
    agent = SiteGenerationAgent(gw)
    candidates, _ = await agent.execute(_make_state(), [VALID_SEED])
    # Both terrain and land_cover provenance should be in the provenance map
    assert "terrain" in candidates[0].provenance
    assert "land_cover" in candidates[0].provenance


# ---------------------------------------------------------------------------
# 2. Rejection rules — each individual rule triggers correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slope_too_high_rejects():
    gw = _make_gateway(slope_pct=10.0)  # default max is 8.0
    agent = SiteGenerationAgent(gw)
    candidates, _ = await agent.execute(_make_state(), [VALID_SEED])
    c = candidates[0]
    assert c.passed_screening is False
    assert any("Slope" in r for r in c.rejection_reasons)


@pytest.mark.asyncio
async def test_elevation_too_high_rejects():
    gw = _make_gateway(elevation_m=300.0)  # default max is 250
    agent = SiteGenerationAgent(gw)
    candidates, _ = await agent.execute(_make_state(), [VALID_SEED])
    assert candidates[0].passed_screening is False
    assert any("Elevation" in r for r in candidates[0].rejection_reasons)


@pytest.mark.asyncio
async def test_occupied_parcel_rejects():
    gw = _make_gateway(is_occupied=True)
    agent = SiteGenerationAgent(gw)
    candidates, _ = await agent.execute(_make_state(), [VALID_SEED])
    assert candidates[0].passed_screening is False
    assert any("occupied" in r.lower() for r in candidates[0].rejection_reasons)


@pytest.mark.asyncio
async def test_small_parcel_rejects():
    gw = _make_gateway(parcel_sqm=5_000.0, is_occupied=False)  # below 25k min
    agent = SiteGenerationAgent(gw)
    candidates, _ = await agent.execute(_make_state(), [VALID_SEED])
    assert candidates[0].passed_screening is False
    assert any("parcel" in r.lower() for r in candidates[0].rejection_reasons)


# ---------------------------------------------------------------------------
# 3. Custom SiteConfig — thresholds are respected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_config_stricter_slope():
    """With a tighter slope limit, a site that passes default config should fail."""
    strict_cfg = SiteConfig(max_slope_pct=1.0)  # default site has slope=2.0
    gw = _make_gateway(slope_pct=2.0)
    agent = SiteGenerationAgent(gw, config=strict_cfg)
    candidates, _ = await agent.execute(_make_state(), [VALID_SEED])
    assert candidates[0].passed_screening is False
    assert any("Slope" in r for r in candidates[0].rejection_reasons)


@pytest.mark.asyncio
async def test_custom_config_looser_parcel():
    """With a smaller minimum parcel, a tight-parcel site should pass."""
    loose_cfg = SiteConfig(min_parcel_sqm=3_000.0)
    gw = _make_gateway(parcel_sqm=4_000.0, is_occupied=False)
    agent = SiteGenerationAgent(gw, config=loose_cfg)
    candidates, _ = await agent.execute(_make_state(), [VALID_SEED])
    assert candidates[0].passed_screening is True


# ---------------------------------------------------------------------------
# 4. Graceful Mireye degradation — exceptions caught, not re-raised
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_terrain_failure_degrades_gracefully(caplog):
    """If terrain fetch raises, site is rejected with explanation, not crashed."""
    gw = MagicMock()
    gw.get_terrain_elevation = AsyncMock(side_effect=ConnectionError("Redis down"))
    gw.get_land_cover_buildings = AsyncMock(
        return_value=_make_land_cover(parcel_sqm=60_000.0)
    )

    agent = SiteGenerationAgent(gw)
    with caplog.at_level(logging.WARNING, logger="agents.site_agent"):
        # Should NOT raise
        candidates, events = await agent.execute(_make_state(), [VALID_SEED])

    # Warning must be logged
    assert any("Terrain fetch failed" in r.getMessage() for r in caplog.records)

    # Site is still produced — marked as degraded (partial data)
    assert len(candidates) == 1
    # Confidence should be < 1.0 because of degradation penalty
    screening_event = next(
        e for e in events if e.action == "CandidateScreened"
    )
    assert screening_event.details["upstream_degraded"] is True
    assert screening_event.details["confidence_score"] < 1.0


@pytest.mark.asyncio
async def test_both_mireye_calls_fail_rejects_site():
    """If both terrain AND land-cover fail, site must be REJECTED, not silently passed."""
    gw = MagicMock()
    gw.get_terrain_elevation = AsyncMock(side_effect=RuntimeError("timeout"))
    gw.get_land_cover_buildings = AsyncMock(side_effect=RuntimeError("timeout"))

    agent = SiteGenerationAgent(gw)
    candidates, _ = await agent.execute(_make_state(), [VALID_SEED])

    c = candidates[0]
    assert c.passed_screening is False
    assert any("cannot be screened" in r for r in c.rejection_reasons)


# ---------------------------------------------------------------------------
# 5. Input validation — malformed seeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_latlon_uses_default_and_warns(caplog):
    """Seed without lat/lon logs a warning and substitutes the configured default."""
    gw = _make_gateway()
    agent = SiteGenerationAgent(gw)
    seed_no_coords = {"id": "WH-NOCOORD", "name": "No Coord Warehouse"}

    with caplog.at_level(logging.WARNING, logger="agents.site_agent"):
        candidates, _ = await agent.execute(_make_state(), [seed_no_coords])

    assert any("missing lat/lon" in r.getMessage() for r in caplog.records)
    c = candidates[0]
    # Defaults from SiteConfig should be used
    assert c.lat == SiteConfig().default_lat
    assert c.lon == SiteConfig().default_lon


@pytest.mark.asyncio
async def test_non_dict_seed_is_skipped_gracefully():
    """Non-dict entries in the seed list must be skipped, not crash."""
    gw = _make_gateway()
    agent = SiteGenerationAgent(gw)
    candidates, _ = await agent.execute(_make_state(), ["not_a_dict", None, 42])
    assert candidates == []


@pytest.mark.asyncio
async def test_non_list_seeds_raises_type_error():
    gw = _make_gateway()
    agent = SiteGenerationAgent(gw)
    with pytest.raises(TypeError, match="must be a list"):
        await agent.execute(_make_state(), "not_a_list")


# ---------------------------------------------------------------------------
# 6. The "why" — reasoning field is populated and meaningful
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoning_populated_on_pass():
    gw = _make_gateway(slope_pct=2.0, elevation_m=30.0, parcel_sqm=60_000.0)
    agent = SiteGenerationAgent(gw)
    _, events = await agent.execute(_make_state(), [VALID_SEED])

    screening_events = [e for e in events if e.action == "CandidateScreened"]
    assert len(screening_events) == 1
    reasoning = screening_events[0].details.get("reasoning", "")
    assert len(reasoning) > 50, "Reasoning string should be substantive, not empty."
    assert "ACCEPTED" in reasoning


@pytest.mark.asyncio
async def test_reasoning_populated_on_reject():
    gw = _make_gateway(slope_pct=12.0)
    agent = SiteGenerationAgent(gw)
    _, events = await agent.execute(_make_state(), [VALID_SEED])

    screening_events = [e for e in events if e.action == "CandidateScreened"]
    reasoning = screening_events[0].details["reasoning"]
    assert "REJECTED" in reasoning
    assert "12" in reasoning or "Slope" in reasoning


@pytest.mark.asyncio
async def test_reasoning_flags_upstream_degradation():
    """When Mireye fails, the reasoning text must mention MOCK / fallback data."""
    gw = MagicMock()
    gw.get_terrain_elevation = AsyncMock(side_effect=ConnectionError("down"))
    gw.get_land_cover_buildings = AsyncMock(
        return_value=_make_land_cover(parcel_sqm=60_000.0)
    )
    agent = SiteGenerationAgent(gw)
    _, events = await agent.execute(_make_state(), [VALID_SEED])

    screening_events = [e for e in events if e.action == "CandidateScreened"]
    reasoning = screening_events[0].details["reasoning"]
    assert "MOCK" in reasoning or "fallback" in reasoning.lower()


# ---------------------------------------------------------------------------
# 7. Confidence scoring — marginal values produce lower confidence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confidence_near_slope_limit_is_lower():
    """A site at 7.9% slope (just below 8% limit) should have lower confidence
    than one at 2% slope."""
    cfg = SiteConfig()

    gw_marginal = _make_gateway(slope_pct=7.9)
    agent_marginal = SiteGenerationAgent(gw_marginal, config=cfg)
    _, events_marginal = await agent_marginal.execute(_make_state(), [VALID_SEED])
    conf_marginal = next(
        e for e in events_marginal if e.action == "CandidateScreened"
    ).details["confidence_score"]

    gw_good = _make_gateway(slope_pct=2.0)
    agent_good = SiteGenerationAgent(gw_good, config=cfg)
    _, events_good = await agent_good.execute(_make_state(), [VALID_SEED])
    conf_good = next(
        e for e in events_good if e.action == "CandidateScreened"
    ).details["confidence_score"]

    assert conf_marginal < conf_good, (
        f"Marginal slope site (confidence={conf_marginal}) should score lower "
        f"than safe slope site (confidence={conf_good})."
    )


# ---------------------------------------------------------------------------
# 8. Edge case — empty seed list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_seed_list_returns_empty():
    gw = _make_gateway()
    agent = SiteGenerationAgent(gw)
    candidates, events = await agent.execute(_make_state(), [])
    assert candidates == []
    # Start and complete events still emitted
    actions = [e.action for e in events]
    assert "SiteSitingScreening" in actions


# ---------------------------------------------------------------------------
# 9. Trace event structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trace_events_contain_thresholds_used():
    """Thresholds used during screening should be recorded in the trace details."""
    cfg = SiteConfig(max_slope_pct=6.0, max_elevation_m=200.0, min_parcel_sqm=30_000.0)
    gw = _make_gateway()
    agent = SiteGenerationAgent(gw, config=cfg)
    _, events = await agent.execute(_make_state(), [VALID_SEED])

    screening_event = next(e for e in events if e.action == "CandidateScreened")
    thresholds = screening_event.details.get("thresholds_used", {})
    assert thresholds["max_slope_pct"] == 6.0
    assert thresholds["max_elevation_m"] == 200.0
    assert thresholds["min_parcel_sqm"] == 30_000.0
