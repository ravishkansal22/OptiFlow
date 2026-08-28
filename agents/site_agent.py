import uuid
from typing import List, Dict, Any, Tuple
from schemas.state import NetworkState, Candidate, InputSpec, AgentTraceEvent
from schemas.mireye import ProvenanceTag
from agents.mireye_gateway_agent import MireyeGatewayAgent


class SiteGenerationAgent:
    """
    Site Generation Agent:
    Proposes candidate warehouse locations from customer demand density,
    then calls the Mireye Gateway for terrain, elevation, land cover, and buildings
    to confirm each site is buildable, zoned appropriately, and unoccupied.
    """

    def __init__(self, gateway: MireyeGatewayAgent):
        self.gateway = gateway
        self.name = "Site Generation Agent"

    async def execute(
        self,
        state: NetworkState,
        raw_candidate_seeds: List[Dict[str, Any]],
        on_event=None
    ) -> Tuple[List[Candidate], List[AgentTraceEvent]]:
        trace_events = []
        candidates: List[Candidate] = []

        def emit(event: AgentTraceEvent):
            """Record the event, and hand it straight on so the UI sees it now."""
            trace_events.append(event)
            if on_event:
                on_event(event)
        
        start_event = AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="SiteSitingScreening",
            status="start",
            message=f"Beginning candidate warehouse evaluation for {len(raw_candidate_seeds)} candidate sites across region.",
            timestamp="",
        )
        emit(start_event)

        for seed in raw_candidate_seeds:
            c_id = seed.get("id", f"cand_{uuid.uuid4().hex[:6]}")
            name = seed.get("name", f"Candidate {c_id}")
            lat = seed.get("lat", 47.50)
            lon = seed.get("lon", -122.25)
            base_cap = seed.get("base_capacity", 20000.0)
            fixed_cost = seed.get("fixed_cost", 130000.0)

            # Query Mireye Gateway for Terrain / Slope
            terrain = await self.gateway.get_terrain_elevation(lat, lon, known_base=seed)
            
            # Query Mireye Gateway for Land Cover / Parcel suitability
            land_cover = await self.gateway.get_land_cover_buildings(lat, lon, radius_m=500.0, known_base=seed)

            # Site Screening Logic
            rejection_reasons = []
            passed = True

            if terrain.slope_pct > 8.0:
                passed = False
                rejection_reasons.append(f"Slope exceeds buildable limit: {terrain.slope_pct}% (Max: 8.0%)")
            
            if terrain.elevation_m > 250.0:
                passed = False
                rejection_reasons.append(f"Elevation excessive for heavy freight logistics: {terrain.elevation_m}m")

            if land_cover.is_occupied:
                passed = False
                rejection_reasons.append(f"Parcel occupied / protected conservation zoning: {land_cover.primary_land_cover}")

            if land_cover.available_parcel_sqm < 25000.0 and not land_cover.is_occupied:
                passed = False
                rejection_reasons.append(f"Available parcel size insufficient: {land_cover.available_parcel_sqm} sqm (Min: 25,000 sqm)")

            provenance_map: Dict[str, ProvenanceTag] = {
                "terrain": terrain.provenance,
                "land_cover": land_cover.provenance
            }

            candidate = Candidate(
                id=c_id,
                name=name,
                lat=lat,
                lon=lon,
                demand_weight=0.0,
                terrain_slope_pct=terrain.slope_pct,
                elevation_m=terrain.elevation_m,
                land_cover=land_cover.primary_land_cover,
                parcel_area_sqm=land_cover.available_parcel_sqm if passed else 0.0,
                is_occupied=land_cover.is_occupied,
                flood_risk_score=0.0,  # will be enriched by Risk Agent
                hazard_score=0.0,
                composite_risk=0.0,
                passed_screening=passed,
                rejection_reasons=rejection_reasons,
                fixed_operating_cost=fixed_cost,
                capacity_units=base_cap,
                provenance=provenance_map
            )
            candidates.append(candidate)

            # Trace event
            status_text = "PASS" if passed else f"REJECT ({', '.join(rejection_reasons)})"
            emit(AgentTraceEvent(
                event_id=str(uuid.uuid4()),
                agent_name=self.name,
                action="CandidateScreened",
                status="progress" if passed else "warning",
                message=f"Screened candidate '{name}' at ({lat:.4f}, {lon:.4f}) -> {status_text}",
                details={
                    "candidate_id": c_id,
                    "passed": passed,
                    "elevation_m": terrain.elevation_m,
                    "slope_pct": terrain.slope_pct,
                    "land_cover": land_cover.primary_land_cover
                },
                timestamp="",
                provenance=terrain.provenance
            ))

        surviving_count = sum(1 for c in candidates if c.passed_screening)
        emit(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="SiteSitingScreening",
            status="complete",
            message=f"Site screening complete. {surviving_count}/{len(candidates)} candidates passed physical buildability criteria.",
            details={"surviving_count": surviving_count, "total_candidates": len(candidates)},
            timestamp=""
        ))

        return candidates, trace_events
