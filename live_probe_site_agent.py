"""
live_probe_site_agent.py

Standalone, test-only probe for:
    SiteGenerationAgent -> MireyeGatewayAgent -> REAL Mireye HTTP API

Run this from the OptiFlow project root, inside a venv, with MIREYE_API_KEY
(and MIREYE_BASE_URL if needed) already set in the environment.

This script makes NO changes to agents/site_agent.py or
agents/mireye_gateway_agent.py. The only instrumentation is a runtime wrapper
placed on the *instance* of MireyeGatewayAgent (not the class, not the file),
around _request_live, so we can prove — per call — whether a real HTTP
response came back or the gateway silently fell through to its local
simulator. Nothing about business logic or thresholds is touched.

It never prints the API key.
"""
import os
import sys
import json
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# 1. Hard gate: refuse to run a "test" that would silently be mock-mode.
# ---------------------------------------------------------------------------
raw_key = os.getenv("MIREYE_API_KEY", "")
if not raw_key or raw_key.lower().startswith("mock"):
    print(
        "\n[BLOCKED] MIREYE_API_KEY is not set to a real value in this shell.\n"
        "This script refuses to run, because SiteGenerationAgent would 'succeed'\n"
        "using the local simulator and that is NOT a real-API test.\n\n"
        "Fix:\n"
        "  PowerShell:  $env:MIREYE_API_KEY = \"<your real key>\"\n"
        "  cmd.exe:     set MIREYE_API_KEY=<your real key>\n"
        "  bash:        export MIREYE_API_KEY=\"<your real key>\"\n\n"
        "Optionally also set MIREYE_BASE_URL if your account uses a non-default host, e.g.\n"
        "  $env:MIREYE_BASE_URL = \"https://api.mireye.ai/v1\"\n",
        file=sys.stderr,
    )
    sys.exit(1)

from agents.mireye_gateway_agent import MireyeGatewayAgent, DEMO_SITES  # noqa: E402
from agents.site_agent import SiteGenerationAgent  # noqa: E402


async def main() -> int:
    gateway = MireyeGatewayAgent()

    print(f"[config] base_url = {gateway.base_url}")
    print(f"[config] live mode active = {gateway._is_live_mode()}")
    if not gateway._is_live_mode():
        print(
            "[BLOCKED] Gateway reports live mode is OFF even though a key is set "
            "(key may start with 'mock', or be empty after parsing).",
            file=sys.stderr,
        )
        return 1

    # ------------------------------------------------------------------
    # 2. Instance-level (NOT class/file-level) wrap of _request_live so we
    #    get hard evidence of live-vs-fallback per Mireye call.
    # ------------------------------------------------------------------
    call_evidence = []
    _orig_request_live = gateway._request_live

    async def _instrumented_request_live(canonical_endpoint, params, method="GET", json_body=None):
        result = await _orig_request_live(canonical_endpoint, params, method=method, json_body=json_body)
        call_evidence.append({
            "endpoint": canonical_endpoint,
            "url": gateway._build_url(canonical_endpoint),
            "method": method,
            "live_http_response_received": result is not None,
            "response_keys": sorted(result.keys()) if isinstance(result, dict) else None,
        })
        return result

    gateway._request_live = _instrumented_request_live

    # ------------------------------------------------------------------
    # 3. Real SiteGenerationAgent, real gateway. One realistic seed from the
    #    project's own DEMO_SITES catalogue (Kent Valley — an existing
    #    industrial-zoned pilot region site).
    # ------------------------------------------------------------------
    site = DEMO_SITES["kent-valley"]
    seed = {
        "id": "LIVE-PROBE-1",
        "name": "Kent Valley Live Probe",
        "lat": site["lat"],
        "lon": site["lon"],
        "base_capacity": 20_000.0,
        "fixed_cost": 130_000.0,
    }

    agent = SiteGenerationAgent(gateway)
    state = {}  # NetworkState is a TypedDict; SiteGenerationAgent reads nothing from it

    print(f"\n[run] SiteGenerationAgent.execute() with seed: {seed}\n")
    candidates, events = await agent.execute(state, [seed])

    # ------------------------------------------------------------------
    # 4. Report — separates API integration success from site-suitability
    #    result, exactly per the required distinction.
    # ------------------------------------------------------------------
    print("\n" + "=" * 78)
    print("MIREYE CALL EVIDENCE")
    print("=" * 78)
    any_fallback = False
    for ev in call_evidence:
        status = "LIVE RESPONSE" if ev["live_http_response_received"] else "FELL BACK TO SIMULATOR"
        if not ev["live_http_response_received"]:
            any_fallback = True
        print(f"  endpoint={ev['endpoint']}  method={ev['method']}")
        print(f"    url={ev['url']}")
        print(f"    result={status}")
        if ev["response_keys"]:
            print(f"    live_response_fields={ev['response_keys']}")
        print()

    print("=" * 78)
    print("SITE GENERATION OUTPUT")
    print("=" * 78)
    screened = [e for e in events if e.action == "CandidateScreened"]
    for c, ev in zip(candidates, screened):
        print(f"  id={c.id}  name={c.name}  lat={c.lat}  lon={c.lon}")
        print(f"  slope_pct={c.terrain_slope_pct}  elevation_m={c.elevation_m}  "
              f"land_cover={c.land_cover}  parcel_sqm={c.parcel_area_sqm}  is_occupied={c.is_occupied}")
        print(f"  passed_screening={c.passed_screening}")
        print(f"  rejection_reasons={c.rejection_reasons}")
        print(f"  confidence_score={ev.details.get('confidence_score')}")
        print(f"  upstream_degraded={ev.details.get('upstream_degraded')}")
        print(f"  provenance_endpoints={ {k: v.endpoint for k, v in c.provenance.items()} }")
        print(f"  provenance_cached={ {k: v.cached for k, v in c.provenance.items()} }")
        print(f"  reasoning: {ev.details.get('reasoning')}")

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    if any_fallback:
        print("LIVE API TEST: FAILED / SIMULATOR FALLBACK USED")
        print("  -> At least one Mireye call did not receive a real HTTP response.")
        print("  -> Check the WARNING/ERROR log lines above from 'agents.mireye_gateway_agent'")
        print("     for the exact HTTP status or exception per attempt.")
    else:
        print(f"LIVE API TEST: PASS — {len(call_evidence)}/{len(call_evidence)} Mireye calls returned real HTTP responses.")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
