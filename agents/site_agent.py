import uuid
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

from schemas.state import NetworkState, Candidate, InputSpec, AgentTraceEvent
from schemas.mireye import ProvenanceTag
from agents.mireye_gateway_agent import MireyeGatewayAgent

logger = logging.getLogger(__name__)


@dataclass
class SiteConfig:
    """
    All tuneable thresholds for site screening in one place.
    Pass a custom SiteConfig to SiteGenerationAgent to override defaults
    without touching source code.
    """
    # Physical buildability limits
    max_slope_pct: float = 8.0          # slopes above this reject the site
    max_elevation_m: float = 250.0      # sites above this elevation are too remote for freight
    min_parcel_sqm: float = 25_000.0    # minimum usable parcel for a warehouse footprint

    # Proximity / query parameters
    land_cover_radius_m: float = 500.0  # radius passed to Mireye land-cover query

    # Confidence band widths — when a value is within this fraction of the threshold,
    # we flag a "marginal" confidence penalty (0 = penalise nothing, 1 = always penalise).
    slope_marginal_band_pct: float = 0.15   # e.g. slope within 15% of max → reduced confidence
    elev_marginal_band_pct: float = 0.10
    parcel_marginal_band_pct: float = 0.20

    # Default field values when a seed dict is missing a key
    default_lat: float = 47.50
    default_lon: float = -122.25
    default_capacity: float = 20_000.0
    default_fixed_cost: float = 130_000.0


# Latitude / longitude sanity bounds (contiguous US + Alaska/Hawaii buffer)
_LAT_BOUNDS = (-90.0, 90.0)
_LON_BOUNDS = (-180.0, 180.0)


def _validate_seed(seed: Dict[str, Any], config: SiteConfig) -> Tuple[float, float, List[str]]:
    """
    Extract and validate lat/lon from a seed dict.

    Returns (lat, lon, warnings_list).  warnings_list is non-empty when values
    were out-of-range or missing and a default was substituted.
    """
    warnings: List[str] = []

    raw_lat = seed.get("lat")
    raw_lon = seed.get("lon")

    if raw_lat is None or raw_lon is None:
        warnings.append(
            f"Seed '{seed.get('id', '?')}' missing lat/lon — using default "
            f"({config.default_lat}, {config.default_lon})."
        )
        return config.default_lat, config.default_lon, warnings

    try:
        lat = float(raw_lat)
        lon = float(raw_lon)
    except (TypeError, ValueError):
        warnings.append(
            f"Seed '{seed.get('id', '?')}' has non-numeric lat/lon "
            f"(lat={raw_lat!r}, lon={raw_lon!r}) — using defaults."
        )
        return config.default_lat, config.default_lon, warnings

    if not (_LAT_BOUNDS[0] <= lat <= _LAT_BOUNDS[1]):
        warnings.append(
            f"lat={lat} out of valid range {_LAT_BOUNDS} for seed '{seed.get('id', '?')}' — using default."
        )
        lat = config.default_lat

    if not (_LON_BOUNDS[0] <= lon <= _LON_BOUNDS[1]):
        warnings.append(
            f"lon={lon} out of valid range {_LON_BOUNDS} for seed '{seed.get('id', '?')}' — using default."
        )
        lon = config.default_lon

    return lat, lon, warnings


def _confidence_score(
    slope_pct: float,
    elevation_m: float,
    parcel_sqm: float,
    passed: bool,
    config: SiteConfig,
    upstream_degraded: bool = False,
) -> float:
    """
    Returns a 0.0–1.0 confidence score reflecting how decisively a site
    passed (or failed) screening, and whether the upstream Mireye data was
    complete.

    Logic:
    - Start at 1.0.
    - Deduct for values inside the marginal band near a threshold.
    - Deduct 0.30 if upstream data was degraded (Mireye fallback used).
    - Floor at 0.0; cap at 1.0.
    """
    score = 1.0

    # Slope: marginal band within X% of max_slope_pct
    slope_margin = config.max_slope_pct * config.slope_marginal_band_pct
    if abs(slope_pct - config.max_slope_pct) <= slope_margin:
        score -= 0.20

    # Elevation: marginal band within X% of max_elevation_m
    elev_margin = config.max_elevation_m * config.elev_marginal_band_pct
    if abs(elevation_m - config.max_elevation_m) <= elev_margin:
        score -= 0.15

    # Parcel: marginal band within X% above min_parcel_sqm
    parcel_margin = config.min_parcel_sqm * config.parcel_marginal_band_pct
    if 0 < (parcel_sqm - config.min_parcel_sqm) <= parcel_margin:
        score -= 0.15

    # Data quality penalty
    if upstream_degraded:
        score -= 0.30

    return round(max(0.0, min(1.0, score)), 3)


