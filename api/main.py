import asyncio
import logging
import time
import os
import uuid
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from schemas.state import (
    NetworkState,
    InputSpec,
    AgentTraceEvent,
    NetworkSolution
)
from schemas.mireye import ProvenanceTag
from agents.controller_agent import ControllerAgent
from agents.mireye_gateway_agent import MireyeGatewayAgent
from agents.site_agent import SiteGenerationAgent
from agents.risk_agent import RiskAgent
from agents.site_scoring import score_candidates, normalise_weights
from api.ws import ws_manager

log = logging.getLogger("optiflow.api")

app = FastAPI(
    title="OptiFlow API",
    description="Agentic Logistics Network Intelligence powered by Mireye",
    version="1.0.0"
)

# CORS Setup
origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State Container
mireye_gateway = MireyeGatewayAgent()
def _empty_state() -> NetworkState:
    return {
        "inputs": InputSpec(),
        "mireye_cache": {},
        "candidates": [],
        "graph": None,
        "frontier": [],
        "active_solution_id": "",
        "disruption_log": [],
        "impact_report": None,
        "recovery_report": None,
        "pre_disruption_graph": None,
        "pre_disruption_solution_id": "",
        "critic_flags": [],
        "critic_report": None,
        "narrative": "",
        "trace_events": []
    }


global_state: NetworkState = _empty_state()

# One pipeline phase at a time. A second /api/analyze or /api/optimize while one
# is already running would interleave trace events and clobber the state.
pipeline_lock = asyncio.Lock()
pipeline_stage: str = "idle"  # idle | analyzing | optimizing | disrupting | recovering


#: Live events kept on the state so a page loaded mid-run still gets the replay.
MAX_LIVE_TRACE = 600


def trace_broadcaster(event: AgentTraceEvent):
    """
    Broadcasts one agent trace event to connected clients, and keeps it on the
    state so a client that connects part-way through a run is replayed what it
    missed. The pipeline overwrites this list with its own authoritative one
    when the phase finishes.
    """
    try:
        buffer = global_state.setdefault("trace_events", [])
        buffer.append(event)
        if len(buffer) > MAX_LIVE_TRACE:
            del buffer[:-MAX_LIVE_TRACE]
    except Exception:
        pass
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(ws_manager.broadcast({
                "type": "agent_trace",
                "event": event.model_dump()
            }))
    except Exception:
        pass


controller = ControllerAgent(gateway=mireye_gateway, event_callback=trace_broadcaster)


class SiteInput(BaseModel):
    """A single user-supplied candidate location to evaluate."""
    id: Optional[str] = None
    name: Optional[str] = None
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    capacity_units: float = Field(default=20000.0, gt=0.0)
    fixed_cost: float = Field(default=130000.0, ge=0.0)

    def to_seed(self, index: int) -> Dict[str, Any]:
        """Shape expected by SiteGenerationAgent / RiskAgent."""
        site_id = self.id or f"user_site_{index + 1}"
        return {
            "id": site_id,
            "name": self.name or f"Site {index + 1}",
            "lat": self.lat,
            "lon": self.lon,
            "base_capacity": self.capacity_units,
            "fixed_cost": self.fixed_cost,
        }


class SupplierInput(BaseModel):
    """A user-supplied supply origin, replacing the region dataset for a run."""
    id: Optional[str] = None
    name: Optional[str] = None
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    capacity_units: float = Field(default=50000.0, gt=0.0)
    unit_supply_cost: float = Field(default=10.0, ge=0.0)

    def to_node(self, index: int) -> Dict[str, Any]:
        return {
            "id": self.id or f"user_supplier_{index + 1}",
            "name": self.name or f"Supplier {index + 1}",
            "lat": self.lat,
            "lon": self.lon,
            "capacity_units": self.capacity_units,
            "unit_supply_cost": self.unit_supply_cost,
        }


class CustomerInput(BaseModel):
    """A user-supplied demand zone, replacing the region dataset for a run."""
    id: Optional[str] = None
    name: Optional[str] = None
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    demand_units: float = Field(default=1000.0, gt=0.0)
    service_sla_minutes: Optional[float] = None
    priority: int = Field(default=1, ge=1, le=3)

    def to_node(self, index: int, default_sla: float) -> Dict[str, Any]:
        return {
            "id": self.id or f"user_customer_{index + 1}",
            "name": self.name or f"Demand zone {index + 1}",
            "lat": self.lat,
            "lon": self.lon,
            "demand_units": self.demand_units,
            "service_sla_minutes": self.service_sla_minutes or default_sla,
            "priority": self.priority,
        }


