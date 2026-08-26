"""
test_agents_with_mireye_api.py
================================
Live, agent-by-agent diagnostic test harness for the OptiFlow 10-agent
LangGraph pipeline.

WHAT THIS SCRIPT DOES DIFFERENTLY FROM tests/test_*.py
--------------------------------------------------------
The existing pytest suite (tests/test_mireye_gateway.py, test_optimization.py,
etc.) uses small unit fixtures and never talks to a real network. This script
is the opposite: it is a manual, human-readable terminal run that

  1. Loads real credentials from a .env file (MIREYE_API_KEY / MIREYE_BASE_URL)
     if present, and constructs the REAL, unmocked MireyeGatewayAgent from
     agents/mireye_gateway_agent.py. If a live key is configured, the gateway's
     own code path will attempt a genuine HTTPS call -- nothing in this script
     patches that logic or fakes its return value.
  2. Adds a thin, non-invasive logging tap on httpx.AsyncClient.get purely so
     that any real network attempt (success, timeout, DNS failure, 4xx/5xx)
     is printed to the terminal instead of being silently swallowed. The
     gateway's own fallback behavior is untouched -- this only makes it visible.
  3. Runs every one of the 10 agents individually, in dependency order, on a
     small hand-built mock dataset (defined below) -- not the full pilot
     region -- so a full run finishes in well under a minute of actual
     compute plus the mandatory pauses.
  4. Pauses 5 seconds after each agent's printed output so the run is easy to
     follow live in a terminal.
  5. Records a structured result (status / duration / output summary / error)
     for every agent via record_result(), and at the end writes both a JSON
     and a plain-text report under test_reports/.

IMPORTANT CODEBASE FINDING (read this before you assume "live" == "live everywhere")
--------------------------------------------------------------------------------------
UPDATED: MireyeGatewayAgent.get_terrain_elevation(), get_land_cover_buildings(),
get_flood_hazard(), and get_routing() ALL now contain a real live-call branch
(POST /v1/fetch with the matching preset, or POST /v1/proximity for routing),
matching Mireye's actual documented API (https://docs.mireye.ai). Each one falls
back to the local simulation model only if no valid key is configured, the live
call fails/errors, or the response is missing the specific fields that method needs.
get_regional_hazards() is the ONE method that remains simulation-only by necessity,
not by omission: Mireye's real API has no bounding-box/region-polygon endpoint at
all, and no field in its catalog returns polygon/geometry data -- there is no live
call this method could make. This script labels each call accordingly so the
terminal output doesn't overstate (or understate) what's actually live.

USAGE
-----
    cd OptiFlow
    pip install -r requirements.txt python-dotenv
    # optional: put a real key in .env
    #   MIREYE_API_KEY=...
    #   MIREYE_BASE_URL=https://your-real-mireye-host/...
    python test_agents_with_mireye_api.py
"""

import os
import sys
import json
import time
import asyncio
import traceback
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    print("(python-dotenv not installed -- skipping .env autoload; "
          "export MIREYE_API_KEY / MIREYE_BASE_URL manually if you want a live test)")

import httpx
from pydantic import BaseModel

from schemas.state import InputSpec
from agents.mireye_gateway_agent import MireyeGatewayAgent
from agents.site_agent import SiteGenerationAgent
from agents.risk_agent import RiskAgent
from agents.route_agent import RouteGraphBuilderAgent
from agents.optimization_agent import OptimizationAgent
from agents.disaster_agent import DisasterSimulationAgent
from agents.recovery_agent import RecoveryVerificationAgent
from agents.critic_agent import CriticAgent
from agents.narrator_agent import NarratorAgent
from agents.controller_agent import ControllerAgent

# ======================================================================
# CONFIG
# ======================================================================
PAUSE_SECONDS = 5
OUTPUT_DIR = PROJECT_ROOT / "test_reports"
OUTPUT_DIR.mkdir(exist_ok=True)
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
MAX_PRINT_CHARS = 2200  # long payloads are summarized in-terminal, full JSON always goes to disk