def _build_reasoning(
    name: str,
    slope_pct: float,
    elevation_m: float,
    parcel_sqm: float,
    land_cover: str,
    passed: bool,
    rejection_reasons: List[str],
    confidence: float,
    upstream_degraded: bool,
    config: SiteConfig,
) -> str:
    """
    Produces a human-readable reasoning string explaining the screening decision.
    This is stored in the trace event details so the Critic Agent and provenance
    trail can surface it.
    """
    lines: List[str] = []

    verdict = "ACCEPTED" if passed else "REJECTED"
    lines.append(f"Site '{name}' screening verdict: {verdict} (confidence={confidence:.0%}).")

    # Slope assessment
    if slope_pct <= config.max_slope_pct * (1 - config.slope_marginal_band_pct):
        lines.append(f"Slope {slope_pct:.1f}% — well within buildable limit of {config.max_slope_pct}%.")
    elif slope_pct <= config.max_slope_pct:
        lines.append(
            f"Slope {slope_pct:.1f}% — marginal (within {config.slope_marginal_band_pct:.0%} of limit "
            f"{config.max_slope_pct}%); grading costs may be elevated."
        )
    else:
        lines.append(f"Slope {slope_pct:.1f}% EXCEEDS buildable limit of {config.max_slope_pct}%.")

    # Elevation assessment
    if elevation_m <= config.max_elevation_m * (1 - config.elev_marginal_band_pct):
        lines.append(f"Elevation {elevation_m:.0f}m — acceptable for heavy freight access.")
    elif elevation_m <= config.max_elevation_m:
        lines.append(
            f"Elevation {elevation_m:.0f}m — approaching freight logistics limit "
            f"of {config.max_elevation_m:.0f}m."
        )
    else:
        lines.append(f"Elevation {elevation_m:.0f}m EXCEEDS freight limit of {config.max_elevation_m:.0f}m.")

    # Parcel assessment
    lines.append(f"Land cover: {land_cover}. Available parcel: {parcel_sqm:,.0f} sqm.")

    # Rejection detail
    if not passed:
        lines.append("Rejection factors: " + "; ".join(rejection_reasons) + ".")

    # Data quality caveat
    if upstream_degraded:
        lines.append(
            "NOTE: Mireye upstream call failed — screening used MOCK/fallback geospatial data. "
            "Confidence reduced accordingly. Re-evaluate with live data before committing."
        )

    return " ".join(lines)


