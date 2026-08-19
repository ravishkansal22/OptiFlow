"""
tests/test_risk_agent.py

Tests for the upgraded RiskAgent, covering:
  1. Happy path — low-risk site passes, high-risk site is rejected.
  2. Pre-rejected candidates are forwarded unchanged (no Mireye calls made).
  3. Custom RiskConfig — weights and threshold are honoured.
  4. Graceful Mireye degradation — gateway exception → conservative score,
     upstream_degraded=True, pipeline does NOT crash.
  5. Input validation — non-list candidates, non-dict seeds_map.
  6. RiskConfig weight validation — non-unit-sum raises ValueError.
  7. The "why" — reasoning field populated; risk_breakdown present.
  8. Confidence scoring — marginal composite scores get lower confidence.
  9. Immutability — original Candidate objects are not mutated.
 10. Annual flood probability is factored into composite (not decorative).
"""
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.risk_agent import RiskAgent, RiskConfig, _composite_score
from schemas.state import Candidate
from schemas.mireye import ProvenanceTag


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_provenance(endpoint: str = "/v1/hazard/flood-risk") -> ProvenanceTag:
    return ProvenanceTag(
        endpoint=endpoint,
        params={},
        timestamp="2026-08-19T00:00:00+00:00",
        response_hash="deadbeef",
        cached=False,
        latency_ms=8.0,
    )


def _make_flood_resp(
    flood_zone: str = "Zone X (Minimal Flood Hazard)",
    flood_risk_index: float = 0.05,
    annual_flood_probability: float = 0.001,
    historical_flood_events: int = 0,
):
    m = MagicMock()
    m.flood_zone = flood_zone
    m.flood_risk_index = flood_risk_index
    m.annual_flood_probability = annual_flood_probability
    m.historical_flood_events = historical_flood_events
    m.provenance = _make_provenance()
    return m


def _make_gateway(flood_resp=None):
    gw = MagicMock()
    gw.get_flood_hazard = AsyncMock(return_value=flood_resp or _make_flood_resp())
    return gw


def _make_candidate(
    id: str = "WH-A",
    name: str = "Warehouse Alpha",
    passed_screening: bool = True,
    slope_pct: float = 2.0,
    rejection_reasons: list = None,
) -> Candidate:
    prov = _make_provenance("/v1/geospatial/terrain-elevation")
    return Candidate(
        id=id,
        name=name,
        lat=47.41,
        lon=-122.24,
        terrain_slope_pct=slope_pct,
        elevation_m=30.0,
        land_cover="Industrial",
        parcel_area_sqm=60_000.0,
        is_occupied=False,
        flood_risk_score=0.0,
        hazard_score=0.0,
        composite_risk=0.0,
        passed_screening=passed_screening,
        rejection_reasons=rejection_reasons or [],
        fixed_operating_cost=130_000.0,
        capacity_units=20_000.0,
        provenance={"terrain": prov},
    )


# ---------------------------------------------------------------------------
# 1. Happy path — low-risk site passes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_low_risk_site_passes():
    gw = _make_gateway(_make_flood_resp(flood_risk_index=0.05, historical_flood_events=0))
    agent = RiskAgent(gw)
    cands, events = await agent.execute([_make_candidate()], {})

    assert len(cands) == 1
    c = cands[0]
    assert c.passed_screening is True
    assert c.flood_risk_score == pytest.approx(0.05)
    assert c.composite_risk < 0.75
    assert c.rejection_reasons == []


@pytest.mark.asyncio
async def test_high_risk_site_rejected():
    """Zone AE high-flood site with extreme risk inputs should be rejected."""
    flood = _make_flood_resp(
        flood_zone="Zone AE (100-Year Base Flood)",
        flood_risk_index=0.95,
        annual_flood_probability=0.025,
        historical_flood_events=5,
    )
    gw = _make_gateway(flood)
    agent = RiskAgent(gw)
    cands, _ = await agent.execute([_make_candidate(slope_pct=7.0)], {})

    c = cands[0]
    assert c.passed_screening is False
    assert c.composite_risk > 0.75
    assert any("flood hazard" in r.lower() for r in c.rejection_reasons)