# ======================================================================
# SMALL, DETERMINISTIC MOCK FIXTURE (opt-in via OPTIFLOW_TEST_SMALL_MOCK=1)
# Deliberately tiny so live/simulated Mireye calls and the MILP solve finish
# in seconds. NOT used by default anymore -- see _load_region_and_inputs()
# below, which defaults to the full 20-site / 33-customer pilot region to
# maximize real Mireye API call volume for verification.
# ======================================================================
SMALL_MOCK_REGION = {
    "region_name": "OptiFlow Test Harness Corridor",
    "bounding_box": [47.10, -122.50, 47.90, -121.90],
    "suppliers": [
        {
            "id": "sup_portA", "name": "Port A Intermodal Terminal",
            "lat": 47.2725, "lon": -122.4182,
            "capacity_units": 40000, "unit_supply_cost": 8.5
        },
        {
            "id": "sup_hubB", "name": "Rail Freight Hub B",
            "lat": 47.3809, "lon": -122.2348,
            "capacity_units": 30000, "unit_supply_cost": 8.0
        }
    ],
    # 5 candidates, all reusing REAL coordinates already seeded in
    # data/sample_region.json (the full pilot region), chosen so the small
    # harness demonstrates genuine live pass/reject outcomes instead of
    # made-up terrain that happens to mismatch reality:
    #   cand_good_site         -> Green River Logistics Center, South Kent
    #                             (real flat industrial site -- should pass cleanly)
    #   cand_auburn_hub        -> Auburn 400 Logistics Hub
    #                             (second real flat industrial site -- gives the
    #                             MILP more than one facility to choose between)
    #   cand_high_slope_cougar -> Cougar Mountain Highland Tract
    #                             (real steep mountain foothill, 14.8% slope /
    #                             310m elevation -- SHOULD be rejected on slope)
    #   cand_flood_delta       -> Puyallup River Confluence Site
    #                             (real low-lying near-river industrial site --
    #                             should pass site screening with elevated flood risk)
    #   cand_restricted_wetland -> Nisqually Delta Conservation Zone
    #                             (real protected wetland -- exercises the
    #                             land-cover-class occupancy heuristic; SHOULD be
    #                             rejected as protected/non-buildable)
    "candidate_warehouses": [
        {
            "id": "cand_good_site", "name": "Green River Logistics Center (South Kent)",
            "lat": 47.3688, "lon": -122.2289,
            "base_capacity": 28000, "fixed_cost": 125000, "parcel_sqm": 72000,
            "land_cover": "Industrial", "base_elevation_m": 9.2, "base_slope_pct": 0.5
        },
        {
            "id": "cand_auburn_hub", "name": "Auburn 400 Logistics Hub",
            "lat": 47.3075, "lon": -122.2257,
            "base_capacity": 32000, "fixed_cost": 140000, "parcel_sqm": 85000,
            "land_cover": "Industrial", "base_elevation_m": 22.0, "base_slope_pct": 1.2
        },
        {
            "id": "cand_high_slope_cougar", "name": "Cougar Mountain Highland Tract (Unbuildable)",
            "lat": 47.5350, "lon": -122.1020,
            "base_capacity": 12000, "fixed_cost": 180000, "parcel_sqm": 22000,
            "land_cover": "Forestry/SteepSlope", "base_elevation_m": 310.0, "base_slope_pct": 14.8
        },
        {
            "id": "cand_flood_delta", "name": "Puyallup River Confluence Site",
            "lat": 47.2412, "lon": -122.4089,
            "base_capacity": 25000, "fixed_cost": 120000, "parcel_sqm": 59000,
            "land_cover": "Industrial", "base_elevation_m": 5.4, "base_slope_pct": 0.4
        },
        {
            "id": "cand_restricted_wetland", "name": "Nisqually Delta Conservation Zone",
            "lat": 47.1200, "lon": -122.6800,
            "base_capacity": 10000, "fixed_cost": 95000, "parcel_sqm": 18000,
            "land_cover": "ProtectedWetland", "base_elevation_m": 2.1, "base_slope_pct": 0.2
        }
    ],
    "customers": [
        {"id": "cust_medical", "name": "Downtown Medical District", "lat": 47.60, "lon": -122.33,
         "demand_units": 4200, "service_sla_minutes": 45, "priority": 3},
        {"id": "cust_tech", "name": "Bellevue Tech Campus", "lat": 47.61, "lon": -122.20,
         "demand_units": 5200, "service_sla_minutes": 60, "priority": 2},
        {"id": "cust_urban", "name": "Tacoma Urban Center", "lat": 47.25, "lon": -122.44,
         "demand_units": 3600, "service_sla_minutes": 50, "priority": 2},
        {"id": "cust_residential", "name": "Kent Residential Zone", "lat": 47.38, "lon": -122.24,
         "demand_units": 2800, "service_sla_minutes": 40, "priority": 1}
    ],
    "hazard_zones": [
        {
            "hazard_id": "hz_duwamish_surge", "hazard_type": "FloodZone", "severity": "High",
            "coordinates": [[[-122.42, 47.22], [-122.38, 47.22], [-122.38, 47.26], [-122.42, 47.26], [-122.42, 47.22]]],
            "description": "Duwamish / lower delta storm surge corridor (mock hazard polygon)."
        }
    ]
}

SMALL_MOCK_INPUTS = InputSpec(
    region_name=SMALL_MOCK_REGION["region_name"],
    bounding_box=SMALL_MOCK_REGION["bounding_box"],
    max_candidate_warehouses=5,
    target_warehouses_to_open=3,
    service_radius_minutes=60.0,
    budget_limit_usd=500000.0,
    resilience_weight=0.6
)