class SiteGenerationAgent:
    """
    Site Generation Agent.

    Proposes candidate warehouse locations from customer demand density,
    then calls the Mireye Gateway for terrain, elevation, land cover, and
    buildings to confirm each site is buildable, zoned appropriately, and
    unoccupied.

    Upgrade dimensions vs. original implementation:
    - Config-over-hardcoding: all thresholds live in SiteConfig.
    - Input validation: lat/lon bounds-checked before any Mireye call.
    - Graceful Mireye degradation: Gateway exceptions are caught; the site
      is flagged with reduced confidence rather than crashing the pipeline.
    - Reasoning: every screening decision is explained in a structured string
      stored in the trace event, not just a pass/fail flag.
    - Confidence scoring: 0–1 score reflects how far values are from
      thresholds and whether upstream data was complete.
    - Observability: structured WARNING logs at every rejection and every
      data-quality degradation, keyed by candidate_id for grep-ability.
    """

    def __init__(
        self,
        gateway: MireyeGatewayAgent,
        config: Optional[SiteConfig] = None,
    ):
        self.gateway = gateway
        self.config = config or SiteConfig()
        self.name = "Site Generation Agent"

    async def execute(
        self,
        state: NetworkState,
        raw_candidate_seeds: List[Dict[str, Any]],
    ) -> Tuple[List[Candidate], List[AgentTraceEvent]]:
        """
        Screen each raw candidate seed against physical buildability criteria.

        Args:
            state: Current NetworkState (read-only in this agent).
            raw_candidate_seeds: List of dicts from the region dataset.

        Returns:
            (candidates, trace_events) — interface unchanged from original.
            Each Candidate is tagged with passed_screening, rejection_reasons,
            and a provenance map.  Trace events include the full reasoning string.
        """
        trace_events: List[AgentTraceEvent] = []
        candidates: List[Candidate] = []
        cfg = self.config

        if not isinstance(raw_candidate_seeds, list):
            raise TypeError(
                f"SiteGenerationAgent.execute: raw_candidate_seeds must be a list, "
                f"got {type(raw_candidate_seeds).__name__}."
            )

        logger.info(
            "[%s] Starting site screening for %d candidate seeds.",
            self.name, len(raw_candidate_seeds),
        )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="SiteSitingScreening",
            status="start",
            message=(
                f"Beginning candidate warehouse evaluation for "
                f"{len(raw_candidate_seeds)} candidate sites across region."
            ),
            timestamp="",
        ))

        for seed in raw_candidate_seeds:
            if not isinstance(seed, dict):
                logger.warning(
                    "[%s] Skipping non-dict seed: %r", self.name, seed
                )
                continue

            c_id = seed.get("id", f"cand_{uuid.uuid4().hex[:6]}")
            name = seed.get("name", f"Candidate {c_id}")
            base_cap = float(seed.get("base_capacity", cfg.default_capacity))
            fixed_cost = float(seed.get("fixed_cost", cfg.default_fixed_cost))

            # ── Input validation ─────────────────────────────────────────────
            lat, lon, coord_warnings = _validate_seed(seed, cfg)
            for w in coord_warnings:
                logger.warning("[%s] [%s] Coordinate warning: %s", self.name, c_id, w)

            # ── Mireye data fetch with graceful degradation ──────────────────
            upstream_degraded = False
            terrain = None
            land_cover = None

            try:
                terrain = await self.gateway.get_terrain_elevation(lat, lon, known_base=seed)
            except Exception as exc:
                upstream_degraded = True
                logger.warning(
                    "[%s] [%s] Terrain fetch failed (%s: %s) — "
                    "using conservative fallback values; confidence will be penalised.",
                    self.name, c_id, type(exc).__name__, exc,
                )

            try:
                land_cover = await self.gateway.get_land_cover_buildings(
                    lat, lon, radius_m=cfg.land_cover_radius_m, known_base=seed
                )
            except Exception as exc:
                upstream_degraded = True
                logger.warning(
                    "[%s] [%s] Land-cover fetch failed (%s: %s) — "
                    "using conservative fallback values; confidence will be penalised.",
                    self.name, c_id, type(exc).__name__, exc,
                )

            # Conservative fallback values when Mireye is unavailable.
            # Using values that will NOT silently accept a bad site:
            # slope=0 (safe pass), elevation=0 (safe pass), parcel=0 (triggers rejection).
            slope_pct = terrain.slope_pct if terrain else 0.0
            elevation_m = terrain.elevation_m if terrain else 0.0
            land_cover_str = land_cover.primary_land_cover if land_cover else "Unknown"
            parcel_sqm = land_cover.available_parcel_sqm if land_cover else 0.0
            is_occupied = land_cover.is_occupied if land_cover else False

            provenance_map: Dict[str, ProvenanceTag] = {}
            if terrain and terrain.provenance:
                provenance_map["terrain"] = terrain.provenance
            if land_cover and land_cover.provenance:
                provenance_map["land_cover"] = land_cover.provenance

            # ── Screening rules ───────────────────────────────────────────────
            rejection_reasons: List[str] = []
            passed = True

            if upstream_degraded and not terrain and not land_cover:
                # Both Mireye calls failed entirely — we cannot screen this site.
                passed = False
                rejection_reasons.append(
                    "Upstream Mireye data unavailable for both terrain and land cover — "
                    "site cannot be screened; manual review required."
                )
            else:
                if slope_pct > cfg.max_slope_pct:
                    passed = False
                    rejection_reasons.append(
                        f"Slope exceeds buildable limit: {slope_pct:.1f}% "
                        f"(configured max: {cfg.max_slope_pct}%)"
                    )

                if elevation_m > cfg.max_elevation_m:
                    passed = False
                    rejection_reasons.append(
                        f"Elevation excessive for heavy freight logistics: "
                        f"{elevation_m:.0f}m (configured max: {cfg.max_elevation_m:.0f}m)"
                    )

                if is_occupied:
                    passed = False
                    rejection_reasons.append(
                        f"Parcel occupied / protected conservation zoning: {land_cover_str}"
                    )

                if not is_occupied and parcel_sqm < cfg.min_parcel_sqm:
                    passed = False
                    rejection_reasons.append(
                        f"Available parcel size insufficient: {parcel_sqm:,.0f} sqm "
                        f"(configured min: {cfg.min_parcel_sqm:,.0f} sqm)"
                    )

            # ── Confidence score ──────────────────────────────────────────────
            confidence = _confidence_score(
                slope_pct=slope_pct,
                elevation_m=elevation_m,
                parcel_sqm=parcel_sqm,
                passed=passed,
                config=cfg,
                upstream_degraded=upstream_degraded,
            )

            # ── Reasoning string ──────────────────────────────────────────────
            reasoning = _build_reasoning(
                name=name,
                slope_pct=slope_pct,
                elevation_m=elevation_m,
                parcel_sqm=parcel_sqm,
                land_cover=land_cover_str,
                passed=passed,
                rejection_reasons=rejection_reasons,
                confidence=confidence,
                upstream_degraded=upstream_degraded,
                config=cfg,
            )

            if not passed:
                logger.warning(
                    "[%s] [%s] REJECTED — %s",
                    self.name, c_id,
                    "; ".join(rejection_reasons),
                )
            else:
                logger.info(
                    "[%s] [%s] ACCEPTED — confidence=%.2f slope=%.1f%% elev=%.0fm parcel=%.0fsqm",
                    self.name, c_id, confidence, slope_pct, elevation_m, parcel_sqm,
                )

            # ── Build Candidate (schema unchanged) ───────────────────────────
            candidate = Candidate(
                id=c_id,
                name=name,
                lat=lat,
                lon=lon,
                demand_weight=0.0,
                terrain_slope_pct=slope_pct,
                elevation_m=elevation_m,
                land_cover=land_cover_str,
                parcel_area_sqm=parcel_sqm if passed else 0.0,
                is_occupied=is_occupied,
                flood_risk_score=0.0,   # enriched by Risk Agent
                hazard_score=0.0,
                composite_risk=0.0,
                passed_screening=passed,
                rejection_reasons=rejection_reasons,
                fixed_operating_cost=fixed_cost,
                capacity_units=base_cap,
                provenance=provenance_map,
            )
            candidates.append(candidate)

            # ── Trace event (confidence + reasoning in details) ───────────────
            status_text = "PASS" if passed else f"REJECT ({', '.join(rejection_reasons)})"
            trace_events.append(AgentTraceEvent(
                event_id=str(uuid.uuid4()),
                agent_name=self.name,
                action="CandidateScreened",
                status="progress" if passed else "warning",
                message=(
                    f"Screened candidate '{name}' at ({lat:.4f}, {lon:.4f}) "
                    f"→ {status_text}"
                ),
                details={
                    "candidate_id": c_id,
                    "passed": passed,
                    "confidence_score": confidence,
                    "elevation_m": elevation_m,
                    "slope_pct": slope_pct,
                    "land_cover": land_cover_str,
                    "parcel_sqm": parcel_sqm,
                    "upstream_degraded": upstream_degraded,
                    "reasoning": reasoning,
                    "rejection_reasons": rejection_reasons,
                    "thresholds_used": {
                        "max_slope_pct": cfg.max_slope_pct,
                        "max_elevation_m": cfg.max_elevation_m,
                        "min_parcel_sqm": cfg.min_parcel_sqm,
                    },
                },
                timestamp="",
                provenance=terrain.provenance if terrain else None,
            ))

        surviving_count = sum(1 for c in candidates if c.passed_screening)
        logger.info(
            "[%s] Screening complete. %d/%d candidates passed.",
            self.name, surviving_count, len(candidates),
        )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="SiteSitingScreening",
            status="complete",
            message=(
                f"Site screening complete. {surviving_count}/{len(candidates)} candidates "
                f"passed physical buildability criteria."
            ),
            details={
                "surviving_count": surviving_count,
                "total_candidates": len(candidates),
                "config": {
                    "max_slope_pct": cfg.max_slope_pct,
                    "max_elevation_m": cfg.max_elevation_m,
                    "min_parcel_sqm": cfg.min_parcel_sqm,
                    "land_cover_radius_m": cfg.land_cover_radius_m,
                },
            },
            timestamp="",
        ))

        return candidates, trace_events