# ---------------------------------------------------------------------------
# 2. Pre-rejected candidates pass through — no Mireye calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pre_rejected_candidate_forwarded_unchanged():
    gw = _make_gateway()
    agent = RiskAgent(gw)
    pre_rejected = _make_candidate(passed_screening=False, rejection_reasons=["Occupied parcel"])

    cands, _ = await agent.execute([pre_rejected], {})

    # Mireye should NOT have been called for a pre-rejected site
    gw.get_flood_hazard.assert_not_called()
    assert cands[0].passed_screening is False
    assert cands[0].rejection_reasons == ["Occupied parcel"]
    # Risk scores must remain at their initial zeroed values
    assert cands[0].flood_risk_score == 0.0
    assert cands[0].composite_risk == 0.0


# ---------------------------------------------------------------------------
# 3. Custom RiskConfig — threshold and weights honoured
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stricter_threshold_rejects_medium_risk_site():
    """A site with composite ~0.40 passes default (0.75) but fails strict (0.35) config."""
    flood = _make_flood_resp(flood_risk_index=0.50, historical_flood_events=2)
    gw = _make_gateway(flood)

    strict_cfg = RiskConfig(
        composite_risk_rejection_threshold=0.35,
        flood_weight=0.55,
        hist_events_weight=0.20,
        slope_weight=0.15,
        annual_prob_weight=0.10,
    )
    agent = RiskAgent(gw, config=strict_cfg)
    cands, _ = await agent.execute([_make_candidate()], {})
    assert cands[0].passed_screening is False


@pytest.mark.asyncio
async def test_looser_threshold_passes_moderate_risk():
    """A site with composite ~0.55 passes when threshold is set to 0.80."""
    flood = _make_flood_resp(
        flood_zone="Zone X500 (500-Year Moderate Flood)",
        flood_risk_index=0.35,
        historical_flood_events=1,
        annual_flood_probability=0.005,
    )
    gw = _make_gateway(flood)
    loose_cfg = RiskConfig(
        composite_risk_rejection_threshold=0.80,
        flood_weight=0.55,
        hist_events_weight=0.20,
        slope_weight=0.15,
        annual_prob_weight=0.10,
    )
    agent = RiskAgent(gw, config=loose_cfg)
    cands, _ = await agent.execute([_make_candidate()], {})
    assert cands[0].passed_screening is True


# ---------------------------------------------------------------------------
# 4. Graceful Mireye degradation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flood_fetch_failure_degrades_gracefully(caplog):
    """Gateway exception → conservative fallback score, upstream_degraded=True,
    no pipeline crash."""
    gw = MagicMock()
    gw.get_flood_hazard = AsyncMock(side_effect=ConnectionError("Redis timeout"))

    agent = RiskAgent(gw)
    with caplog.at_level(logging.WARNING, logger="agents.risk_agent"):
        cands, events = await agent.execute([_make_candidate()], {})

    # Warning must be logged
    assert any("Flood hazard fetch failed" in r.getMessage() for r in caplog.records)

    # Candidate still produced, not crashed
    assert len(cands) == 1

    # upstream_degraded flag in trace
    risk_event = next(e for e in events if e.action == "CandidateRiskEvaluated")
    assert risk_event.details["upstream_degraded"] is True
    assert risk_event.details["confidence_score"] < 1.0