# ======================================================================
# LIVE-CALL VOLUME: default to the FULL real pilot region (20 candidates,
# 5 suppliers, 33 customers from data/sample_region.json) instead of the
# small fixture above, to maximize genuine Mireye API call coverage for
# verification -- confirmed against docs.mireye.ai/pricing that a full run
# (~1,300-1,700 credits) is well within a paid-tier monthly allowance.
# Set OPTIFLOW_TEST_SMALL_MOCK=1 to fall back to the fast, small fixture
# above for a quick smoke test instead.
# ======================================================================
def _load_region_and_inputs():
    if os.getenv("OPTIFLOW_TEST_SMALL_MOCK", "0") == "1":
        return SMALL_MOCK_REGION, SMALL_MOCK_INPUTS

    region_path = PROJECT_ROOT / "data" / "sample_region.json"
    with open(region_path, "r", encoding="utf-8") as f:
        full_region = json.load(f)

    full_inputs = InputSpec(
        region_name=full_region["region_name"],
        bounding_box=full_region["bounding_box"],
        max_candidate_warehouses=len(full_region["candidate_warehouses"]),
        target_warehouses_to_open=4,
        service_radius_minutes=60.0,
        budget_limit_usd=2500000.0,
        resilience_weight=0.6
    )
    return full_region, full_inputs


MOCK_REGION, MOCK_INPUTS = _load_region_and_inputs()


# ======================================================================
# WHAT EACH AGENT DOES (used both for terminal output and the saved report)
# ======================================================================
AGENT_INFO = {
    "Mireye Gateway Agent": (
        "Owns all outbound Mireye traffic. Builds a cache key from (layer, geohash-7, radius); "
        "on a cache miss it either performs a live HTTPS call (implemented today ONLY for "
        "terrain-elevation) or falls back to a deterministic local geospatial simulation, then "
        "stamps every response with an immutable provenance tag (endpoint, params, SHA-256 "
        "response hash, cached flag, latency)."
    ),
    "Site Generation Agent": (
        "For each raw candidate site, calls the Gateway for terrain slope/elevation and land-cover/"
        "parcel data, then screens out sites with slope > 8%, elevation > 250m, protected/occupied "
        "zoning, or usable parcel area < 25,000 sqm."
    ),
    "Risk Agent": (
        "For every site that survived site screening, calls the Gateway's flood-hazard endpoint and "
        "blends flood risk index (65%), historical flood-event frequency (20%) and terrain slope "
        "(15%) into a single 0-1 composite risk score; sites above 0.75 are rejected."
    ),
    "Route / Graph Builder Agent": (
        "Assembles supplier, warehouse and customer nodes, then batches an origin-destination Gateway "
        "routing call for every supplier->warehouse and warehouse->customer pair to attach real "
        "distance/time/cost/route-risk weights, plus regional hazard polygons."
    ),
    "Optimization Agent": (
        "Formulates facility-location + multi-commodity flow as a MILP (Google OR-Tools CBC) for a "
        "least-cost baseline, then re-solves across a resilience-bias sweep to build a non-dominated "
        "Cost-vs-Resilience Pareto frontier."
    ),
    "Disaster Simulation Agent": (
        "Uses the graph's Mireye-derived flood-risk scores and node names to build a geographically "
        "grounded disruption scenario (flood, road closure, demand surge, or facility outage)."
    ),
    "Recovery / Verification Agent": (
        "Marks disrupted warehouses/edges inactive, re-assigns only the customers cut off from a "
        "disabled facility to the nearest surviving open warehouse (re-querying the Gateway only for "
        "those delta routes), targeting a sub-60-second recovery re-solve."
    ),
    "Critic Agent": (
        "Audits the final state before it reaches a user: verifies every candidate/edge carries a "
        "Mireye provenance tag, that no warehouse is over capacity, customers are only assigned to "
        "open facilities, and total cost is within budget."
    ),
    "Reporting / Narrator Agent": (
        "Synthesizes candidates, graph, Pareto frontier, active solution, disruption and critic report "
        "into an executive narrative, and separately answers free-form what-if questions by matching "
        "the query against structured state fields."
    ),
    "Mireye API Connectivity Probe": (
        "Not one of the 10 agents -- a standalone preamble check that makes a direct HTTPS GET to the "
        "configured MIREYE_BASE_URL, independent of the Gateway's own retry/fallback logic, so DNS/"
        "network/auth problems are visible immediately instead of being silently absorbed later."
    ),
    "Controller / Supervisor Agent": (
        "Compiles all of the above into a compiled LangGraph StateGraph "
        "(site -> risk -> route -> optimize -> critic -> narrate) and exposes run_full_pipeline() and "
        "trigger_disruption() as the two top-level orchestration entry points."
    ),
}


# ======================================================================
# REPORTING
# ======================================================================
class TestReport:
    def __init__(self):
        self.entries = []

    def record(self, agent_no, agent_name, status, duration_s, output_summary, raw_output=None, error=None):
        entry = {
            "agent_no": agent_no,
            "agent_name": agent_name,
            "description": AGENT_INFO.get(agent_name, ""),
            "status": status,  # "success" | "error" | "skipped"
            "duration_s": round(duration_s, 3),
            "output_summary": output_summary,
            "raw_output": raw_output,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.entries.append(entry)
        return entry

    def save(self):
        json_path = OUTPUT_DIR / f"agent_test_report_{RUN_ID}.json"
        txt_path = OUTPUT_DIR / f"agent_test_report_{RUN_ID}.txt"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2, default=str)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"OptiFlow Live Agent Test Report -- run {RUN_ID}\n")
            f.write("=" * 78 + "\n\n")
            for e in self.entries:
                f.write(f"[{e['agent_no']}] {e['agent_name']}\n")
                f.write(f"    Status:      {e['status'].upper()}   ({e['duration_s']}s)\n")
                f.write(f"    How it works: {e['description']}\n")
                f.write(f"    Output:      {e['output_summary']}\n")
                if e["error"]:
                    f.write(f"    ERROR:       {e['error']}\n")
                f.write("\n")
            n_ok = sum(1 for e in self.entries if e["status"] == "success")
            n_err = sum(1 for e in self.entries if e["status"] == "error")
            n_skip = sum(1 for e in self.entries if e["status"] == "skipped")
            f.write(f"Summary: {n_ok} succeeded, {n_err} errored, {n_skip} skipped "
                    f"out of {len(self.entries)} stages.\n")

        return json_path, txt_path


