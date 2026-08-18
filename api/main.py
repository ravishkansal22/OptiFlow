import asyncio
import os
from typing import Dict, Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from schemas.state import (
    NetworkState,
    InputSpec,
    AgentTraceEvent,
    NetworkSolution
)
from schemas.mireye import ProvenanceTag
from agents.controller_agent import ControllerAgent
from agents.mireye_gateway_agent import MireyeGatewayAgent
from api.ws import ws_manager

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
global_state: NetworkState = {
    "inputs": InputSpec(),
    "mireye_cache": {},
    "candidates": [],
    "graph": None,
    "frontier": [],
    "active_solution_id": "",
    "disruption_log": [],
    "critic_flags": [],
    "critic_report": None,
    "narrative": "",
    "trace_events": []
}


def trace_broadcaster(event: AgentTraceEvent):
    """Callback to broadcast agent trace events to connected frontend clients."""
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


class RunRequest(BaseModel):
    region_name: Optional[str] = "Puget Sound Logistics Corridor"
    target_warehouses: Optional[int] = 4
    service_radius_minutes: Optional[float] = 60.0
    budget_limit_usd: Optional[float] = 2500000.0


class DisruptionRequest(BaseModel):
    scenario_type: str = "flood_green_river"  # "flood_green_river", "road_closure_corridor", "surge_demand"


class SwitchSolutionRequest(BaseModel):
    solution_id: str


class AskNarratorRequest(BaseModel):
    query: str


@app.on_event("startup")
async def startup_event():
    """Initializes the baseline run on startup."""
    asyncio.create_task(_run_pipeline_task(InputSpec()))


async def _run_pipeline_task(spec: InputSpec):
    global global_state
    try:
        final_state = await controller.run_full_pipeline(spec)
        global_state.update(final_state)
        await ws_manager.broadcast({
            "type": "pipeline_complete",
            "active_solution_id": global_state.get("active_solution_id")
        })
    except Exception as e:
        await ws_manager.broadcast({
            "type": "pipeline_error",
            "error": str(e)
        })


@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "service": "OptiFlow Logistics Intelligence",
        "mireye_cache_count": len(mireye_gateway.memory_cache),
        "active_ws_clients": len(ws_manager.active_connections)
    }


@app.get("/api/state")
async def get_state():
    """Returns the full master network state."""
    return {
        "inputs": global_state.get("inputs").model_dump() if hasattr(global_state.get("inputs"), "model_dump") else global_state.get("inputs"),
        "candidates": [c.model_dump() for c in global_state.get("candidates", [])],
        "graph": global_state.get("graph").model_dump() if global_state.get("graph") else None,
        "frontier": [s.model_dump() for s in global_state.get("frontier", [])],
        "active_solution_id": global_state.get("active_solution_id"),
        "disruption_log": [d.model_dump() for d in global_state.get("disruption_log", [])],
        "critic_flags": global_state.get("critic_flags", []),
        "critic_report": global_state.get("critic_report").model_dump() if global_state.get("critic_report") else None,
        "narrative": global_state.get("narrative", ""),
        "trace_events": [t.model_dump() for t in global_state.get("trace_events", [])]
    }


@app.post("/api/run")
async def run_pipeline(req: RunRequest, background_tasks: BackgroundTasks):
    """Triggers the full 10-Agent LangGraph optimization workflow."""
    spec = InputSpec(
        region_name=req.region_name or "Puget Sound Logistics Corridor",
        target_warehouses_to_open=req.target_warehouses or 4,
        service_radius_minutes=req.service_radius_minutes or 60.0,
        budget_limit_usd=req.budget_limit_usd or 2500000.0
    )
    background_tasks.add_task(_run_pipeline_task, spec)
    return {"message": "OptiFlow multi-agent optimization pipeline dispatched in background."}


@app.post("/api/disrupt")
async def trigger_disruption(req: DisruptionRequest):
    """Triggers a disaster disruption scenario and runs warm-started sub-60s recovery."""
    global global_state
    if not global_state.get("graph"):
        raise HTTPException(status_code=400, detail="Initial network optimization not yet executed.")
    
    updated_state = await controller.trigger_disruption(global_state, req.scenario_type)
    global_state.update(updated_state)
    
    await ws_manager.broadcast({
        "type": "disruption_resolved",
        "active_solution_id": global_state.get("active_solution_id")
    })
    
    return {
        "message": f"Disruption '{req.scenario_type}' simulated and recovered successfully.",
        "active_solution_id": global_state.get("active_solution_id")
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