@pytest.mark.asyncio
async def test_flood_fetch_failure_uses_conservative_score():
    """Conservative fallback composite should equal upstream_failure_composite_risk
    when both factors are also at their fallback values."""
    cfg = RiskConfig(
        upstream_failure_flood_score=0.50,
        flood_weight=0.55,
        hist_events_weight=0.20,
        slope_weight=0.15,
        annual_prob_weight=0.10,
    )
    gw = MagicMock()
    gw.get_flood_hazard = AsyncMock(side_effect=RuntimeError("timeout"))
    agent = RiskAgent(gw, config=cfg)

    cands, _ = await agent.execute([_make_candidate(slope_pct=0.0)], {})
    c = cands[0]
    # With slope=0, historical=0, annual_prob=0, only flood contributes:
    # composite = 0.55 * 0.50 = 0.275 → well below threshold → should PASS
    assert c.composite_risk == pytest.approx(0.55 * 0.50, abs=1e-3)
    assert c.passed_screening is True  # conservative but not auto-reject


# ---------------------------------------------------------------------------
# 5. Input validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_list_candidates_raises():
    agent = RiskAgent(_make_gateway())
    with pytest.raises(TypeError, match="candidates must be a list"):
        await agent.execute("not_a_list", {})


@pytest.mark.asyncio
async def test_non_dict_seeds_map_raises():
    agent = RiskAgent(_make_gateway())
    with pytest.raises(TypeError, match="raw_seeds_map must be a dict"):
        await agent.execute([], "not_a_dict")


# ---------------------------------------------------------------------------
# 6. RiskConfig weight validation
# ---------------------------------------------------------------------------

def test_risk_config_bad_weights_raises():
    bad_cfg = RiskConfig(
        flood_weight=0.50,
        hist_events_weight=0.30,
        slope_weight=0.30,
        annual_prob_weight=0.10,
    )
    with pytest.raises(ValueError, match="must sum to 1.0"):
        bad_cfg.validate()


def test_risk_config_good_weights_ok():
    cfg = RiskConfig(
        flood_weight=0.55,
        hist_events_weight=0.20,
        slope_weight=0.15,
        annual_prob_weight=0.10,
    )
    cfg.validate()  # should not raise


# ---------------------------------------------------------------------------
# 7. The "why" — reasoning and risk_breakdown populated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoning_populated_on_pass():
    gw = _make_gateway(_make_flood_resp(flood_risk_index=0.05))
    agent = RiskAgent(gw)
    _, events = await agent.execute([_make_candidate()], {})

    risk_event = next(e for e in events if e.action == "CandidateRiskEvaluated")
    reasoning = risk_event.details.get("reasoning", "")
    assert len(reasoning) > 50
    assert "ACCEPTED" in reasoning


@pytest.mark.asyncio
async def test_reasoning_populated_on_reject():
    flood = _make_flood_resp(
        flood_zone="Zone AE (100-Year Base Flood)",
        flood_risk_index=0.95,
        historical_flood_events=5,
        annual_flood_probability=0.025,
    )
    gw = _make_gateway(flood)
    agent = RiskAgent(gw)
    _, events = await agent.execute([_make_candidate(slope_pct=7.0)], {})

    risk_event = next(e for e in events if e.action == "CandidateRiskEvaluated")
    reasoning = risk_event.details["reasoning"]
    assert "REJECTED" in reasoning
    assert "flood" in reasoning.lower()


@pytest.mark.asyncio
async def test_risk_breakdown_present_and_sums_to_composite():
    flood = _make_flood_resp(flood_risk_index=0.30, historical_flood_events=2,
                             annual_flood_probability=0.005)
    gw = _make_gateway(flood)
    agent = RiskAgent(gw)
    cands, events = await agent.execute([_make_candidate(slope_pct=3.0)], {})

    risk_event = next(e for e in events if e.action == "CandidateRiskEvaluated")
    breakdown = risk_event.details["risk_breakdown"]
    composite = risk_event.details["composite_risk"]

    # All four components must be present
    assert "flood_index_contrib" in breakdown
    assert "hist_events_contrib" in breakdown
    assert "slope_contrib" in breakdown
    assert "annual_prob_contrib" in breakdown

    # Components must sum to the reported composite
    total = sum(breakdown.values())
    assert total == pytest.approx(composite, abs=1e-3)


