"""
tests/test_critic_agent.py

Tests for the upgraded CriticAgent, covering:
  1. Happy path — clean provenance, no violations, coverage 100%, passes.
  2. Stale candidate provenance is detected and flagged.
  3. Missing candidate provenance (terrain/land_cover) is flagged.
  4. Surviving (passed_screening) candidate missing flood provenance flagged.
  5. Evidence coverage threshold gates the verdict even with zero violations.
  6. Capacity overload constraint violation.
  7. Unassigned customer constraint violation.
  8. Customer assigned to a closed facility constraint violation.
  9. Budget limit exceeded constraint violation.
 10. Edge provenance missing / stale (sampled edge audit).
 11. edge_sample_size caps how many edges get audited.
 12. Unparseable timestamps are treated as stale by default, and honour the
     treat_unparseable_timestamp_as_stale override.
 13. CriticConfig validation (staleness window, coverage pct, sample size).
 14. Trace events — start/complete present, status reflects audit outcome.
 15. Warning-level logging on a flagged audit.
"""
import logging
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from agents.critic_agent import CriticAgent, CriticConfig
from schemas.state import Candidate
from schemas.mireye import ProvenanceTag


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_provenance(minutes_ago: float = 0.0, endpoint: str = "/v1/mock", timestamp: str = None) -> ProvenanceTag:
    if timestamp is None:
        ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    else:
        ts = timestamp
    return ProvenanceTag(
        endpoint=endpoint,
        params={},
        timestamp=ts,
        response_hash="deadbeef",
        cached=False,
        latency_ms=8.0,
    )


def _fresh_provenance_set() -> dict:
    return {
        "terrain": _make_provenance(0),
        "land_cover": _make_provenance(0),
        "flood": _make_provenance(0),
    }


def _make_candidate(
    id: str = "WH-A",
    name: str = "Warehouse Alpha",
    passed_screening: bool = True,
    provenance: dict = None,
) -> Candidate:
    return Candidate(
        id=id,
        name=name,
        lat=47.41,
        lon=-122.24,
        terrain_slope_pct=2.0,
        elevation_m=30.0,
        land_cover="Industrial",
        parcel_area_sqm=60_000.0,
        is_occupied=False,
        flood_risk_score=0.05,
        hazard_score=0.1,
        composite_risk=0.15,
        passed_screening=passed_screening,
        rejection_reasons=[],
        fixed_operating_cost=130_000.0,
        capacity_units=20_000.0,
        provenance=provenance if provenance is not None else {},
    )


def _make_warehouse(id: str, name: str, capacity_units: float, lat: float = 47.4, lon: float = -122.2):
    return SimpleNamespace(id=id, name=name, lat=lat, lon=lon, capacity_units=capacity_units)


def _make_customer(id: str, name: str, demand_units: float):
    return SimpleNamespace(id=id, name=name, demand_units=demand_units)


def _make_edge(id: str, source_id: str, target_id: str, provenance=None):
    return SimpleNamespace(id=id, source_id=source_id, target_id=target_id, provenance=provenance)


def _make_graph(warehouses=None, customers=None, edges=None, suppliers=None):
    return SimpleNamespace(
        warehouses=warehouses or [],
        customers=customers or [],
        edges=edges or [],
        suppliers=suppliers or [],
    )


def _make_solution(
    solution_id: str = "sol-1",
    selected_warehouse_ids=None,
    customer_assignments=None,
    total_cost: float = 1_000_000.0,
):
    return SimpleNamespace(
        solution_id=solution_id,
        selected_warehouse_ids=selected_warehouse_ids or [],
        customer_assignments=customer_assignments or {},
        total_cost=total_cost,
    )


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_clean_audit_passes():
    cand = _make_candidate(provenance=_fresh_provenance_set())
    wh = _make_warehouse("wh-1", "Warehouse 1", capacity_units=1000)
    cust = _make_customer("cust-1", "Customer 1", demand_units=500)
    edge = _make_edge("e1", "wh-1", "cust-1", provenance=_make_provenance(0))
    graph = _make_graph(warehouses=[wh], customers=[cust], edges=[edge])
    solution = _make_solution(
        selected_warehouse_ids=["wh-1"],
        customer_assignments={"cust-1": "wh-1"},
        total_cost=500_000.0,
    )
    agent = CriticAgent()
    report, events = agent.execute_audit([cand], graph, solution, budget_limit_usd=1_000_000.0)

    assert report.passed is True
    assert report.constraint_violations == []
    assert report.missing_provenance_count == 0
    assert report.stale_provenance_count == 0
    assert report.evidence_coverage_pct == 100.0


