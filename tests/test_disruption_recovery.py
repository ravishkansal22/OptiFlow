import pytest
import time
from agents.controller_agent import ControllerAgent
from schemas.state import InputSpec


@pytest.mark.asyncio
async def test_disruption_and_sub_60s_recovery():
    controller = ControllerAgent()
    spec = InputSpec(
        region_name="Puget Sound Logistics Corridor",
        target_warehouses_to_open=4
    )

    # Initial Run
    state = await controller.run_full_pipeline(spec)
    initial_sol_id = state["active_solution_id"]

    # Trigger Flood Disruption
    t0 = time.perf_counter()
    post_disruption_state = await controller.trigger_disruption(state, scenario_type="flood_green_river")
    elapsed_recovery = time.perf_counter() - t0

    # Validate sub-60s claim (should complete in well under 5 seconds)
    assert elapsed_recovery < 60.0, f"Recovery took {elapsed_recovery:.2f}s, exceeding 60s limit!"

    # Validate disruption state
    assert len(post_disruption_state["disruption_log"]) == 1
    disruption = post_disruption_state["disruption_log"][0]
    assert disruption.disruption_type == "flood"
    assert len(disruption.affected_warehouse_ids) > 0

    # Validate recovered solution
    recovered_sol_id = post_disruption_state["active_solution_id"]
    recovered_sol = next((s for s in post_disruption_state["frontier"] if s.solution_id == recovered_sol_id), None)
    assert recovered_sol is not None
    assert recovered_sol.demand_retained_pct > 0.0
    assert recovered_sol.resilience_score > 0.0