report = TestReport()


# ======================================================================
# TERMINAL HELPERS
# ======================================================================
def header(title):
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)


def to_jsonable(obj):
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    if isinstance(obj, list):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj


def print_output(obj, max_chars=MAX_PRINT_CHARS):
    payload = to_jsonable(obj)
    text = json.dumps(payload, indent=2, default=str)
    if len(text) > max_chars:
        print(text[:max_chars])
        print(f"... [truncated {len(text) - max_chars} more characters; full output saved to {OUTPUT_DIR.name}/] ...")
    else:
        print(text)


def pause(seconds=PAUSE_SECONDS):
    print(f"\n... pausing {seconds}s before the next agent ...")
    time.sleep(seconds)


# ======================================================================
# NON-INVASIVE LIVE-HTTP LOGGING TAP
# (only makes real network attempts visible in the terminal; does not
#  change the gateway's own retry/fallback behavior)
# ======================================================================
_original_asyncclient_get = httpx.AsyncClient.get
_original_asyncclient_post = httpx.AsyncClient.post
LIVE_HTTP_LOG = []


async def _traced_get(self, url, *args, **kwargs):
    t0 = time.perf_counter()
    try:
        resp = await _original_asyncclient_get(self, url, *args, **kwargs)
        dt_ms = (time.perf_counter() - t0) * 1000
        LIVE_HTTP_LOG.append({"method": "GET", "url": str(url), "status_code": resp.status_code, "latency_ms": round(dt_ms, 1), "error": None})
        print(f"    [LIVE MIREYE HTTP] GET {url} -> HTTP {resp.status_code}  ({dt_ms:.0f} ms)")
        return resp
    except Exception as exc:
        dt_ms = (time.perf_counter() - t0) * 1000
        err_txt = f"{type(exc).__name__}: {exc}"
        LIVE_HTTP_LOG.append({"method": "GET", "url": str(url), "status_code": None, "latency_ms": round(dt_ms, 1), "error": err_txt})
        print(f"    [LIVE MIREYE HTTP] GET {url} -> ERROR: {err_txt}  ({dt_ms:.0f} ms)")
        raise


async def _traced_post(self, url, *args, **kwargs):
    # NOTE: added because get_terrain_elevation/get_land_cover_buildings/get_flood_hazard/
    # get_routing all call Mireye's real /v1/fetch and /v1/proximity endpoints via POST
    # (that's the actual documented Mireye contract -- GET+query-params was never correct).
    # Without this, every one of those real live calls was invisible to LIVE_HTTP_LOG and
    # to the "live HTTP attempts this stage" counter below.
    t0 = time.perf_counter()
    body_preview = kwargs.get("json")
    try:
        resp = await _original_asyncclient_post(self, url, *args, **kwargs)
        dt_ms = (time.perf_counter() - t0) * 1000
        LIVE_HTTP_LOG.append({"method": "POST", "url": str(url), "body": body_preview, "status_code": resp.status_code, "latency_ms": round(dt_ms, 1), "error": None})
        print(f"    [LIVE MIREYE HTTP] POST {url} {body_preview} -> HTTP {resp.status_code}  ({dt_ms:.0f} ms)")
        return resp
    except Exception as exc:
        dt_ms = (time.perf_counter() - t0) * 1000
        err_txt = f"{type(exc).__name__}: {exc}"
        LIVE_HTTP_LOG.append({"method": "POST", "url": str(url), "body": body_preview, "status_code": None, "latency_ms": round(dt_ms, 1), "error": err_txt})
        print(f"    [LIVE MIREYE HTTP] POST {url} {body_preview} -> ERROR: {err_txt}  ({dt_ms:.0f} ms)")
        raise


httpx.AsyncClient.get = _traced_get
httpx.AsyncClient.post = _traced_post


async def probe_mireye_connectivity(base_url: str):
    """Direct, standalone reachability probe of the configured Mireye host
    (independent of the gateway logic) so connectivity problems are obvious
    up front rather than buried in a later agent's silent fallback."""
    header("STEP 0 -- Mireye API Connectivity Probe (direct, outside the Gateway)")
    print(f"Target base URL: {base_url}")
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(base_url)
        dt_ms = (time.perf_counter() - t0) * 1000
        print(f"REACHABLE -- HTTP {resp.status_code} in {dt_ms:.0f} ms "
              f"(a non-2xx status here is normal for a bare host root; it still proves the "
              f"network path and DNS resolve).")
        return True, f"HTTP {resp.status_code} in {dt_ms:.0f} ms"
    except Exception as exc:
        dt_ms = (time.perf_counter() - t0) * 1000
        msg = f"{type(exc).__name__}: {exc}"
        print(f"UNREACHABLE -- {msg}  ({dt_ms:.0f} ms)")
        return False, msg