# ---------------------------------------------------------------------------
# 2. Stale candidate provenance
# ---------------------------------------------------------------------------

def test_stale_candidate_provenance_flagged():
    stale_prov = {
        "terrain": _make_provenance(60),  # older than the default 30 min window
        "land_cover": _make_provenance(0),
        "flood": _make_provenance(0),
    }
    cand = _make_candidate(provenance=stale_prov)
    agent = CriticAgent()
    report, _ = agent.execute_audit([cand], _make_graph(), _make_solution())

    assert report.stale_provenance_count >= 1
    assert any("stale" in f.lower() for f in report.flags)


# ---------------------------------------------------------------------------
# 3. Missing candidate provenance
# ---------------------------------------------------------------------------

def test_missing_candidate_provenance_flagged():
    cand = _make_candidate(provenance={})
    agent = CriticAgent()
    report, _ = agent.execute_audit([cand], _make_graph(), _make_solution())

    assert report.missing_provenance_count >= 1
    assert report.passed is False
    assert any("missing terrain/landcover" in f.lower() for f in report.flags)


# ---------------------------------------------------------------------------
# 4. Surviving candidate missing flood provenance
# ---------------------------------------------------------------------------

def test_surviving_candidate_missing_flood_provenance_flagged():
    prov = {"terrain": _make_provenance(0), "land_cover": _make_provenance(0)}
    cand = _make_candidate(passed_screening=True, provenance=prov)
    agent = CriticAgent()
    report, _ = agent.execute_audit([cand], _make_graph(), _make_solution())

    assert any("missing flood hazard" in f.lower() for f in report.flags)
    assert report.missing_provenance_count >= 1


def test_rejected_candidate_flood_provenance_not_required():
    """A candidate that already failed screening doesn't need flood provenance."""
    prov = {"terrain": _make_provenance(0), "land_cover": _make_provenance(0)}
    cand = _make_candidate(passed_screening=False, provenance=prov)
    agent = CriticAgent()
    report, _ = agent.execute_audit([cand], _make_graph(), _make_solution())

    assert not any("missing flood hazard" in f.lower() for f in report.flags)


# ---------------------------------------------------------------------------
# 5. Evidence coverage gates the verdict even with zero violations
# ---------------------------------------------------------------------------

def test_coverage_threshold_fails_audit_even_without_violations():
    cfg = CriticConfig(min_evidence_coverage_pct=100.0)
    stale_prov = {
        "terrain": _make_provenance(60),
        "land_cover": _make_provenance(0),
        "flood": _make_provenance(0),
    }
    cand = _make_candidate(provenance=stale_prov)
    agent = CriticAgent(config=cfg)
    report, _ = agent.execute_audit([cand], _make_graph(), _make_solution())

    assert report.constraint_violations == []
    assert report.evidence_coverage_pct < 100.0
    assert report.passed is False


# ---------------------------------------------------------------------------
# 6. Capacity overload
# ---------------------------------------------------------------------------

def test_capacity_overload_violation():
    wh = _make_warehouse("wh-1", "Warehouse 1", capacity_units=100)
    cust = _make_customer("cust-1", "Customer 1", demand_units=500)
    edge = _make_edge("e1", "wh-1", "cust-1", provenance=_make_provenance(0))
    graph = _make_graph(warehouses=[wh], customers=[cust], edges=[edge])
    solution = _make_solution(
        selected_warehouse_ids=["wh-1"],
        customer_assignments={"cust-1": "wh-1"},
    )
    agent = CriticAgent()
    report, _ = agent.execute_audit([], graph, solution)

    assert any("Capacity Overload" in v for v in report.constraint_violations)
    assert report.passed is False