class ScoreWeights(BaseModel):
    """Weights for the suitability score. Normalised to sum to 1 before use."""
    hazard_headroom: float = Field(default=0.40, ge=0.0)
    slope_headroom: float = Field(default=0.25, ge=0.0)
    parcel_adequacy: float = Field(default=0.20, ge=0.0)
    capacity_share: float = Field(default=0.15, ge=0.0)


class EvaluateSitesRequest(BaseModel):
    sites: List[SiteInput] = Field(..., min_length=1, max_length=50)
    weights: Optional[ScoreWeights] = None


class RunRequest(BaseModel):
    region_name: Optional[str] = "Puget Sound Logistics Corridor"
    target_warehouses: Optional[int] = 4
    service_radius_minutes: Optional[float] = 60.0
    budget_limit_usd: Optional[float] = 2500000.0
    # Which point on the finished frontier is recommended first. The frontier is
    # built the same way regardless; this only moves the starting selection.
    optimization_preference: Optional[str] = Field(
        default="balanced", pattern="^(cost|balanced|resilience)$"
    )
    # Minimum share of demand the plan should serve inside the delivery window.
    # Recorded with the run and reported back; the Critic checks the result.
    min_demand_coverage_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    # When supplied, each of these replaces the matching part of the region
    # dataset for this run. Hazard layers always come from the dataset and the
    # Mireye Gateway.
    custom_sites: Optional[List[SiteInput]] = None
    custom_suppliers: Optional[List[SupplierInput]] = None
    custom_customers: Optional[List[CustomerInput]] = None


class DisruptionRequest(BaseModel):
    # Any id the Disaster Simulation Agent knows, including "auto".
    scenario_type: str = "flood_green_river"
    # Scenario-specific choices; the keys come from GET /api/scenarios.
    params: Optional[Dict[str, Any]] = None
    # Recovery used to run in the same call. It is a separate step now so the
    # damage can be seen first; pass true for the old one-shot behaviour.
    auto_recover: bool = False


class SwitchSolutionRequest(BaseModel):
    solution_id: str


class AskNarratorRequest(BaseModel):
    query: str


def _spec_from_request(req: "RunRequest") -> InputSpec:
    spec = InputSpec(
        region_name=req.region_name or "Puget Sound Logistics Corridor",
        target_warehouses_to_open=req.target_warehouses or 4,
        service_radius_minutes=req.service_radius_minutes or 60.0,
        budget_limit_usd=req.budget_limit_usd or 2500000.0,
        optimization_preference=req.optimization_preference or "balanced",
        min_demand_coverage_pct=req.min_demand_coverage_pct or 0.0,
    )
    return spec


def _seeds_from_request(req: "RunRequest", spec: InputSpec):
    seeds = (
        [site.to_seed(i) for i, site in enumerate(req.custom_sites)]
        if req.custom_sites
        else None
    )
    if seeds:
        # Opening more hubs than the user supplied sites is impossible; asking for
        # it only produces a confusing "no feasible plan".
        spec.target_warehouses_to_open = min(spec.target_warehouses_to_open, len(seeds))
    return seeds


def _nodes_from_request(req: "RunRequest", spec: InputSpec):
    """Supplier and customer overrides, or None to use the region dataset."""
    suppliers = (
        [s.to_node(i) for i, s in enumerate(req.custom_suppliers)]
        if req.custom_suppliers
        else None
    )
    customers = (
        [c.to_node(i, spec.service_radius_minutes) for i, c in enumerate(req.custom_customers)]
        if req.custom_customers
        else None
    )
    return suppliers, customers


@app.on_event("startup")
async def startup_event():
    """
    Dispatches the baseline run so a network is waiting on first load.
    Set OPTIFLOW_BASELINE_ON_STARTUP=0 to boot idle and let the UI drive
    every phase itself.
    """
    if os.getenv("OPTIFLOW_BASELINE_ON_STARTUP", "1").strip().lower() in {"0", "false", "no", "off"}:
        log.info("Baseline startup run disabled by OPTIFLOW_BASELINE_ON_STARTUP.")
        return
    asyncio.create_task(_run_pipeline_task(InputSpec()))


