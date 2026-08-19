# OptiFlow — Audit Snapshot
*Last updated: 2026-08-19 (Route/Graph Builder Agent upgrade pass applied)*

## Status by Component

### Agents
| Agent | Status | File Path |
|-------|--------|-----------|
| Controller | complete | `agents/controller_agent.py` |
| Mireye Gateway | complete | `agents/mireye_gateway_agent.py` |
| Site Generation | **upgraded** | `agents/site_agent.py` |
| Risk | **upgraded** | `agents/risk_agent.py` |
| Route/Graph Builder | **upgraded** | `agents/route_agent.py` |
| Optimization | complete | `agents/optimization_agent.py` |
| Disaster Simulation | complete | `agents/disaster_agent.py` |
| Recovery | complete | `agents/recovery_agent.py` |
| Critic | complete | `agents/critic_agent.py` |
| Narrator | complete | `agents/narrator_agent.py` |

### Backend (FastAPI)
| Module | Status | File Path |
|--------|--------|-----------|
| Main API (`main.py`) | complete | `api/main.py` |
| WebSocket (`ws.py`) | complete | `api/ws.py` |

### Frontend (React)
| Module | Status | File Path |
|--------|--------|-----------|
| App Component | complete | `frontend/src/App.tsx` |
| Components | partial | `frontend/src/components/*` |

### Shared Schemas / NetworkState
| Module | Status | File Path |
|--------|--------|-----------|
| State Schemas | complete | `schemas/state.py` |
| Mireye Schemas | complete | `schemas/mireye.py` |

## Test Results
- Total: **55 passed, 0 failed, 0 errored**
- Passing:
  - `test_disruption_and_sub_60s_recovery`
  - `test_geohash_encoding`
  - `test_haversine_distance`
  - `test_mireye_gateway_terrain_and_provenance`
  - `test_mireye_gateway_flood_and_routing`
  - `test_redis_connection_error_is_logged`
  - `test_milp_baseline_and_pareto_frontier`
  - `test_full_10_agent_pipeline`
  - `test_provenance_tag_creation`
  - `test_candidate_serialization`
  - `test_network_solution_resilience_formula`
  - `test_happy_path_site_passes` *(new)*
  - `test_happy_path_provenance_attached` *(new)*
  - `test_slope_too_high_rejects` *(new)*
  - `test_elevation_too_high_rejects` *(new)*
  - `test_occupied_parcel_rejects` *(new)*
  - `test_small_parcel_rejects` *(new)*
  - `test_custom_config_stricter_slope` *(new)*
  - `test_custom_config_looser_parcel` *(new)*
  - `test_terrain_failure_degrades_gracefully` *(new)*
  - `test_both_mireye_calls_fail_rejects_site` *(new)*
  - `test_missing_latlon_uses_default_and_warns` *(new)*
  - `test_non_dict_seed_is_skipped_gracefully` *(new)*
  - `test_non_list_seeds_raises_type_error` *(new)*
  - `test_reasoning_populated_on_pass` *(new)*
  - `test_reasoning_populated_on_reject` *(new)*
  - `test_reasoning_flags_upstream_degradation` *(new)*
  - `test_confidence_near_slope_limit_is_lower` *(new)*
  - `test_empty_seed_list_returns_empty` *(new)*
  - `test_trace_events_contain_thresholds_used` *(new — site agent)*
  - `test_low_risk_site_passes` *(new — risk agent)*
  - `test_high_risk_site_rejected` *(new)*
  - `test_pre_rejected_candidate_forwarded_unchanged` *(new)*
  - `test_stricter_threshold_rejects_medium_risk_site` *(new)*
  - `test_looser_threshold_passes_moderate_risk` *(new)*
  - `test_flood_fetch_failure_degrades_gracefully` *(new)*
  - `test_flood_fetch_failure_uses_conservative_score` *(new)*
  - `test_non_list_candidates_raises` *(new)*
  - `test_non_dict_seeds_map_raises` *(new)*
  - `test_risk_config_bad_weights_raises` *(new)*
  - `test_risk_config_good_weights_ok` *(new)*
  - `test_reasoning_populated_on_pass` *(new — risk)*
  - `test_reasoning_populated_on_reject` *(new)*
  - `test_risk_breakdown_present_and_sums_to_composite` *(new)*
  - `test_reasoning_flags_upstream_degradation` *(new — risk)*
  - `test_marginal_composite_has_lower_confidence` *(new)*
  - `test_original_candidate_not_mutated` *(new)*
  - `test_annual_prob_contributes_to_composite` *(new)*
  - `test_empty_candidates_returns_empty` *(new)*
  - `test_weights_recorded_in_trace_details` *(new)*
  - `test_happy_path_constructs_graph` *(new — route agent)*
  - `test_haversine_distance_math` *(new)*
  - `test_graceful_routing_degradation` *(new)*
  - `test_graceful_hazards_degradation` *(new)*
  - `test_input_validation` *(new)*
- Failing/Erroring: None