# ---------------------------------------------------------------------------
# 7. Unassigned customer
# ---------------------------------------------------------------------------

def test_unassigned_customer_violation():
    cust = _make_customer("cust-1", "Customer 1", demand_units=200)
    graph = _make_graph(customers=[cust])
    solution = _make_solution(customer_assignments={})
    agent = CriticAgent()
    report, _ = agent.execute_audit([], graph, solution)

    assert any("unassigned" in v.lower() for v in report.constraint_violations)


# ---------------------------------------------------------------------------
# 8. Customer assigned to a closed facility
# ---------------------------------------------------------------------------

def test_customer_assigned_to_closed_facility_violation():
    cust = _make_customer("cust-1", "Customer 1", demand_units=200)
    graph = _make_graph(customers=[cust])
    solution = _make_solution(
        selected_warehouse_ids=["wh-open"],
        customer_assignments={"cust-1": "wh-closed"},
    )
    agent = CriticAgent()
    report, _ = agent.execute_audit([], graph, solution)

    assert any("closed facility" in v.lower() for v in report.constraint_violations)


# ---------------------------------------------------------------------------
# 9. Budget limit exceeded
# ---------------------------------------------------------------------------

def test_budget_exceeded_violation():
    solution = _make_solution(total_cost=5_000_000.0)
    agent = CriticAgent()
    report, _ = agent.execute_audit([], _make_graph(), solution, budget_limit_usd=3_000_000.0)

    assert any("Budget Limit Exceeded" in v for v in report.constraint_violations)
    assert report.passed is False


# ---------------------------------------------------------------------------
# 10. Edge provenance missing / stale
# ---------------------------------------------------------------------------

def test_edge_missing_provenance_flagged():
    edge = _make_edge("e1", "wh-1", "cust-1", provenance=None)
    graph = _make_graph(edges=[edge])
    agent = CriticAgent()
    report, _ = agent.execute_audit([], graph, _make_solution())

    assert report.missing_provenance_count >= 1
    assert any("missing mireye provenance hash" in f.lower() for f in report.flags)


def test_edge_stale_provenance_flagged():
    edge = _make_edge("e1", "wh-1", "cust-1", provenance=_make_provenance(45))
    graph = _make_graph(edges=[edge])
    agent = CriticAgent()
    report, _ = agent.execute_audit([], graph, _make_solution())

    assert report.stale_provenance_count >= 1
    assert any("routing edge e1" in f.lower() and "stale" in f.lower() for f in report.flags)


def test_edge_fresh_provenance_not_flagged():
    edge = _make_edge("e1", "wh-1", "cust-1", provenance=_make_provenance(0))
    graph = _make_graph(edges=[edge])
    agent = CriticAgent()
    report, _ = agent.execute_audit([], graph, _make_solution())

    assert report.stale_provenance_count == 0
    assert report.missing_provenance_count == 0


# ---------------------------------------------------------------------------
# 11. edge_sample_size caps sampling
# ---------------------------------------------------------------------------

def test_edge_sample_size_caps_sampling():
    cfg = CriticConfig(edge_sample_size=2)
    edges = [_make_edge(f"e{i}", "wh-1", "cust-1", provenance=None) for i in range(5)]
    graph = _make_graph(edges=edges)
    agent = CriticAgent(config=cfg)
    report, _ = agent.execute_audit([], graph, _make_solution())

    # Only the first 2 (of 5) edges are sampled/audited.
    assert report.missing_provenance_count == 2


# ---------------------------------------------------------------------------
# 12. Unparseable timestamps
# ---------------------------------------------------------------------------

def test_unparseable_timestamp_treated_as_stale_by_default():
    bad_prov = ProvenanceTag(
        endpoint="/v1/mock", params={}, timestamp="not-a-timestamp",
        response_hash="deadbeef", cached=False, latency_ms=8.0,
    )
    cand = _make_candidate(provenance={
        "terrain": bad_prov, "land_cover": _make_provenance(0), "flood": _make_provenance(0),
    })
    agent = CriticAgent()
    report, _ = agent.execute_audit([cand], _make_graph(), _make_solution())

    assert report.stale_provenance_count >= 1