# ======================================================================
# AGENT-BY-AGENT TEST STAGES
# ======================================================================
async def stage_gateway(gateway: MireyeGatewayAgent):
    header("[2] Mireye Gateway Agent")
    print(AGENT_INFO["Mireye Gateway Agent"])
    api_key_present = bool(gateway.api_key) and not gateway.api_key.startswith("mock")
    print(f"\nMIREYE_API_KEY configured: {api_key_present}   |   MIREYE_BASE_URL: {gateway.base_url}")
    if not api_key_present:
        print("No usable live key found -> every call below will use the local simulation model.")

    t0 = time.perf_counter()
    try:
        # Pick the lowest-elevation candidate as the "most flood-interesting" sample --
        # dataset-agnostic (works whether MOCK_REGION is the small fixture or the full
        # real pilot region, which don't share candidate ids), unlike the previous
        # hardcoded "cand_flood_delta" lookup that only existed in the small fixture
        # and raised StopIteration once the harness defaulted to the full dataset.
        sample = min(MOCK_REGION["candidate_warehouses"], key=lambda c: c.get("base_elevation_m", 9999))
        print(f"\n-> get_terrain_elevation() [LIVE-CAPABLE endpoint]")
        terrain = await gateway.get_terrain_elevation(sample["lat"], sample["lon"], known_base=sample)
        print_output(terrain)

        print(f"\n-> get_land_cover_buildings() [LIVE-CAPABLE endpoint]")
        land = await gateway.get_land_cover_buildings(sample["lat"], sample["lon"], known_base=sample)
        print_output(land)

        print(f"\n-> get_flood_hazard() [LIVE-CAPABLE endpoint]")
        flood = await gateway.get_flood_hazard(sample["lat"], sample["lon"], known_base=sample)
        print_output(flood)

        print(f"\n-> get_routing() [LIVE-CAPABLE endpoint via /v1/proximity]")
        routing = await gateway.get_routing(
            origin=[MOCK_REGION["suppliers"][0]["lat"], MOCK_REGION["suppliers"][0]["lon"]],
            destination=[sample["lat"], sample["lon"]]
        )
        print_output(routing)

        print(f"\n-> get_terrain_elevation() AGAIN on the same point -- should now be served from cache")
        terrain_cached = await gateway.get_terrain_elevation(sample["lat"], sample["lon"], known_base=sample)
        print(f"    cached={terrain_cached.provenance.cached}  (expect True)")

        dt = time.perf_counter() - t0
        summary = (f"terrain elevation={terrain.elevation_m}m slope={terrain.slope_pct}%; "
                   f"land_cover={land.primary_land_cover}; flood_zone={flood.flood_zone}; "
                   f"route={routing.distance_km}km/{routing.duration_minutes}min; "
                   f"2nd terrain call cached={terrain_cached.provenance.cached}; "
                   f"live HTTP attempts this stage={len(LIVE_HTTP_LOG)}")
        report.record(2, "Mireye Gateway Agent", "success", dt, summary,
                       raw_output={"terrain": to_jsonable(terrain), "land_cover": to_jsonable(land),
                                   "flood": to_jsonable(flood), "routing": to_jsonable(routing)})
        return gateway
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Mireye Gateway Agent stage: {err}")
        report.record(2, "Mireye Gateway Agent", "error", dt, "Gateway stage failed.", error=err)
        return gateway


async def stage_site_generation(gateway):
    header("[3] Site Generation Agent")
    print(AGENT_INFO["Site Generation Agent"])
    agent = SiteGenerationAgent(gateway)
    t0 = time.perf_counter()
    try:
        candidates, events = await agent.execute({}, MOCK_REGION["candidate_warehouses"])
        dt = time.perf_counter() - t0
        for e in events:
            print(f"  [{e.status.upper():8s}] {e.message}")
        print()
        print_output(candidates)
        passed = [c.id for c in candidates if c.passed_screening]
        rejected = {c.id: c.rejection_reasons for c in candidates if not c.passed_screening}
        summary = f"{len(passed)}/{len(candidates)} passed site screening -> {passed}; rejected -> {rejected}"
        report.record(3, "Site Generation Agent", "success", dt, summary, raw_output=to_jsonable(candidates))
        return candidates
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Site Generation Agent: {err}")
        report.record(3, "Site Generation Agent", "error", dt, "Site screening failed.", error=err)
        return None