# ═════════════════════════════════════════════════════════════════════════════
# MOCK HARNESS — run the Site Agent standalone, no Mireye API / server needed
#
#     python -m agents.site_agent                  # full scenario sweep
#     python -m agents.site_agent --scenario pass  # one scenario
#     python -m agents.site_agent --json           # machine-readable output
#
# Every scenario prints the INPUT seed and the OUTPUT candidate + trace event
# side by side, so you can eyeball that screening actually works.
# ═══════════════════════════════════════════════════════════════════════════

import json as _json
import asyncio as _asyncio
import argparse as _argparse
from datetime import datetime as _dt, timezone as _tz

from schemas.mireye import (
    MireyeTerrainResponse as _Terrain,
    MireyeLandCoverResponse as _LandCover,
)


def _mock_provenance(endpoint: str, **params: Any) -> ProvenanceTag:
    """A real ProvenanceTag flagged as mock, so downstream schema validation passes."""
    return ProvenanceTag(
        endpoint=endpoint,
        params={"mock": True, **params},
        timestamp=_dt.now(_tz.utc).isoformat(),
        response_hash="mock-" + str(abs(hash((endpoint, tuple(sorted(params.items()))))))[:12],
        cached=False,
        latency_ms=0.0,
    )


class MockMireyeGateway:
    """
    Drop-in stand-in for MireyeGatewayAgent, satisfying only the two methods
    SiteGenerationAgent actually calls:

        await get_terrain_elevation(lat, lon, known_base=...)  -> MireyeTerrainResponse
        await get_land_cover_buildings(lat, lon, radius_m=..., known_base=...)
                                                              -> MireyeLandCoverResponse

    Values are read from the seed dict itself (`known_base`) when present, so a
    test can dictate exactly what terrain the agent "sees":

        {"id": "X", "lat": 47.4, "lon": -122.2,
         "mock_slope_pct": 12.0, "mock_parcel_sqm": 5000, "mock_is_occupied": True}

    Failure injection:
        MockMireyeGateway(fail_terrain=True)     -> terrain call raises
        MockMireyeGateway(fail_land_cover=True)  -> land-cover call raises
    """

    # Defaults used when the seed does not override them — a clean, passing site.
    DEFAULTS = {
        "slope_pct": 2.0,
        "elevation_m": 45.0,
        "primary_land_cover": "Industrial",
        "available_parcel_sqm": 60_000.0,
        "is_occupied": False,
    }

    def __init__(self, fail_terrain: bool = False, fail_land_cover: bool = False,
                 overrides: Optional[Dict[str, Any]] = None):
        self.fail_terrain = fail_terrain
        self.fail_land_cover = fail_land_cover
        self.overrides = overrides or {}
        self.calls: List[Dict[str, Any]] = []   # inspectable call log

    def _value(self, key: str, seed: Optional[Dict[str, Any]]) -> Any:
        if seed and f"mock_{key}" in seed:
            return seed[f"mock_{key}"]
        if key in self.overrides:
            return self.overrides[key]
        return self.DEFAULTS[key]

    async def get_terrain_elevation(self, lat: float, lon: float,
                                    known_base: Optional[Dict[str, Any]] = None) -> _Terrain:
        self.calls.append({"method": "get_terrain_elevation", "lat": lat, "lon": lon})
        if self.fail_terrain:
            raise ConnectionError("MOCK: Mireye terrain endpoint unreachable")

        slope_pct = float(self._value("slope_pct", known_base))
        return _Terrain(
            lat=lat,
            lon=lon,
            elevation_m=float(self._value("elevation_m", known_base)),
            slope_degrees=round(slope_pct * 0.573, 3),
            slope_pct=slope_pct,
            aspect="Flat" if slope_pct < 3 else "NE",
            buildability_score=round(max(0.0, 1.0 - slope_pct / 20.0), 3),
            provenance=_mock_provenance("/v1/fetch", lat=lat, lon=lon, layer="terrain"),
        )

    async def get_land_cover_buildings(self, lat: float, lon: float, radius_m: float = 500.0,
                                       known_base: Optional[Dict[str, Any]] = None) -> _LandCover:
        self.calls.append({"method": "get_land_cover_buildings", "lat": lat,
                           "lon": lon, "radius_m": radius_m})
        if self.fail_land_cover:
            raise ConnectionError("MOCK: Mireye land-cover endpoint unreachable")

        cover = str(self._value("primary_land_cover", known_base))
        parcel = float(self._value("available_parcel_sqm", known_base))
        return _LandCover(
            lat=lat,
            lon=lon,
            radius_m=radius_m,
            primary_land_cover=cover,
            is_industrial_zoned=cover.lower() in ("industrial", "commercial"),
            building_footprint_sqm=max(0.0, 80_000.0 - parcel),
            available_parcel_sqm=parcel,
            is_occupied=bool(self._value("is_occupied", known_base)),
            provenance=_mock_provenance("/v1/geospatial/land-cover-parcels",
                                        lat=lat, lon=lon, radius_m=radius_m),
        )


