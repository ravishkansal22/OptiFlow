# OPTIFLOW: Agentic Logistics Network Intelligence
### Resilient Supply Chain Design Powered by Mireye

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-StateGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![OR-Tools](https://img.shields.io/badge/Google%20OR--Tools-MILP-blue.svg)](https://developers.google.com/optimization)
[![React 18](https://img.shields.io/badge/React-18-61DAFB.svg)](https://reactjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🌟 Executive Summary

**OptiFlow** is an agentic logistics network intelligence platform combining geospatial AI, multi-objective optimization, and real-time disaster resilience. Built around a **10-agent LangGraph architecture**, OptiFlow ensures that **Mireye is visible, not just used**: every stage of the supply chain design pipeline—facility siting, multi-hazard scoring, logistics graph construction, disruption simulation, and sub-60-second recovery—routes through a centralized, cached, and provenance-tagged **Mireye Gateway Agent**.

Every metric on screen can be traced directly to an audited Mireye endpoint, parameter set, and server timestamp.

---

## 🏗️ 10-Agent Architecture

The system operates as a state machine passing a single shared `NetworkState` typed contract between specialized agents:

```
                      +------------------------------------------+
                      |    1. Controller / Supervisor Agent      |
                      +--------------------+---------------------+
                                           |
                    +----------------------+----------------------+
                    |                      |                      |
     +--------------v-------------+        |        +-------------v--------------+
     | 3. Site Generation Agent   |        |        | 7. Disaster Simulation     |
     +--------------+-------------+        |        +-------------+--------------+
                    |                      |                      |
     +--------------v-------------+        |        +-------------v--------------+
     |      4. Risk Agent         |        |        | 8. Recovery / Verification |
     +--------------+-------------+        |        +-------------+--------------+
                    |                      |                      |
     +--------------v-------------+        |        +-------------+--------------+
     | 5. Route / Graph Builder   |        |                      |
     +--------------+-------------+        |                      |
                    |                      |                      |
     +--------------v-------------+        |                      |
     |    6. Optimization Agent   |<-------+----------------------+
     |      (MILP + NSGA-II)      |
     +--------------+-------------+
                    |
     +--------------v-------------+
     |      9. Critic Agent       |
     +--------------+-------------+
                    |
     +--------------v-------------+
     | 10. Reporting / Narrator   |
     +----------------------------+
                    ^
                    | (ALL Geospatial Calls Route Exclusively Through)
     +--------------+-------------+
     |  2. Mireye Gateway Agent   | (Redis / In-Memory Cache, Geohash-7, Provenance Tagging)
     +----------------------------+
```

### Agent Roster & Ownership:
1. **Controller / Supervisor Agent (`agents/controller_agent.py`)**: Orchestrates the LangGraph state machine, sequences downstream agents, manages run state, and handles async dispatch.
2. **Mireye Gateway Agent (`agents/mireye_gateway_agent.py`)**: Owns **ALL** Mireye traffic. Implements request logging, Redis/Memory caching (`key = layer:geohash-7:radius`), exponential backoff retries, and attaches immutable `ProvenanceTag` metadata to 100% of returned values.
3. **Site Generation Agent (`agents/site_agent.py`)**: Clusters customer demand density and screens candidate warehouse parcels against Mireye terrain slope (<8%), elevation (<250m), land cover, and zoning.
4. **Risk Agent (`agents/risk_agent.py`)**: Evaluates Mireye flood exposure (Zone AE, 100-year probability) and historical hazards on surviving candidates, computing a normalized $0-1$ risk score with rejection tracking.
5. **Route / Graph Builder Agent (`agents/route_agent.py`)**: Batches origin-destination queries via Mireye routing to construct the weighted multimodal logistics graph with real road distances, transit times, fuel/driver costs, and hazard weights.
6. **Optimization Agent (`agents/optimization_agent.py`)**: Solves facility location and commodity flow using Google OR-Tools MILP for a least-cost baseline, then executes an NSGA-II sweep to generate a 20–50 point Cost-vs-Resilience Pareto Frontier.
7. **Disaster Simulation Agent (`agents/disaster_agent.py`)**: Uses Mireye flood polygons and road closure data to generate geographically grounded disruption scenarios.
8. **Recovery / Verification Agent (`agents/recovery_agent.py`)**: Warm-starts re-optimization upon disruption, querying Mireye only for delta changes, guaranteeing **sub-60-second recovery**.
9. **Critic Agent (`agents/critic_agent.py`)**: Audits the entire state for fresh, non-stale Mireye provenance and ensures capacity, budget, and SLA delivery constraints are satisfied.
10. **Reporting / Narrator Agent (`agents/narrator_agent.py`)**: Natural language synthesizer and interactive AI assistant explaining trade-offs and answering free-form "what-if" inquiries.

---

## 📐 Mathematical Foundations

### 1. Resilience Score Formula
$$\text{Resilience} = 0.6 \times \left(\frac{\text{Demand Retained \%}}{100}\right) + 0.4 \times (1 - \text{Normalized Recovery Cost})$$
- **Demand Retained**: Percentage of customer demand fulfilled within SLA transit time limits.
- **Normalized Recovery Cost**: Ratio of additional detour/freight reassignment expense relative to base network operations.

### 2. Multi-Objective Pareto Optimization
$$\min \left[ f_1(\mathbf{x}), -f_2(\mathbf{x}) \right]$$
- $f_1(\mathbf{x}) = \sum_j \text{FixedCost}_j \cdot y_j + \sum_{k,j} c_{kj} z_{kj} + \sum_{i,j} d_i c_{ji} x_{ij}$ (Total Financial Outlay)
- $f_2(\mathbf{x}) = \text{Resilience}(\mathbf{x})$ (Resilience Index)

---

## 🚀 Quickstart Guide

### Prerequisites
- Python 3.10+
- Node.js 18+ & npm 9+
- Docker & Docker Compose (Optional)

### Option 1: Local Development Setup

#### 1. Backend API & Multi-Agent Engine
```bash
# Clone repository
cd OptiFlow

# Install Python dependencies
pip install -r requirements.txt

# Start the backend
python server.py

# Verify imports, dataset and routes without serving
python server.py --check
```
API Documentation will be live at: [http://localhost:8000/docs](http://localhost:8000/docs)

**Is the data real?**

Every value carries a `live` flag and a `source` (`live`, `cache`, `cache-simulation`,
`simulation`). A value is only `live` when the Mireye API answered successfully; anything else
came from the local simulation model, which substitutes fixed defaults. `GET /api/data-source`
reports the running tally, the dashboard shows it in the header and on a banner, and
`POST /api/reset` clears every cached value, the call log and the network state.

Two things silently degrade data quality, both now handled:

- **Timeouts.** A first lookup for a cold coordinate can take over 10 seconds, then sub-second
  once warm. The old 10s ceiling turned that into a silent fallback. `MIREYE_TIMEOUT` now
  defaults to 30s with one retry.
- **Coverage.** Mireye v1 supports **US coordinates only**. Anything else returns
  `coord_out_of_bounds` and cannot be evaluated with real data. Both coordinate entry points
  check this before dispatching and offer a one-click repair for the most common cause: a
  dropped minus sign on longitude, since every US longitude is negative.

**Strict mode is on by default when a key is set.** A failed terrain, land-cover or flood
lookup raises rather than substituting simulated values, so a site verdict never rests on
fabricated data. Routing legs the API cannot drive (`flag: unreachable_or_snapped`) are counted
and tagged as non-live but do not abort a run. Set `MIREYE_STRICT_LIVE=0` to allow the fallback.

**Outbound calls are capped** by a token bucket at `MIREYE_MAX_CALLS_PER_MIN` (default 250,
against Mireye's 300/min). Calls are issued sequentially, so a cold full run measures ~50/min;
the cap protects against concurrent requests rather than the steady state.

**The backend logs to the terminal.** Each run prints `PIPELINE START`/`DONE` with the call
tally and rate, every agent milestone, and each failed or simulated lookup. `--quiet-api`
suppresses the per-call success lines.

**Evaluating your own coordinates**

`POST /api/evaluate-sites` screens a list of locations and ranks them, without touching the
global network state:

```bash
curl -X POST http://localhost:8000/api/evaluate-sites   -H "Content-Type: application/json"   -d '{"sites":[{"name":"Kent Valley","lat":47.4124,"lon":-122.2415,"capacity_units":25000}]}'
```

Each site comes back with `passed`, any `rejection_reasons`, the measured terrain/parcel/hazard
values, a `suitability_score` with its components, and a `rank` among the sites that passed.
`POST /api/run` also accepts a `custom_sites` array, which replaces the region dataset's
candidate warehouses for that run (customers, suppliers and hazards still come from the dataset).

#### 2. Frontend Interactive Dashboard
```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start Vite Dev Server
npm run dev
```
Dashboard will be live at: [http://localhost:5173](http://localhost:5173)

The dev server proxies `/api` and `/ws` to the backend on port `8000`, so the app runs
same-origin and needs no CORS configuration. Point it elsewhere with either
`VITE_PROXY_TARGET` (proxy destination) or `VITE_API_URL` (bypass the proxy entirely).
The nginx image used by Docker Compose forwards the same two paths to the `api` service.

**Using the app**

The frontend is one guided workflow, not a set of dashboard pages:

    SETUP -> ANALYZE -> CANDIDATES -> OPTIMIZE -> STRESS TEST -> RECOVERY -> INSIGHTS

A rail across the top shows where you are; a step opens only once the backend holds what that
screen needs, and the app moves forward on its own as each phase finishes.

0. The **landing page** leads with one action, *Create New Network*. If the server already holds
   a network it appears above, with the stage it reached, and one click resumes there.
1. **Setup** asks three things on one page: where the network goes (with a live map preview of
   the loaded region from `GET /api/region`), what it has to achieve (delivery time, minimum
   demand coverage, budget, and whether to favour cost, balance or resilience), and what it is
   built from. Warehouse candidates, suppliers and demand zones can each come from the loaded
   region or from your own upload. The facility cap sits under *Advanced configuration*.
2. **Analyze** posts to `POST /api/analyze`, which runs the geospatial half of the pipeline —
   Site Generation, Risk and the Route/Graph build. Progress streams over `/ws/trace`: a
   checklist per agent, a live activity panel showing the newest report from each one, and the
   raw event log. The agents emit as they work, so a long route matrix reports its progress
   rather than going quiet.
3. **Candidates** is map-first: every screened site on the map, a ranked sidebar beside it, and
   a *Why this site?* panel behind any card — terrain, flood risk, infrastructure, measured
   accessibility, rejection reasons, and the Mireye evidence behind each value. The full
   screening table is one disclosure away.
4. **Optimize** runs `POST /api/optimize` (MILP + NSGA-II + critic + narrator) and is the main
   dashboard: the network on the map, the five headline metrics, and the Pareto frontier below
   it. Clicking a point calls `POST /api/switch-solution` and repaints the map, the metrics and
   the facility list against that design.
5. **Stress test** reads its scenario cards from `GET /api/scenarios`, which is built from the
   live graph — so a flood only offers hazard zones this network actually has. *Auto stress
   test* lets the Disaster agent choose based on where the network is most exposed, and says
   why. `POST /api/disrupt` applies the scenario and measures the damage; recovery is a separate
   step, so the impact is visible before anything is repaired.
6. **Recovery** runs `POST /api/recover`: the warm-started delta re-solve, re-audited by the
   critic and re-narrated. The result is shown against the disrupted network and against the
   healthy one, with recovery time, zones recovered, routes changed and facilities moved.
   `POST /api/restore` puts the network back so another scenario can run from the same start.
7. **Insights** carries the recommendation, its comparison against the cost-only baseline, the
   critic's verification checks inline (a failed check reads as a CRITIC FLAG), the narrator's
   explanation, a downloadable report and the What-If assistant.

**Screen individual sites** takes your own coordinates — uploaded as a file, pasted, or typed —
screens each one through `POST /api/evaluate-sites`, and ranks the ones that pass. From there
those sites can be carried straight into a run in place of the dataset's candidates.

   File upload accepts CSV, TSV, plain text and JSON. Column names are matched case-insensitively
   from `lat`/`latitude`/`y`, `lon`/`lng`/`long`/`longitude`/`x`, and optionally `name`,
   `capacity` and `cost`. Files without a header row fall back to positional parsing
   (`lat, lon` / `name, lat, lon` / `name, lat, lon, capacity, cost`). A file with a mislabelled
   extension still reads correctly, because the format is detected from the content.
**Ask** posts to `/api/ask` and answers what-if questions against the network on screen, not
from general knowledge. Light theme is the default; the moon icon switches to dark and the
choice persists.

If a run finishes without a feasible plan, the Optimize step shows why — the binding
constraint, the figures behind it, and a route back to the requirements — instead of an error.

Nothing in the UI is seeded with placeholder data — if the backend returns nothing, the panels
say so rather than showing sample content.

---

### Option 2: Docker Compose (One-Click)

```bash
docker-compose up --build
```
This launches:
- **Redis Cache**: Port `6379`
- **OptiFlow API**: Port `8000`
- **OptiFlow Frontend**: Port `5173`

---

## 🧪 Automated Test Suite

Run the full verification test suite:
```bash
python -m pytest tests/ -v
```

### Test Coverage:
- `tests/test_schemas.py`: Verifies Pydantic v2 serialization and typed contracts.
- `tests/test_mireye_gateway.py`: Validates geohash-7 caching, SHA-256 response hashing, and provenance tags.
- `tests/test_optimization.py`: Validates OR-Tools MILP and Pareto frontier generation.
- `tests/test_pipeline_end_to_end.py`: Executes the complete 10-Agent LangGraph workflow.
- `tests/test_disruption_recovery.py`: Validates sub-60s disaster recovery and demand retention.

---

## 📡 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Healthcheck, cache counts, and active WebSocket connections |
| `GET` | `/api/state` | Full master `NetworkState`, plus the workflow `stage` and `can_restore` |
| `GET` | `/api/region` | The loaded region: bounds, suppliers, demand zones, hazards, candidate sites |
| `POST` | `/api/run` | Runs the whole 10-agent workflow in one call |
| `POST` | `/api/analyze` | Phase one only: Site Generation, Risk and the Route/Graph build |
| `POST` | `/api/optimize` | Phase two only: MILP + NSGA-II, the critic audit and the narrator report |
| `GET` | `/api/scenarios` | Disruption scenarios available for the current network, with their options |
| `POST` | `/api/disrupt` | Applies a scenario and measures the impact (`auto_recover` to repair in the same call) |
| `POST` | `/api/recover` | Warm-started delta re-solve against the latest disruption |
| `POST` | `/api/restore` | Restores the pre-disruption network so another scenario can run |
| `POST` | `/api/evaluate-sites` | Screens and ranks user-supplied coordinates without touching state |
| `POST` | `/api/switch-solution` | Activates a specific solution from the Pareto frontier |
| `POST` | `/api/ask` | Free-form what-if Q&A powered by the Narrator Agent |
| `GET` | `/api/data-source` | How much of the data served so far came from the API rather than simulation |
| `POST` | `/api/reset` | Clears every cached value, the call log and the network state |
| `GET` | `/api/provenance-trace` | Full audit log of all Mireye queries and response hashes |
| `WS` | `/ws/trace` | Real-time WebSocket stream of live agent execution events |

`/ws/trace` also carries the control signals the UI advances on: `analysis_complete`,
`pipeline_complete`, `disruption_applied`, `disruption_resolved`, `network_restored`,
`solution_switched`, `state_reset` and `pipeline_error`.

`POST /api/run` and `POST /api/analyze` accept `optimization_preference`
(`cost` | `balanced` | `resilience`), `min_demand_coverage_pct`, and `custom_sites`,
`custom_suppliers` and `custom_customers` arrays, each replacing the matching part of the
region dataset for that run. Set `OPTIFLOW_BASELINE_ON_STARTUP=0` to boot without dispatching
the baseline run.

---

## 🗺️ Seeded Pilot Region: Puget Sound Logistics Corridor

Included in `data/sample_region.json`:
- **5 Major Suppliers**: Port of Tacoma, Port of Seattle Terminal 18, SeaTac Air Cargo, BNSF Kent Freight Hub, Everett Northern Gateway.
- **20 Candidate Logistics Sites**: Varying terrain slopes ($0.2\% - 14.8\%$), elevations ($2\text{m} - 310\text{m}$), and flood risk zones.
- **33 Customer Delivery Zones**: High-priority medical precincts, tech campuses, and downtown urban centers with strict SLA windows.
- **Mireye Inundation Polygons**: Green River Valley 100-Year Flood Basin, Puyallup Tidal Confluence, and Duwamish Storm Surge corridors.

---

## 👥 Authors
- **Shivam Goel**
- **Ravish Kansal**
- **Maulik Chugh**