## Dependency Audit
### Missing from requirements.txt (imported in code but not listed)
- Standard library modules only (no missing third-party packages found).

### Unused in requirements.txt
- `pymoo`: Included in `requirements.txt` (presumably for NSGA-II optimization), but `optimization_agent.py` implements the Pareto frontier using a manual grid sweep over the `resilience_bias` parameter with OR-Tools instead of actually using `pymoo`.

### Docker Compose mismatches
- `docker-compose.yml` specifies a `redis` service and sets `REDIS_HOST=redis`. The Python code correctly handles the Redis integration optionally, so it matches.

## Known Gaps and Inconsistencies

### ✅ Upgrade Pass — Route/Graph Builder Agent (2026-08-19)

File: [`agents/route_agent.py`](agents/route_agent.py) | Tests: [`tests/test_route_agent.py`](tests/test_route_agent.py) (5 new tests)

**What changed:**
- **`RouteConfig` dataclass**: Made routing mode (`"heavy_truck"`), concurrency limits, and fallback
  heuristics (speed, cost, circuitry factor) configurable constructor arguments.
- **Concurrent routing batching**: Replaced N×M sequential routing calls with `asyncio.gather` bounded by
  an `asyncio.Semaphore`. This prevents hammering the Mireye API and massively accelerates graph building.
- **Graceful routing degradation (Haversine fallback)**: If a specific edge fails routing (e.g. timeout,
  unreachable coordinates), it no longer crashes the pipeline. Instead, it computes a straight-line Haversine
  distance, applies the `circuitry_factor` and `fallback_speed_kmh`, marks `upstream_degraded=True` in the edge's
  provenance, and assigns a pessimistic risk score.
- **Graceful hazards degradation**: Wrapped the regional hazards fetch in a `try/except`. Failure returns
  an empty list rather than aborting.
- **Input validation**: Basic type checks on raw node dictionaries before instantiation.
- **Enhanced traces**: The completion trace event now reports `degraded_edges_count` so downstream
  agents and human operators know the fidelity of the logistics graph.

**What's still rough for a future pass:**
- Haversine fallback doesn't account for geographical barriers (mountains, rivers). A future upgrade could
  implement a fast local offline router (e.g. OSRM or GraphHopper) to provide a high-fidelity fallback
  when the primary Mireye routing API goes down.
- Node coordinates aren't validated against the bounding box before routing, which could result in
  excessively long edges if a coordinate is anomalous.

### ✅ Upgrade Pass — Risk Agent (2026-08-19)

File: [`agents/risk_agent.py`](agents/risk_agent.py) | Tests: [`tests/test_risk_agent.py`](tests/test_risk_agent.py) (20 new tests)

**What changed:**
- **`RiskConfig` dataclass**: Formula weights (flood 0.55 / hist 0.20 / slope 0.15 / annual_prob 0.10),
  normalisers, and rejection threshold (0.75) are now constructor args with documented defaults.
  `RiskConfig.validate()` asserts weights sum to 1.0 at construction time.
- **Annual flood probability as a 4th scoring signal**: Previously fetched from Mireye but only
  stored decoratively in the trace. Now contributes 10% to the composite formula.
- **Immutable candidate updates**: Switched from direct attribute mutation (`cand.flood_risk_score = ...`)
  to `cand.model_copy(update={...})` so the original objects are never modified in-place.
- **Graceful Mireye degradation**: `get_flood_hazard()` wrapped in `try/except`. On failure:
  conservative flood score (0.50) and zeroed ancillary signals are used; `upstream_degraded=True`
  is recorded; confidence is penalised by 0.35. Pipeline never crashes.
- **Risk breakdown dict**: `details['risk_breakdown']` records each component's individual
  contribution so the Critic Agent can pinpoint the dominant driver without re-computing.
- **Dominant-driver reasoning**: `_build_reasoning()` identifies the highest-contributing factor
  and explains whether the score is comfortable, marginal, or over the threshold.
- **Confidence scoring**: `_confidence_score()` penalises values within 15% of the rejection
  threshold and degrades further for upstream failures.
- **Interface stability**: `execute(candidates, raw_seeds_map) → (List[Candidate], List[AgentTraceEvent])`
  **unchanged** — Controller Agent requires no modification.

**What's still rough for a future pass:**
- `reasoning` and `confidence_score` live in trace event `details`, not on the `Candidate` schema.
  Same future-schema-evolution note as Site Agent.
- The 4-factor weights (0.55/0.20/0.15/0.10) were chosen to approximate the original 3-factor
  formula. A proper calibration against historical loss data would sharpen these.
- `slope_normaliser_pct` in `RiskConfig` duplicates `SiteConfig.max_slope_pct`. A shared
  constants module or cross-agent config object would eliminate that duplication.

### ✅ Upgrade Pass — Site Generation Agent (2026-08-19)

File: [`agents/site_agent.py`](agents/site_agent.py) | Tests: [`tests/test_site_agent.py`](tests/test_site_agent.py) (19 new tests)