# ── Scenario catalogue: (name, seeds, gateway kwargs, what we expect) ───────
MOCK_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "pass": {
        "why": "Flat, low, large industrial parcel — should ACCEPT with high confidence.",
        "seeds": [{"id": "WH-A", "name": "Warehouse Alpha", "lat": 47.41, "lon": -122.24}],
        "gateway": {},
        "expect_passed": [True],
    },
    "slope": {
        "why": "Slope 12% vs 8% limit — should REJECT on slope.",
        "seeds": [{"id": "WH-B", "name": "Hillside Site", "lat": 47.50, "lon": -122.30,
                   "mock_slope_pct": 12.0}],
        "gateway": {},
        "expect_passed": [False],
    },
    "elevation": {
        "why": "Elevation 400m vs 250m limit — should REJECT on freight access.",
        "seeds": [{"id": "WH-C", "name": "Mountain Site", "lat": 47.60, "lon": -121.90,
                   "mock_elevation_m": 400.0}],
        "gateway": {},
        "expect_passed": [False],
    },
    "occupied": {
        "why": "Parcel already occupied / conservation zoned — should REJECT.",
        "seeds": [{"id": "WH-D", "name": "Wetland Reserve", "lat": 47.30, "lon": -122.40,
                   "mock_is_occupied": True, "mock_primary_land_cover": "Wetland"}],
        "gateway": {},
        "expect_passed": [False],
    },
    "small_parcel": {
        "why": "Parcel 5,000 sqm vs 25,000 minimum — should REJECT on size.",
        "seeds": [{"id": "WH-E", "name": "Cramped Lot", "lat": 47.45, "lon": -122.20,
                   "mock_available_parcel_sqm": 5_000.0}],
        "gateway": {},
        "expect_passed": [False],
    },
    "marginal": {
        "why": "Slope 7.9% (just under the 8% limit) — ACCEPT but with reduced confidence.",
        "seeds": [{"id": "WH-F", "name": "Marginal Grade", "lat": 47.44, "lon": -122.22,
                   "mock_slope_pct": 7.9}],
        "gateway": {},
        "expect_passed": [True],
    },
    "partial_outage": {
        "why": "Terrain call fails, land cover OK — degraded data, confidence penalised.",
        "seeds": [{"id": "WH-G", "name": "Partial Data Site", "lat": 47.42, "lon": -122.26}],
        "gateway": {"fail_terrain": True},
        "expect_passed": [True],
    },
    "full_outage": {
        "why": "Both Mireye calls fail — must REJECT (never silently pass an unscreened site).",
        "seeds": [{"id": "WH-H", "name": "Blind Site", "lat": 47.43, "lon": -122.27}],
        "gateway": {"fail_terrain": True, "fail_land_cover": True},
        "expect_passed": [False],
    },
    "bad_input": {
        "why": "Missing lat/lon, out-of-range lon, and a non-dict entry — validate, warn, never crash.",
        "seeds": [
            {"id": "WH-I", "name": "No Coordinates"},
            {"id": "WH-J", "name": "Bad Longitude", "lat": 47.4, "lon": 999.0},
            "this-is-not-a-dict",
        ],
        "gateway": {},
        "expect_passed": [True, True],
    },
}


