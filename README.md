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

# Start FastAPI Backend (with live reload)
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```
API Documentation will be live at: [http://localhost:8000/docs](http://localhost:8000/docs)

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
| `GET` | `/api/state` | Returns full master `NetworkState` |
| `POST` | `/api/run` | Triggers 10-Agent LangGraph optimization workflow |
| `POST` | `/api/disrupt` | Triggers disaster simulation and warm-started recovery |
| `POST` | `/api/switch-solution` | Activates a specific solution from the Pareto frontier |
| `POST` | `/api/ask` | Free-form what-if Q&A powered by the Narrator Agent |
| `GET` | `/api/provenance-trace` | Full audit log of all Mireye queries and response hashes |
| `WS` | `/ws/trace` | Real-time WebSocket stream of live agent execution events |

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