@pytest.mark.asyncio
async def test_reasoning_flags_upstream_degradation():
    gw = MagicMock()
    gw.get_flood_hazard = AsyncMock(side_effect=ConnectionError("down"))
    agent = RiskAgent(gw)
    _, events = await agent.execute([_make_candidate()], {})

    risk_event = next(e for e in events if e.action == "CandidateRiskEvaluated")
    assert "MOCK" in risk_event.details["reasoning"] or \
           "fallback" in risk_event.details["reasoning"].lower()


# ---------------------------------------------------------------------------
# 8. Confidence scoring — marginal composite gets lower confidence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_marginal_composite_has_lower_confidence():
    """A site at 0.74 (just below 0.75 threshold) should have lower confidence
    than one at 0.10."""
    cfg = RiskConfig(
        composite_risk_rejection_threshold=0.75,
        flood_weight=0.55,
        hist_events_weight=0.20,
        slope_weight=0.15,
        annual_prob_weight=0.10,
    )
    # Build a flood response that yields composite ≈ 0.74
    # 0.55*0.90 + 0.20*(3/5) + 0.15*(4/8) + 0.10*(0.018/0.02)
    # = 0.495 + 0.12 + 0.075 + 0.09 = 0.78 — try lower: flood_idx=0.88
    # 0.55*0.88 + 0.20*0 + 0.15*0 + 0.10*0 = 0.484 → too low
    # Use direct formula check instead
    from agents.risk_agent import _confidence_score as cs
    conf_marginal = cs(0.74, cfg, upstream_degraded=False)
    conf_safe = cs(0.10, cfg, upstream_degraded=False)
    assert conf_marginal < conf_safe


# ---------------------------------------------------------------------------
# 9. Immutability — original Candidate not mutated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_original_candidate_not_mutated():
    """model_copy() should produce a new object; the original must be unchanged."""
    gw = _make_gateway(_make_flood_resp(flood_risk_index=0.05))
    agent = RiskAgent(gw)
    original = _make_candidate()
    original_risk = original.composite_risk  # 0.0

    updated, _ = await agent.execute([original], {})

    # Original unchanged
    assert original.composite_risk == original_risk
    assert original.flood_risk_score == 0.0

    # Updated candidate has new values
    assert updated[0].composite_risk > 0.0


# ---------------------------------------------------------------------------
# 10. Annual flood probability is factored into composite (not decorative)
# ---------------------------------------------------------------------------

def test_annual_prob_contributes_to_composite():
    """With all other factors at zero, a non-zero annual probability should
    still produce a non-zero composite score."""
    cfg = RiskConfig(
        flood_weight=0.55,
        hist_events_weight=0.20,
        slope_weight=0.15,
        annual_prob_weight=0.10,
    )
    composite, breakdown = _composite_score(
        flood_risk_index=0.0,
        historical_flood_events=0,
        slope_pct=0.0,
        annual_flood_probability=0.02,  # = normaliser → norm=1.0
        cfg=cfg,
    )
    assert breakdown["annual_prob_contrib"] == pytest.approx(0.10, abs=1e-4)
    assert composite == pytest.approx(0.10, abs=1e-4)


# ---------------------------------------------------------------------------
# 11. Empty candidate list — no crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_candidates_returns_empty():
    agent = RiskAgent(_make_gateway())
    cands, events = await agent.execute([], {})
    assert cands == []
    actions = [e.action for e in events]
    assert "HazardScoring" in actions


# ---------------------------------------------------------------------------
# 12. Weights recorded in trace event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_weights_recorded_in_trace_details():
    cfg = RiskConfig(
        flood_weight=0.55, hist_events_weight=0.20,
        slope_weight=0.15, annual_prob_weight=0.10,
    )
    gw = _make_gateway()
    agent = RiskAgent(gw, config=cfg)
    _, events = await agent.execute([_make_candidate()], {})

    risk_event = next(e for e in events if e.action == "CandidateRiskEvaluated")
    weights = risk_event.details.get("weights_used", {})
    assert weights["flood"] == 0.55
    assert weights["annual_prob"] == 0.10