async def stage_risk(gateway, candidates):
    header("[4] Risk Agent")
    print(AGENT_INFO["Risk Agent"])
    if candidates is None:
        print("SKIPPED -- upstream Site Generation Agent did not produce candidates.")
        report.record(4, "Risk Agent", "skipped", 0.0, "Skipped: no candidates from Site Generation Agent.")
        return None
    agent = RiskAgent(gateway)
    raw_seeds_map = {c["id"]: c for c in MOCK_REGION["candidate_warehouses"]}
    t0 = time.perf_counter()
    try:
        updated, events = await agent.execute(candidates, raw_seeds_map)
        dt = time.perf_counter() - t0
        for e in events:
            print(f"  [{e.status.upper():8s}] {e.message}")
        print()
        print_output(updated)
        qualified = [c.id for c in updated if c.passed_screening]
        summary = f"{len(qualified)}/{len(updated)} qualified after hazard scoring -> {qualified}"
        report.record(4, "Risk Agent", "success", dt, summary, raw_output=to_jsonable(updated))
        return updated
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Risk Agent: {err}")
        report.record(4, "Risk Agent", "error", dt, "Risk scoring failed.", error=err)
        return None


async def stage_route_graph(gateway, candidates):
    header("[5] Route / Graph Builder Agent")
    print(AGENT_INFO["Route / Graph Builder Agent"])
    if candidates is None:
        print("SKIPPED -- upstream Risk Agent did not produce candidates.")
        report.record(5, "Route / Graph Builder Agent", "skipped", 0.0, "Skipped: no candidates from Risk Agent.")
        return None
    agent = RouteGraphBuilderAgent(gateway)
    t0 = time.perf_counter()
    try:
        graph, events = await agent.execute(
            suppliers_raw=MOCK_REGION["suppliers"],
            candidates=candidates,
            customers_raw=MOCK_REGION["customers"],
            hazard_zones_raw=MOCK_REGION["hazard_zones"],
            region_name=MOCK_REGION["region_name"],
            bounding_box=MOCK_REGION["bounding_box"]
        )
        dt = time.perf_counter() - t0
        for e in events:
            print(f"  [{e.status.upper():8s}] {e.message}")
        print()
        print_output(graph)
        summary = (f"{len(graph.suppliers)} suppliers, {len(graph.warehouses)} warehouses, "
                   f"{len(graph.customers)} customers, {len(graph.edges)} weighted edges, "
                   f"{len(graph.hazards)} hazard polygons")
        report.record(5, "Route / Graph Builder Agent", "success", dt, summary, raw_output=to_jsonable(graph))
        return graph
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Route / Graph Builder Agent: {err}")
        report.record(5, "Route / Graph Builder Agent", "error", dt, "Graph construction failed.", error=err)
        return None


async def stage_optimization(graph):
    header("[6] Optimization Agent")
    print(AGENT_INFO["Optimization Agent"])
    if graph is None:
        print("SKIPPED -- upstream Route / Graph Builder Agent did not produce a graph.")
        report.record(6, "Optimization Agent", "skipped", 0.0, "Skipped: no graph from Route Agent.")
        return None, None
    agent = OptimizationAgent()
    t0 = time.perf_counter()
    try:
        frontier, best_sol, events = await agent.execute(graph, MOCK_INPUTS)
        dt = time.perf_counter() - t0
        for e in events:
            print(f"  [{e.status.upper():8s}] {e.message}")
        print(f"\nPareto frontier ({len(frontier)} solutions) -- showing best-balanced solution:")
        print_output(best_sol)
        summary = (f"{len(frontier)} Pareto solutions; best-balanced: cost=${best_sol.total_cost:,.0f}, "
                   f"resilience={best_sol.resilience_score}, warehouses={best_sol.selected_warehouse_ids}"
                   if best_sol else f"{len(frontier)} Pareto solutions; no feasible best-balanced solution found")
        report.record(6, "Optimization Agent", "success" if best_sol else "error", dt, summary,
                       raw_output={"frontier_count": len(frontier), "best_solution": to_jsonable(best_sol)})
        return frontier, best_sol
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Optimization Agent: {err}")
        report.record(6, "Optimization Agent", "error", dt, "MILP / Pareto sweep failed.", error=err)
        return None, None


async def stage_disaster(gateway, graph):
    header("[7] Disaster Simulation Agent")
    print(AGENT_INFO["Disaster Simulation Agent"])
    if graph is None:
        print("SKIPPED -- no graph available to simulate a disruption against.")
        report.record(7, "Disaster Simulation Agent", "skipped", 0.0, "Skipped: no graph.")
        return None
    agent = DisasterSimulationAgent(gateway)
    t0 = time.perf_counter()
    try:
        disruption, events = await agent.generate_scenario("flood_green_river", graph)
        dt = time.perf_counter() - t0
        for e in events:
            print(f"  [{e.status.upper():8s}] {e.message}")
        print()
        print_output(disruption)
        summary = (f"'{disruption.title}' -> {len(disruption.affected_warehouse_ids)} warehouses, "
                   f"{len(disruption.affected_edge_ids)} edges affected")
        report.record(7, "Disaster Simulation Agent", "success", dt, summary, raw_output=to_jsonable(disruption))
        return disruption
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Disaster Simulation Agent: {err}")
        report.record(7, "Disaster Simulation Agent", "error", dt, "Scenario generation failed.", error=err)
        return None