**What changed:**
- **`SiteConfig` dataclass**: All 4 previously hardcoded thresholds (slope 8%, elevation 250m,
  min parcel 25k sqm, search radius 500m) are now constructor arguments with documented defaults.
  Pass a custom `SiteConfig` to change any threshold without touching source code.
- **Input validation**: `_validate_seed()` bounds-checks lat/lon before any Mireye call;
  missing or out-of-range coordinates log a `WARNING` and substitute the configured default
  rather than silently proceeding with garbage coordinates.
- **Graceful Mireye degradation**: Both gateway calls (`get_terrain_elevation`,
  `get_land_cover_buildings`) are wrapped in `try/except`. On failure:
  - Partial failure (one call succeeds): site continues with reduced confidence, `upstream_degraded=True`.
  - Total failure (both calls fail): site is explicitly **REJECTED** with a clear reason,
    not silently accepted with zeroed fields.
- **Confidence scoring** (`0.0–1.0`): `_confidence_score()` penalises values within a
  configurable marginal band of each threshold, and deducts 0.30 for degraded upstream data.
  Stored in `trace_event.details['confidence_score']`.
- **Reasoning strings**: `_build_reasoning()` produces a human-readable explanation of each
  decision (why a site passed or failed, which values were marginal, data quality caveats).
  Stored in `trace_event.details['reasoning']` — feeds Critic Agent and provenance trail.
- **Observability**: Structured `logger.warning` at every rejection (keyed by `candidate_id`)
  and `logger.info` for accepted sites. Thresholds used are recorded in every trace event's
  `details['thresholds_used']` so audit history is self-contained.
- **Interface stability**: `execute(state, raw_candidate_seeds) -> (List[Candidate], List[AgentTraceEvent])`
  is **unchanged** — Controller Agent requires no modification.

**What's still rough for a future pass:**
- `reasoning` and `confidence_score` are stored only in trace event `details`, not as dedicated
  fields on the `Candidate` schema. A future schema evolution could promote them to first-class
  fields so downstream agents (Risk, Critic) can read them programmatically without parsing dicts.
- The fallback values when terrain is missing (slope=0, elevation=0) will cause a site to pass
  slope/elevation checks but fail on parcel=0. This is deliberately conservative but could be
  revisited to use regional median values once a proper data-quality layer is in place.
- No retry logic on Mireye calls (e.g., exponential backoff with 2 retries). The Gateway agent
  itself should own retry, but if it doesn't, the Site Agent has no recourse beyond logging.

### ✅ Fixed — Silent exception handling (2026-08-19)
- `agents/mireye_gateway_agent.py` (formerly :128, :135, :173): All three bare
  `except Exception: pass` blocks now log a `WARNING` via the `logging` module.
  Fallback behaviour is unchanged — Redis misses still fall through to in-memory
  cache; Mireye live-call failures still fall through to mock data.
- `api/main.py` (formerly :62): `trace_broadcaster` bare `except` now logs a
  `WARNING`; the loop still does not crash on broadcast failure.
- Regression test added: `tests/test_mireye_gateway.py::test_redis_connection_error_is_logged`.

### ⚠️ Intentionally Deferred — Real Mireye API integration
- **All Mireye data is currently mock/simulation only.** The real HTTP path in
  `agents/mireye_gateway_agent.py` is only attempted when `MIREYE_API_KEY` is
  set to a non-mock value (i.e. does *not* start with `"mock"`). In all other
  cases the code falls through to the **MIREYE_MOCK_MODE** block (clearly
  labelled with a comment at line ~185 in the updated file).
- **Integration point**: Set `MIREYE_API_KEY` and `MIREYE_BASE_URL` in the
  environment, then wire error handling inside the `except Exception as exc`
  block in `get_terrain_elevation` (and equivalent blocks to be added to
  `get_land_cover_buildings`, `get_flood_hazard`, `get_routing`, and
  `get_regional_hazards` when live calls are enabled for those endpoints).
- This deferral is intentional; do not add live-API logic without a dedicated
  integration session.

### ⚠️ Open — `pymoo` / NSGA-II mismatch
- `optimization_agent.py`: docstring claims NSGA-II but implementation is a
  manual `resilience_bias` grid sweep using OR-Tools. `pymoo` in
  `requirements.txt` is currently unused. Deferred to a future session.

## Recommended Next Step
**[Implement True NSGA-II Pareto Optimization]**

Modify `agents/optimization_agent.py` to actually use `pymoo` for the NSGA-II
multi-objective optimization, instead of the current manual weight-sweep approach.
This would fulfil the architectural promise of a true Pareto search and activate
the currently unused `pymoo` dependency.

Files needed for that session:
- `agents/optimization_agent.py`
- `schemas/state.py` (for `NetworkSolution` / `ParetoFrontier` schemas)
- `requirements.txt` (to confirm `pymoo` version pin)
- `tests/test_optimization.py` (existing MILP/Pareto test to extend)