async def _run_pipeline_task(
    spec: InputSpec,
    candidate_seeds: Optional[List[Dict[str, Any]]] = None,
    suppliers: Optional[List[Dict[str, Any]]] = None,
    customers: Optional[List[Dict[str, Any]]] = None,
):
    global global_state, pipeline_stage
    started = time.perf_counter()
    source = f"{len(candidate_seeds)} custom sites" if candidate_seeds else "region dataset"
    log.info(
        "PIPELINE START region=%r hubs=%s sla=%smin budget=%s source=%s",
        spec.region_name, spec.target_warehouses_to_open,
        spec.service_radius_minutes, spec.budget_limit_usd, source
    )
    before_live = mireye_gateway.live_calls
    before_sim = mireye_gateway.simulated_calls
    async with pipeline_lock:
        pipeline_stage = "analyzing"
        await _full_pipeline_body(
            spec, candidate_seeds, suppliers, customers, started, before_live, before_sim
        )


async def _full_pipeline_body(
    spec, candidate_seeds, suppliers, customers, started, before_live, before_sim
):
    global global_state, pipeline_stage
    try:
        final_state = await controller.run_full_pipeline(
            spec, candidate_seeds=candidate_seeds, suppliers=suppliers, customers=customers
        )
        global_state.update(final_state)
        pipeline_stage = "optimized"
        elapsed = time.perf_counter() - started
        live = mireye_gateway.live_calls - before_live
        sim = mireye_gateway.simulated_calls - before_sim
        log.info(
            "PIPELINE DONE in %.0fs | frontier=%d | api calls: %d live, %d simulated (%.0f/min)",
            elapsed, len(final_state.get("frontier", [])), live, sim,
            (live + sim) / (elapsed / 60) if elapsed else 0
        )
        await ws_manager.broadcast({
            "type": "pipeline_complete",
            "active_solution_id": global_state.get("active_solution_id")
        })
    except Exception as e:
        pipeline_stage = "idle"
        log.exception("PIPELINE FAILED after %.0fs: %s", time.perf_counter() - started, e)
        await ws_manager.broadcast({
            "type": "pipeline_error",
            "error": str(e)
        })


async def _run_analysis_task(spec: InputSpec, candidate_seeds=None, suppliers=None, customers=None):
    """
    Phase one: screen every candidate site and build the routed graph. Stops
    before the solver so the shortlist can be reviewed.
    """
    global global_state, pipeline_stage
    async with pipeline_lock:
        pipeline_stage = "analyzing"
        started = time.perf_counter()
        source = f"{len(candidate_seeds)} custom sites" if candidate_seeds else "region dataset"
        log.info(
            "ANALYSIS START region=%r hubs=%s sla=%smin budget=%s source=%s",
            spec.region_name, spec.target_warehouses_to_open,
            spec.service_radius_minutes, spec.budget_limit_usd, source
        )
        try:
            state = await controller.run_screening_pipeline(
                spec, candidate_seeds=candidate_seeds, suppliers=suppliers, customers=customers
            )
            global_state = _empty_state()
            global_state.update(state)
            pipeline_stage = "analyzed"
            graph = global_state.get("graph")
            log.info(
                "ANALYSIS DONE in %.0fs | candidates=%d | qualified=%d",
                time.perf_counter() - started,
                len(global_state.get("candidates", [])),
                len(graph.warehouses) if graph else 0,
            )
            await ws_manager.broadcast({
                "type": "analysis_complete",
                "candidate_count": len(global_state.get("candidates", [])),
                "qualified_count": len(graph.warehouses) if graph else 0,
            })
        except Exception as e:
            pipeline_stage = "idle"
            log.exception("ANALYSIS FAILED after %.0fs: %s", time.perf_counter() - started, e)
            await ws_manager.broadcast({"type": "pipeline_error", "phase": "analyze", "error": str(e)})


