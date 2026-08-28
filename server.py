#!/usr/bin/env python
"""
OptiFlow backend entrypoint.

Loads .env, then serves the FastAPI app defined in api/main.py.

    python server.py                 # serve on $HOST:$PORT (default 0.0.0.0:8000)
    python server.py --reload        # restart on source changes
    python server.py --port 9000     # override the port
    python server.py --check         # verify imports + dataset, then exit

`--check` is the quickest way to confirm the backend is sound before wiring a
frontend to it: it imports every agent, compiles the LangGraph workflow and
validates the region dataset without binding a socket.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

# Make `agents`, `api` and `schemas` importable no matter where this is run from.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load .env before anything reads os.getenv at import time.
load_dotenv(ROOT / ".env")

APP_IMPORT_STRING = "api.main:app"
DATASET_PATH = ROOT / "data" / "sample_region.json"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def run_checks() -> int:
    """Import the whole stack and validate the dataset. Returns a process exit code."""
    failures: list[str] = []

    def ok(label: str, detail: str = "") -> None:
        print(f"  [ok]   {label}{f' - {detail}' if detail else ''}")

    def bad(label: str, detail: str) -> None:
        failures.append(f"{label}: {detail}")
        print(f"  [FAIL] {label} - {detail}")

    print("\nOptiFlow backend check\n" + "-" * 60)

    print("\nDependencies")
    for mod, label in [
        ("fastapi", "FastAPI"),
        ("uvicorn", "Uvicorn"),
        ("pydantic", "Pydantic"),
        ("langgraph", "LangGraph"),
        ("ortools", "OR-Tools"),
        ("numpy", "NumPy"),
        ("httpx", "httpx"),
    ]:
        try:
            m = __import__(mod)
            ok(label, getattr(m, "__version__", ""))
        except Exception as exc:  # noqa: BLE001 - report, do not raise
            bad(label, str(exc))

    print("\nRegion dataset")
    if not DATASET_PATH.exists():
        bad("data/sample_region.json", "file not found")
    else:
        try:
            data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
            for key in ("suppliers", "candidate_warehouses", "customers", "hazard_zones"):
                rows = data.get(key)
                if not isinstance(rows, list) or not rows:
                    bad(f"dataset.{key}", "missing or empty")
                else:
                    ok(f"dataset.{key}", f"{len(rows)} records")
            region = data.get("region_name")
            ok("dataset.region_name", str(region)) if region else bad(
                "dataset.region_name", "missing"
            )
        except Exception as exc:  # noqa: BLE001
            bad("data/sample_region.json", f"unreadable: {exc}")

    print("\nAgents and workflow")
    try:
        from agents.controller_agent import ControllerAgent
        from agents.mireye_gateway_agent import MireyeGatewayAgent

        gateway = MireyeGatewayAgent()
        controller = ControllerAgent(gateway=gateway)
        ok("ControllerAgent", "10-agent LangGraph workflow compiled")
        ok("Region dataset loaded", controller.raw_data.get("region_name", "unknown"))
    except Exception as exc:  # noqa: BLE001
        bad("ControllerAgent", str(exc))

    print("\nAPI surface")
    try:
        from api.main import app

        routes = []
        for route in app.routes:
            path = getattr(route, "path", None)
            if not path or not (path.startswith("/api") or path.startswith("/ws")):
                continue
            methods = ",".join(sorted(getattr(route, "methods", {"WS"}) - {"HEAD", "OPTIONS"}))
            routes.append(f"{methods or 'WS'} {path}")
        for r in sorted(routes):
            ok(r)
        if not routes:
            bad("api.main:app", "no /api or /ws routes registered")
    except Exception as exc:  # noqa: BLE001
        bad("api.main:app", str(exc))

    print("\nConfiguration")
    ok("MIREYE_API_KEY", "set" if os.getenv("MIREYE_API_KEY") else "not set (gateway simulates)")
    ok("REDIS_HOST", os.getenv("REDIS_HOST") or "not set (in-memory cache)")
    ok("CORS_ORIGINS", os.getenv("CORS_ORIGINS") or "* (all origins)")

    print("-" * 60)
    if failures:
        print(f"\n{len(failures)} check(s) failed:\n")
        for f in failures:
            print(f"  - {f}")
        print()
        return 1

    print("\nAll checks passed. Start the server with:  python server.py\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="server.py",
        description="Run the OptiFlow FastAPI backend.",
    )
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument(
        "--reload",
        action="store_true",
        default=_env_flag("RELOAD"),
        help="restart the server when source files change",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "info"),
        choices=["critical", "error", "warning", "info", "debug", "trace"],
    )
    parser.add_argument(
        "--quiet-api",
        action="store_true",
        help="log only failed Mireye calls, not every successful one",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify imports, dataset and routes, then exit without serving",
    )
    args = parser.parse_args()

    if args.check:
        return run_checks()

    import uvicorn

    # Route our own loggers to the terminal alongside uvicorn's access log.
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s %(name)-18s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # The per-call Mireye log is verbose; keep it unless the user asked for quiet.
    logging.getLogger("optiflow.mireye").setLevel(
        logging.WARNING if args.quiet_api else logging.INFO
    )
    # httpx logs every request too; ours already says the same thing with context.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    shown_host = "localhost" if args.host in {"0.0.0.0", "127.0.0.1"} else args.host
    base = f"http://{shown_host}:{args.port}"

    from agents.mireye_gateway_agent import MireyeGatewayAgent as _G
    _probe = _G()
    key_state = "set" if _probe.data_source_summary()["api_key_configured"] else "NOT set"
    rate_cap = _probe.limiter.per_minute
    timeout = int(_probe.request_timeout)
    strict = "on" if _probe.strict_live else "off"
    strict_effect = "raises" if _probe.strict_live else "falls back to simulated values"

    print(f"""
  OptiFlow API
  ------------------------------------------------------------
  Health      {base}/api/health
  State       {base}/api/state
  Docs        {base}/docs
  Trace WS    ws://{shown_host}:{args.port}/ws/trace

  A baseline optimisation is dispatched on startup; give it a few
  seconds before /api/state reports a frontier.
  Frontend:   cd frontend && npm run dev   ->  http://localhost:5173

  Live data   MIREYE_API_KEY {key_state}
  Rate cap    {rate_cap} calls/min   Timeout {timeout}s
  Strict      {strict} (a failed call {strict_effect})
  ------------------------------------------------------------
""")

    uvicorn.run(
        APP_IMPORT_STRING,
        host=args.host,
        port=args.port,
        reload=args.reload,
        # Watching node_modules would make reload unusably slow.
        reload_dirs=[str(ROOT / "api"), str(ROOT / "agents"), str(ROOT / "schemas")]
        if args.reload
        else None,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