async def stage_recovery(gateway, graph, active_solution, disruption):
    header("[8] Recovery / Verification Agent")
    print(AGENT_INFO["Recovery / Verification Agent"])
    if graph is None or active_solution is None or disruption is None:
        print("SKIPPED -- missing graph, active solution, or disruption from an earlier stage.")
        report.record(8, "Recovery / Verification Agent", "skipped", 0.0, "Skipped: missing upstream inputs.")
        return None, None
    optimizer = OptimizationAgent()
    agent = RecoveryVerificationAgent(gateway, optimizer)
    t0 = time.perf_counter()
    try:
        recovered_sol, mutated_graph, elapsed_sec, events = await agent.execute_recovery(
            original_graph=graph, active_solution=active_solution, disruption=disruption
        )
        dt = time.perf_counter() - t0
        for e in events:
            print(f"  [{e.status.upper():8s}] {e.message}")
        print()
        print_output(recovered_sol)
        summary = (f"recovered in {elapsed_sec:.3f}s (internal timer); demand retained "
                   f"{recovered_sol.demand_retained_pct}%; resilience {recovered_sol.resilience_score}; "
                   f"sub-60s target met = {elapsed_sec < 60.0}")
        report.record(8, "Recovery / Verification Agent", "success", dt, summary,
                       raw_output=to_jsonable(recovered_sol))
        return recovered_sol, mutated_graph
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Recovery / Verification Agent: {err}")
        report.record(8, "Recovery / Verification Agent", "error", dt, "Recovery re-solve failed.", error=err)
        return None, None


async def stage_critic(candidates, graph, solution):
    header("[9] Critic Agent")
    print(AGENT_INFO["Critic Agent"])
    if candidates is None or graph is None or solution is None:
        print("SKIPPED -- missing candidates, graph, or solution from an earlier stage.")
        report.record(9, "Critic Agent", "skipped", 0.0, "Skipped: missing upstream inputs.")
        return None
    agent = CriticAgent()
    t0 = time.perf_counter()
    try:
        cr_report, events = agent.execute_audit(candidates, graph, solution, budget_limit_usd=MOCK_INPUTS.budget_limit_usd)
        dt = time.perf_counter() - t0
        for e in events:
            print(f"  [{e.status.upper():8s}] {e.message}")
        print()
        print_output(cr_report)
        summary = (f"passed={cr_report.passed}; evidence coverage={cr_report.evidence_coverage_pct}%; "
                   f"flags={len(cr_report.flags)}; constraint violations={len(cr_report.constraint_violations)}")
        report.record(9, "Critic Agent", "success", dt, summary, raw_output=to_jsonable(cr_report))
        return cr_report
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Critic Agent: {err}")
        report.record(9, "Critic Agent", "error", dt, "Audit failed.", error=err)
        return None


async def stage_narrator(candidates, graph, frontier, solution, disruption, critic_report):
    header("[10] Reporting / Narrator Agent")
    print(AGENT_INFO["Reporting / Narrator Agent"])
    if candidates is None or graph is None or solution is None:
        print("SKIPPED -- missing candidates, graph, or solution from an earlier stage.")
        report.record(10, "Reporting / Narrator Agent", "skipped", 0.0, "Skipped: missing upstream inputs.")
        return None
    agent = NarratorAgent()
    t0 = time.perf_counter()
    try:
        narrative, events = agent.generate_narrative(
            inputs_region=MOCK_REGION["region_name"],
            candidates=candidates, graph=graph, frontier=frontier or [solution],
            active_solution=solution, disruption=disruption, critic_report=critic_report
        )
        print("\n--- Executive Narrative ---")
        print(narrative)

        print("\n--- What-if Q&A demo ---")
        qa = await agent.answer_what_if(
            query="Why wasn't Cascade Foothills Steep Site selected?",
            candidates=candidates, graph=graph, frontier=frontier or [solution], active_solution=solution
        )
        print(qa["answer"])

        dt = time.perf_counter() - t0
        summary = f"narrative length={len(narrative)} chars; what-if Q&A answered={bool(qa.get('answer'))}"
        report.record(10, "Reporting / Narrator Agent", "success", dt, summary,
                       raw_output={"narrative": narrative, "what_if_answer": qa})
        return narrative
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Reporting / Narrator Agent: {err}")
        report.record(10, "Reporting / Narrator Agent", "error", dt, "Narrative generation failed.", error=err)
        return None