async def _run_optimization_task():
    """Phase two: MILP + NSGA-II, the Critic audit and the Narrator report."""
    global global_state, pipeline_stage
    async with pipeline_lock:
        pipeline_stage = "optimizing"
        started = time.perf_counter()
        try:
            state = await controller.run_optimization_pipeline(global_state)
            global_state.update(state)
            pipeline_stage = "optimized"
            log.info(
                "OPTIMIZATION DONE in %.0fs | frontier=%d",
                time.perf_counter() - started, len(global_state.get("frontier", []))
            )
            await ws_manager.broadcast({
                "type": "pipeline_complete",
                "phase": "optimize",
                "active_solution_id": global_state.get("active_solution_id")
            })
        except Exception as e:
            pipeline_stage = "analyzed"
            log.exception("OPTIMIZATION FAILED after %.0fs: %s", time.perf_counter() - started, e)
            await ws_manager.broadcast({"type": "pipeline_error", "phase": "optimize", "error": str(e)})


@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "service": "OptiFlow Logistics Intelligence",
        "mireye_cache_count": len(mireye_gateway.memory_cache),
        "active_ws_clients": len(ws_manager.active_connections),
        "data_source": mireye_gateway.data_source_summary()
    }


def _dump(value):
    return value.model_dump() if hasattr(value, "model_dump") else value


def serialize_state() -> Dict[str, Any]:
    """The whole master state, in the shape the frontend types mirror."""
    return {
        "inputs": _dump(global_state.get("inputs")),
        "candidates": [c.model_dump() for c in global_state.get("candidates", [])],
        "graph": _dump(global_state.get("graph")),
        "frontier": [s.model_dump() for s in global_state.get("frontier", [])],
        "active_solution_id": global_state.get("active_solution_id"),
        "disruption_log": [d.model_dump() for d in global_state.get("disruption_log", [])],
        "impact_report": _dump(global_state.get("impact_report")),
        "recovery_report": _dump(global_state.get("recovery_report")),
        "critic_flags": global_state.get("critic_flags", []),
        "critic_report": _dump(global_state.get("critic_report")),
        "narrative": global_state.get("narrative", ""),
        "trace_events": [t.model_dump() for t in global_state.get("trace_events", [])],
        # Workflow position, so a reloaded page resumes where it left off.
        "stage": pipeline_stage,
        "can_restore": bool(global_state.get("pre_disruption_graph")),
        # The design in place before the first disruption. It stays the
        # recommendation even while the network runs in its recovered state.
        "pre_disruption_solution_id": global_state.get("pre_disruption_solution_id", ""),
    }


@app.get("/api/state")
async def get_state():
    """Returns the full master network state."""
    return serialize_state()


@app.post("/api/run")
async def run_pipeline(req: RunRequest, background_tasks: BackgroundTasks):
    """Triggers the full 10-Agent LangGraph optimization workflow end to end."""
    spec = _spec_from_request(req)
    seeds = _seeds_from_request(req, spec)
    suppliers, customers = _nodes_from_request(req, spec)

    background_tasks.add_task(_run_pipeline_task, spec, seeds, suppliers, customers)
    return {
        "message": "OptiFlow multi-agent optimization pipeline dispatched in background.",
        "candidate_source": "custom_sites" if seeds else "region_dataset",
        "candidate_count": len(seeds) if seeds else None,
    }


@app.post("/api/analyze")
async def analyze_network(req: RunRequest, background_tasks: BackgroundTasks):
    """
    Runs the geospatial half of the pipeline: Site Generation, Risk scoring and
    the Route/Graph build. Returns immediately; progress arrives on /ws/trace and
    an analysis_complete signal is broadcast when the shortlist is ready.
    """
    if pipeline_lock.locked():
        raise HTTPException(status_code=409, detail=f"A {pipeline_stage} run is already in flight.")

    spec = _spec_from_request(req)
    seeds = _seeds_from_request(req, spec)
    suppliers, customers = _nodes_from_request(req, spec)

    background_tasks.add_task(_run_analysis_task, spec, seeds, suppliers, customers)
    return {
        "message": "Site, risk and routing agents dispatched.",
        "candidate_source": "custom_sites" if seeds else "region_dataset",
        "candidate_count": len(seeds) if seeds else None,
    }