def test_unparseable_timestamp_not_stale_when_configured():
    cfg = CriticConfig(treat_unparseable_timestamp_as_stale=False)
    bad_prov = ProvenanceTag(
        endpoint="/v1/mock", params={}, timestamp="not-a-timestamp",
        response_hash="deadbeef", cached=False, latency_ms=8.0,
    )
    cand = _make_candidate(provenance={
        "terrain": bad_prov, "land_cover": _make_provenance(0), "flood": _make_provenance(0),
    })
    agent = CriticAgent(config=cfg)
    report, _ = agent.execute_audit([cand], _make_graph(), _make_solution())

    assert report.stale_provenance_count == 0


# ---------------------------------------------------------------------------
# 13. CriticConfig validation
# ---------------------------------------------------------------------------

def test_critic_config_bad_staleness_window_raises():
    with pytest.raises(ValueError, match="staleness_window_minutes"):
        CriticConfig(staleness_window_minutes=0).validate()


def test_critic_config_bad_coverage_pct_raises():
    with pytest.raises(ValueError, match="min_evidence_coverage_pct"):
        CriticConfig(min_evidence_coverage_pct=150.0).validate()


def test_critic_config_bad_edge_sample_size_raises():
    with pytest.raises(ValueError, match="edge_sample_size"):
        CriticConfig(edge_sample_size=0).validate()


def test_critic_config_good_values_ok():
    cfg = CriticConfig(staleness_window_minutes=15, min_evidence_coverage_pct=95.0, edge_sample_size=10)
    cfg.validate()  # should not raise


def test_critic_agent_rejects_invalid_config_at_construction():
    with pytest.raises(ValueError):
        CriticAgent(config=CriticConfig(staleness_window_minutes=-5))


# ---------------------------------------------------------------------------
# 14. Trace events
# ---------------------------------------------------------------------------

def test_trace_events_start_and_complete_present():
    agent = CriticAgent()
    _, events = agent.execute_audit([], _make_graph(), _make_solution())

    actions = [e.action for e in events]
    assert actions.count("EvidenceAndConstraintAudit") == 2
    statuses = [e.status for e in events]
    assert statuses[0] == "start"
    assert statuses[-1] in ("complete", "warning")


def test_trace_event_status_warning_when_audit_fails():
    solution = _make_solution(total_cost=10_000_000.0)
    agent = CriticAgent()
    report, events = agent.execute_audit([], _make_graph(), solution, budget_limit_usd=1_000_000.0)

    assert report.passed is False
    complete_event = events[-1]
    assert complete_event.status == "warning"
    assert complete_event.details["audit_passed"] is False


def test_trace_event_status_complete_when_audit_passes():
    agent = CriticAgent()
    report, events = agent.execute_audit([], _make_graph(), _make_solution())

    assert report.passed is True
    complete_event = events[-1]
    assert complete_event.status == "complete"
    assert complete_event.details["audit_passed"] is True


# ---------------------------------------------------------------------------
# 15. Logging
# ---------------------------------------------------------------------------

def test_audit_failure_logs_warning(caplog):
    solution = _make_solution(total_cost=10_000_000.0)
    agent = CriticAgent()
    with caplog.at_level(logging.WARNING, logger="agents.critic_agent"):
        agent.execute_audit([], _make_graph(), solution, budget_limit_usd=1_000_000.0)

    assert any("Audit FLAGGED" in r.getMessage() for r in caplog.records)


def test_audit_success_logs_info(caplog):
    agent = CriticAgent()
    with caplog.at_level(logging.INFO, logger="agents.critic_agent"):
        agent.execute_audit([], _make_graph(), _make_solution())

    assert any("Audit PASSED" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 16. Empty inputs — no crash
# ---------------------------------------------------------------------------

def test_empty_everything_no_crash():
    agent = CriticAgent()
    report, events = agent.execute_audit([], _make_graph(), _make_solution())

    assert report.passed is True
    assert report.constraint_violations == []
    assert len(events) == 2