async def run_mock_scenario(name: str, as_json: bool = False) -> bool:
    """
    Run one named scenario end-to-end against MockMireyeGateway and print the
    INPUT seeds next to the OUTPUT candidates + reasoning.

    Returns True if every candidate's passed_screening matched `expect_passed`.
    """
    spec = MOCK_SCENARIOS[name]
    gateway = MockMireyeGateway(**spec["gateway"])
    agent = SiteGenerationAgent(gateway, config=spec.get("config"))
    state: NetworkState = {}  # NetworkState is a TypedDict; this agent reads nothing from it

    candidates, events = await agent.execute(state, spec["seeds"])

    screened = [e for e in events if e.action == "CandidateScreened"]
    actual = [c.passed_screening for c in candidates]
    ok = actual == spec["expect_passed"]

    if as_json:
        print(_json.dumps({
            "scenario": name,
            "why": spec["why"],
            "input_seeds": spec["seeds"],
            "gateway_calls": gateway.calls,
            "output_candidates": [
                {
                    "id": c.id, "name": c.name, "lat": c.lat, "lon": c.lon,
                    "slope_pct": c.terrain_slope_pct, "elevation_m": c.elevation_m,
                    "land_cover": c.land_cover, "parcel_sqm": c.parcel_area_sqm,
                    "is_occupied": c.is_occupied,
                    "passed_screening": c.passed_screening,
                    "rejection_reasons": c.rejection_reasons,
                    "provenance_keys": sorted(c.provenance.keys()),
                }
                for c in candidates
            ],
            "confidence_scores": [e.details.get("confidence_score") for e in screened],
            "reasoning": [e.details.get("reasoning") for e in screened],
            "expected_passed": spec["expect_passed"],
            "actual_passed": actual,
            "result": "OK" if ok else "MISMATCH",
        }, indent=2, default=str))
        return ok

    print("\n" + "=" * 78)
    print(f"SCENARIO: {name}")
    print(f"  {spec['why']}")
    print("=" * 78)

    print("\n-- INPUT (seeds handed to agent.execute) --")
    for s in spec["seeds"]:
        print(f"   {s!r}")
    print(f"   gateway: MockMireyeGateway({', '.join(f'{k}={v}' for k, v in spec['gateway'].items()) or 'defaults'})")

    print(f"\n-- MIREYE CALLS MADE ({len(gateway.calls)}) --")
    for call in gateway.calls:
        print(f"   {call}")

    print(f"\n-- OUTPUT ({len(candidates)} candidate(s), {len(events)} trace event(s)) --")
    for c, ev in zip(candidates, screened):
        verdict = "PASS" if c.passed_screening else "REJECT"
        print(f"\n   [{verdict}] {c.id} — {c.name}  @ ({c.lat}, {c.lon})")
        print(f"      slope={c.terrain_slope_pct}%  elev={c.elevation_m}m  "
              f"parcel={c.parcel_area_sqm:,.0f} sqm  cover={c.land_cover}  occupied={c.is_occupied}")
        print(f"      confidence={ev.details.get('confidence_score')}  "
              f"upstream_degraded={ev.details.get('upstream_degraded')}")
        print(f"      provenance={sorted(c.provenance.keys()) or 'none (mireye unavailable)'}")
        if c.rejection_reasons:
            for r in c.rejection_reasons:
                print(f"      reject: {r}")
        print(f"      reasoning: {ev.details.get('reasoning')}")

    print(f"\n-- CHECK --  expected passed={spec['expect_passed']}  actual={actual}  "
          f"→ {'OK' if ok else 'MISMATCH'}")
    return ok