@app.post("/api/optimize")
async def optimize_network(background_tasks: BackgroundTasks):
    """
    Runs the solver half of the pipeline over the analysed graph: OR-Tools MILP,
    the NSGA-II frontier sweep, the Critic audit and the Narrator report.
    """
    if pipeline_lock.locked():
        raise HTTPException(status_code=409, detail=f"A {pipeline_stage} run is already in flight.")
    if not global_state.get("graph"):
        raise HTTPException(status_code=400, detail="No analysed network yet. Run /api/analyze first.")

    background_tasks.add_task(_run_optimization_task)
    return {"message": "Optimization, critic and narrator agents dispatched."}


@app.get("/api/scenarios")
async def list_scenarios():
    """
    The disruption scenarios that can run against the current network, with the
    choices each one offers. Options are built from the live graph, so nothing
    here is offered that the network does not contain.
    """
    graph = global_state.get("graph")
    frontier = global_state.get("frontier", [])
    active_id = global_state.get("active_solution_id")
    active_sol = next((s for s in frontier if s.solution_id == active_id), frontier[0] if frontier else None)
    return {
        "ready": bool(graph and active_sol),
        "scenarios": controller.disaster_agent.catalogue(graph, active_sol),
    }


@app.post("/api/evaluate-sites")
async def evaluate_sites(req: EvaluateSitesRequest):
    """
    Screens user-supplied coordinates for warehouse suitability and ranks them.

    Runs the same Site Generation and Risk agents the full pipeline uses, so a
    site is judged against identical slope, elevation, parcel and hazard gates.
    Read-only: this does not touch the global network state.
    """
    seeds = [site.to_seed(i) for i, site in enumerate(req.sites)]

    if len({s["id"] for s in seeds}) != len(seeds):
        raise HTTPException(status_code=400, detail="Duplicate site ids in request.")

    site_agent = SiteGenerationAgent(mireye_gateway)
    risk_agent = RiskAgent(mireye_gateway)

    try:
        candidates, site_events = await site_agent.execute({}, seeds)
        candidates, risk_events = await risk_agent.execute(candidates, {s["id"]: s for s in seeds})
    except RuntimeError as exc:
        # Strict mode refused to substitute simulated values. Report why rather
        # than returning a plausible-looking but fabricated verdict.
        log.warning("evaluate-sites aborted: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))

    # The same scoring the pipeline uses, with any weight override applied.
    w = req.weights or ScoreWeights()
    weight_map = normalise_weights({
        "hazard_headroom": w.hazard_headroom,
        "slope_headroom": w.slope_headroom,
        "parcel_adequacy": w.parcel_adequacy,
        "capacity_share": w.capacity_share,
    })
    components_by_id = score_candidates(candidates, weight_map)

    results = []
    for cand in candidates:
        components = components_by_id[cand.id]
        score = cand.suitability_score

        prov = cand.provenance or {}
        layer_live = {k: bool(v.live) for k, v in prov.items()}

        results.append({
            "id": cand.id,
            "name": cand.name,
            "lat": cand.lat,
            "lon": cand.lon,
            "passed": cand.passed_screening,
            "rejection_reasons": cand.rejection_reasons,
            "suitability_score": score,
            "score_components": components,
            "terrain_slope_pct": cand.terrain_slope_pct,
            "elevation_m": cand.elevation_m,
            "land_cover": cand.land_cover,
            "parcel_area_sqm": cand.parcel_area_sqm,
            "is_occupied": cand.is_occupied,
            "flood_risk_score": cand.flood_risk_score,
            "composite_risk": cand.composite_risk,
            "capacity_units": cand.capacity_units,
            "fixed_operating_cost": cand.fixed_operating_cost,
            "provenance": {k: v.model_dump() for k, v in cand.provenance.items()},
            # Per-layer origin so a verdict is never read as live when it is not.
            "layer_live": layer_live,
            "all_live": bool(layer_live) and all(layer_live.values()),
            "rank": None,
        })

    # Rank only the sites that cleared screening; rejects stay unranked.
    passed = sorted(
        [r for r in results if r["passed"]],
        key=lambda r: (-r["suitability_score"], r["fixed_operating_cost"]),
    )
    for position, row in enumerate(passed, 1):
        row["rank"] = position

    ordered = passed + [r for r in results if not r["passed"]]

    # A recommendation resting on simulated values is not evidence, so only a
    # fully-live site can be named best.
    live_passed = [r for r in passed if r["all_live"]]
    best_id = live_passed[0]["id"] if live_passed else None
    best_blocked_reason = None
    if not live_passed and passed:
        best_blocked_reason = (
            "Every site that passed relies on at least one simulated value, so none can be "
            "recommended on evidence."
        )

    return {
        "evaluated": len(results),
        "passed": len(passed),
        "rejected": len(results) - len(passed),
        "best_site_id": best_id,
        "best_blocked_reason": best_blocked_reason,
        "weights": weight_map,
        "sites": ordered,
        "data_source": {
            **mireye_gateway.data_source_summary(),
            # Counted from these sites' own provenance rather than the gateway's
            # global counters, which would also pick up any concurrent pipeline run.
            "live_values_this_request": sum(
                1 for r in results for ok in r["layer_live"].values() if ok
            ),
            "simulated_values_this_request": sum(
                1 for r in results for ok in r["layer_live"].values() if not ok
            ),
        },
        "trace_events": [e.model_dump() for e in (site_events + risk_events)],
    }


@app.post("/api/disrupt")
async def trigger_disruption(req: DisruptionRequest):
    """
    Runs a geographically grounded disruption scenario against the active plan
    and measures what it did. Recovery is a separate call unless auto_recover
    is set, which restores the original one-shot behaviour.
    """
    global global_state, pipeline_stage
    if not global_state.get("graph"):
        raise HTTPException(status_code=400, detail="Initial network optimization not yet executed.")
    if not global_state.get("frontier"):
        raise HTTPException(status_code=400, detail="No active network plan to stress test.")

    async with pipeline_lock:
        pipeline_stage = "disrupting"
        try:
            updated_state = await controller.apply_disruption(
                global_state, req.scenario_type, req.params
            )
            global_state.update(updated_state)
            if req.auto_recover:
                pipeline_stage = "recovering"
                global_state.update(await controller.recover_from_disruption(global_state))
                pipeline_stage = "recovered"
            else:
                pipeline_stage = "disrupted"
        except Exception as e:
            pipeline_stage = "optimized"
            log.exception("DISRUPTION FAILED: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    impact = global_state.get("impact_report")
    await ws_manager.broadcast({
        "type": "disruption_resolved" if req.auto_recover else "disruption_applied",
        "active_solution_id": global_state.get("active_solution_id"),
        "disruption_id": impact.disruption_id if impact else None,
    })

    return {
        "message": f"Disruption '{req.scenario_type}' simulated.",
        "active_solution_id": global_state.get("active_solution_id"),
        "impact_report": impact.model_dump() if impact else None,
        "recovery_report": _dump(global_state.get("recovery_report")),
    }


@app.post("/api/recover")
async def recover_network():
    """
    Runs the Recovery / Verification Agent against the latest disruption: a
    warm-started delta re-solve, re-audited by the Critic and re-narrated.
    """
    global global_state, pipeline_stage
    if not global_state.get("impact_report"):
        raise HTTPException(status_code=400, detail="No disruption to recover from.")
    if global_state.get("recovery_report"):
        raise HTTPException(status_code=409, detail="This disruption has already been recovered.")

    async with pipeline_lock:
        pipeline_stage = "recovering"
        try:
            global_state.update(await controller.recover_from_disruption(global_state))
            pipeline_stage = "recovered"
        except Exception as e:
            pipeline_stage = "disrupted"
            log.exception("RECOVERY FAILED: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

    await ws_manager.broadcast({
        "type": "disruption_resolved",
        "active_solution_id": global_state.get("active_solution_id")
    })

    return {
        "message": "Recovery re-solve completed.",
        "active_solution_id": global_state.get("active_solution_id"),
        "recovery_report": _dump(global_state.get("recovery_report")),
    }


@app.post("/api/restore")
async def restore_network():
    """
    Puts the network back as it was before the first disruption so another
    scenario can be tested against the same starting point.
    """
    global global_state, pipeline_stage
    if not global_state.get("pre_disruption_graph"):
        raise HTTPException(status_code=400, detail="Nothing to restore; the network has not been disrupted.")

    async with pipeline_lock:
        global_state.update(controller.restore_network(global_state))
        pipeline_stage = "optimized"

    await ws_manager.broadcast({
        "type": "network_restored",
        "active_solution_id": global_state.get("active_solution_id")
    })
    return {
        "message": "Network restored to its pre-disruption state.",
        "active_solution_id": global_state.get("active_solution_id"),
    }


@app.post("/api/switch-solution")
async def switch_solution(req: SwitchSolutionRequest):
    """Switches the active Pareto solution on the dashboard."""
    global global_state
    frontier = global_state.get("frontier", [])
    target_sol = next((s for s in frontier if s.solution_id == req.solution_id), None)
    if not target_sol:
        raise HTTPException(status_code=404, detail="Solution ID not found in Pareto frontier.")

    global_state["active_solution_id"] = req.solution_id

    # Re-generate narrative for selected solution
    inputs = global_state.get("inputs", InputSpec())
    region_name = inputs.region_name if hasattr(inputs, "region_name") else "Puget Sound Corridor"
    candidates = global_state.get("candidates", [])
    graph = global_state.get("graph")
    disruption_log = global_state.get("disruption_log", [])
    latest_disruption = disruption_log[-1] if disruption_log else None
    critic_report = global_state.get("critic_report")

    narrative, _ = controller.narrator_agent.generate_narrative(
        inputs_region=region_name,
        candidates=candidates,
        graph=graph,
        frontier=frontier,
        active_solution=target_sol,
        disruption=latest_disruption,
        critic_report=critic_report
    )
    global_state["narrative"] = narrative

    await ws_manager.broadcast({
        "type": "solution_switched",
        "solution_id": req.solution_id
    })

    return {"message": f"Switched to solution {target_sol.name}", "solution": target_sol.model_dump()}


@app.post("/api/ask")
async def ask_narrator(req: AskNarratorRequest):
    """Interactive endpoint for free-form What-If inquiries."""
    candidates = global_state.get("candidates", [])
    graph = global_state.get("graph")
    frontier = global_state.get("frontier", [])
    active_id = global_state.get("active_solution_id")
    active_sol = next((s for s in frontier if s.solution_id == active_id), frontier[0] if frontier else None)

    if not graph or not active_sol:
        raise HTTPException(status_code=400, detail="Network state not ready.")

    response = await controller.narrator_agent.answer_what_if(
        query=req.query,
        candidates=candidates,
        graph=graph,
        frontier=frontier,
        active_solution=active_sol
    )
    return response


@app.get("/api/region")
async def get_region():
    """
    The region the server has loaded: its bounds, its suppliers, its demand
    zones, its hazard layers and its candidate sites. The setup screen draws
    its map preview and its defaults from this rather than from anything
    hardcoded in the client.
    """
    data = controller.raw_data or {}
    defaults = InputSpec()
    return {
        "region_name": data.get("region_name", defaults.region_name),
        "bounding_box": data.get("bounding_box", defaults.bounding_box),
        "suppliers": data.get("suppliers", []),
        "customers": data.get("customers", []),
        "candidate_warehouses": data.get("candidate_warehouses", []),
        "hazard_zones": data.get("hazard_zones", []),
        "defaults": defaults.model_dump(),
    }


@app.get("/api/data-source")
async def data_source():
    """
    Reports how much of the data served so far actually came from the Mireye API
    rather than the local simulation fallback.
    """
    return mireye_gateway.data_source_summary()


@app.post("/api/reset")
async def reset_everything():
    """
    Clears every cached geospatial value, the call history and the whole network
    state, so the next run starts from nothing.
    """
    global global_state, pipeline_stage
    removed = mireye_gateway.clear_cache()
    controller.raw_data = controller._load_dataset()
    global_state = _empty_state()
    pipeline_stage = "idle"
    await ws_manager.broadcast({"type": "state_reset"})
    return {"message": "Cache and network state cleared.", "removed": removed}


@app.get("/api/provenance-trace")
async def get_provenance_trace():
    """Returns the full audit log of all Mireye API calls and provenance tags."""
    return {
        "call_count": len(mireye_gateway.call_history),
        "history": mireye_gateway.call_history[-100:]
    }


@app.websocket("/ws/trace")
async def websocket_trace_endpoint(websocket: WebSocket):
    """WebSocket stream for real-time agent execution traces and Mireye queries."""
    await ws_manager.connect(websocket)
    try:
        # Send current trace buffer on connection
        current_events = [t.model_dump() for t in global_state.get("trace_events", [])]
        await websocket.send_json({
            "type": "initial_trace",
            "events": current_events
        })
        while True:
            # Keep-alive loop
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)
