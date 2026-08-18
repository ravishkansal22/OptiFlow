import pytest
from agents.controller_agent import ControllerAgent
from schemas.state import InputSpec


@pytest.mark.asyncio
async def test_full_10_agent_pipeline():
    controller = ControllerAgent()
    spec = InputSpec(
        region_name="Puget Sound Logistics Corridor",
        target_warehouses_to_open=3
    )

    state = await controller.run_full_pipeline(spec)

    # 1. Check Site Generation & Screening
    assert len(state["candidates"]) > 0
    passed_cands = [c for c in state["candidates"] if c.passed_screening]
    assert len(passed_cands) > 0

    # 2. Check Logistics Graph
    assert state["graph"] is not None
    assert len(state["graph"].suppliers) > 0
    assert len(state["graph"].warehouses) > 0
    assert len(state["graph"].customers) > 0
    assert len(state["graph"].edges) > 0

    # 3. Check Optimization & Frontier
    assert len(state["frontier"]) > 0
    active_id = state["active_solution_id"]
    active_sol = next((s for s in state["frontier"] if s.solution_id == active_id), None)
    assert active_sol is not None
    assert active_sol.total_cost > 0
    assert active_sol.resilience_score > 0.0

    # 4. Check Critic Audit
    assert state["critic_report"] is not None
    assert state["critic_report"].evidence_coverage_pct > 80.0

    # 5. Check Narrator Report
    assert len(state["narrative"]) > 100
    assert "Executive Logistics Intelligence Summary" in state["narrative"]