async def run_all_mock_scenarios(as_json: bool = False) -> int:
    results = {}
    for name in MOCK_SCENARIOS:
        results[name] = await run_mock_scenario(name, as_json=as_json)
    failures = [n for n, ok in results.items() if not ok]
    if not as_json:
        print("\n" + "=" * 78)
        print(f"SUMMARY: {len(results) - len(failures)}/{len(results)} scenarios behaved as expected.")
        for n, ok in results.items():
            print(f"   {'OK    ' if ok else 'FAILED'}  {n}")
        print("=" * 78)
    return 1 if failures else 0


def _mock_main(argv: Optional[List[str]] = None) -> int:
    parser = _argparse.ArgumentParser(
        description="Run SiteGenerationAgent against a mock Mireye gateway (no API key needed)."
    )
    parser.add_argument("--scenario", choices=sorted(MOCK_SCENARIOS), default=None,
                        help="Run a single scenario (default: run all).")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    parser.add_argument("--log-level", default="WARNING",
                        help="Agent log level: DEBUG, INFO, WARNING (default WARNING).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(levelname)s %(name)s: %(message)s")

    if args.scenario:
        ok = _asyncio.run(run_mock_scenario(args.scenario, as_json=args.json))
        return 0 if ok else 1
    return _asyncio.run(run_all_mock_scenarios(as_json=args.json))


if __name__ == "__main__":
    raise SystemExit(_mock_main())