async def stage_controller(gateway):
    header("[1] Controller / Supervisor Agent (full LangGraph pipeline + disruption, capstone integration test)")
    print(AGENT_INFO["Controller / Supervisor Agent"])
    events_seen = []
    controller = ControllerAgent(gateway=gateway, event_callback=lambda e: events_seen.append(e))
    controller.raw_data = MOCK_REGION  # swap in the mock dataset instead of data/sample_region.json

    t0 = time.perf_counter()
    try:
        final_state = await controller.run_full_pipeline(inputs=MOCK_INPUTS)
        print(f"run_full_pipeline() completed -- {len(events_seen)} trace events emitted across the "
              f"compiled site->risk->route->optimize->critic->narrate graph.")

        disrupted_state = await controller.trigger_disruption(final_state, scenario_type="flood_green_river")
        print(f"trigger_disruption('flood_green_river') completed -- "
              f"{len(disrupted_state.get('disruption_log', []))} disruption(s) logged, "
              f"{len(disrupted_state.get('frontier', []))} solutions on frontier after recovery.")

        dt = time.perf_counter() - t0
        active_id = disrupted_state.get("active_solution_id")
        active_sol = next((s for s in disrupted_state.get("frontier", []) if s.solution_id == active_id), None)
        print("\n--- Final narrative after full pipeline + disruption ---")
        print(disrupted_state.get("narrative", "(none)"))

        summary = (f"full pipeline + disruption/recovery completed end-to-end; "
                   f"{len(events_seen)} trace events; final active solution cost="
                   f"${active_sol.total_cost:,.0f}" if active_sol else "full pipeline ran but no active solution found")
        report.record(1, "Controller / Supervisor Agent", "success", dt, summary,
                       raw_output={"trace_event_count": len(events_seen),
                                   "critic_flags": disrupted_state.get("critic_flags", [])})
        return disrupted_state
    except Exception as exc:
        dt = time.perf_counter() - t0
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        print(f"\n!! ERROR in Controller / Supervisor Agent: {err}")
        report.record(1, "Controller / Supervisor Agent", "error", dt, "Full pipeline run failed.", error=err)
        return None


# ======================================================================
# MAIN
# ======================================================================
async def main():
    print("#" * 90)
    print("# OptiFlow -- Live Agent-by-Agent Test Harness")
    print(f"# Run ID: {RUN_ID}")
    print("#" * 90)

    base_url = os.getenv("MIREYE_BASE_URL", "https://api.mireye.com")
    reachable, probe_msg = await probe_mireye_connectivity(base_url)
    # NOTE: the probe itself always "succeeds" as a diagnostic step (it ran and got an answer).
    # Whether the host is REACHABLE or UNREACHABLE is a network fact recorded in the summary text,
    # not a pipeline failure -- it must not affect the pass/fail exit code below.
    probe_summary = f"{'REACHABLE' if reachable else 'UNREACHABLE'} -- {probe_msg}"
    report.record(0, "Mireye API Connectivity Probe", "success", 0.0, probe_summary)
    pause()

    gateway = MireyeGatewayAgent()

    gateway = await stage_gateway(gateway)
    pause()

    candidates = await stage_site_generation(gateway)
    pause()

    candidates = await stage_risk(gateway, candidates)
    pause()

    graph = await stage_route_graph(gateway, candidates)
    pause()

    frontier, best_sol = await stage_optimization(graph)
    pause()

    disruption = await stage_disaster(gateway, graph)
    pause()

    recovered_sol, mutated_graph = await stage_recovery(gateway, graph, best_sol, disruption)
    pause()

    critic_report = await stage_critic(candidates, graph, best_sol)
    pause()

    # Feed the narrator the POST-RECOVERY solution/graph (when the Recovery stage produced one) so the
    # "Active Disruption & Recovery Impact" section reflects genuinely recovered numbers, matching how
    # ControllerAgent.trigger_disruption() wires it -- not the pre-disruption solution alongside a
    # disruption record, which would show mismatched before/after figures.
    narrator_solution = recovered_sol if recovered_sol is not None else best_sol
    narrator_graph = mutated_graph if mutated_graph is not None else graph
    await stage_narrator(candidates, narrator_graph, frontier, narrator_solution, disruption, critic_report)
    pause()

    # fresh gateway instance for the Controller's own internal agents so its
    # cache stats reflect only the full-pipeline run, not the manual calls above
    await stage_controller(MireyeGatewayAgent())

    # ------------------------------------------------------------------
    header("RUN COMPLETE -- Saving Report")
    json_path, txt_path = report.save()
    n_ok = sum(1 for e in report.entries if e["status"] == "success")
    n_err = sum(1 for e in report.entries if e["status"] == "error")
    n_skip = sum(1 for e in report.entries if e["status"] == "skipped")
    print(f"{n_ok} succeeded, {n_err} errored, {n_skip} skipped, out of {len(report.entries)} stages.")
    print(f"Full JSON report: {json_path}")
    print(f"Readable summary: {txt_path}")
    if LIVE_HTTP_LOG:
        print(f"\n{len(LIVE_HTTP_LOG)} real outbound HTTP call(s) were attempted against Mireye during this run:")
        for call in LIVE_HTTP_LOG:
            status = f"HTTP {call['status_code']}" if call["error"] is None else f"ERROR: {call['error']}"
            print(f"  - {call['url']} -> {status} ({call['latency_ms']} ms)")
    else:
        print("\nNo real outbound HTTP calls were attempted against Mireye during this run "
              "(no usable MIREYE_API_KEY was configured, so every Gateway call used the local "
              "simulation model -- set MIREYE_API_KEY / MIREYE_BASE_URL in a .env file to test live).")

    if n_err > 0:
        print(f"\n{n_err} stage(s) reported an error -- see the ERROR lines above and in {txt_path.name}.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())