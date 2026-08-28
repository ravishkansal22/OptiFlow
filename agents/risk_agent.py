import uuid
from typing import List, Dict, Any, Tuple
from schemas.state import NetworkState, Candidate, AgentTraceEvent
from agents.mireye_gateway_agent import MireyeGatewayAgent
from agents.site_scoring import score_candidates


class RiskAgent:
    """
    Risk Agent:
    Calls the Mireye Gateway for flood exposure, hazard layers, and elevation
    on every candidate, converting raw attributes into a normalized 0-1 risk score
    with pass/fail flags and auditable rejection rationales.
    """

    def __init__(self, gateway: MireyeGatewayAgent):
        self.gateway = gateway
        self.name = "Risk Agent"

    async def execute(
        self,
        candidates: List[Candidate],
        raw_seeds_map: Dict[str, Any],
        on_event=None
    ) -> Tuple[List[Candidate], List[AgentTraceEvent]]:
        trace_events = []
        updated_candidates: List[Candidate] = []

        def emit(event: AgentTraceEvent):
            """Record the event, and hand it straight on so the UI sees it now."""
            trace_events.append(event)
            if on_event:
                on_event(event)

        start_event = AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="HazardScoring",
            status="start",
            message=f"Beginning geospatial hazard and flood exposure scoring for {len(candidates)} candidates.",
            timestamp=""
        )
        emit(start_event)

        for cand in candidates:
            # If already rejected in site screening, keep rejection reason and skip flood scoring
            if not cand.passed_screening:
                updated_candidates.append(cand)
                continue

            seed_data = raw_seeds_map.get(cand.id, {})
            flood_resp = await self.gateway.get_flood_hazard(cand.lat, cand.lon, known_base=seed_data)

            # Compute composite risk: weighted combination of flood risk + slope + historical events
            flood_score = flood_resp.flood_risk_index
            hist_events_factor = min(1.0, flood_resp.historical_flood_events / 5.0)
            slope_risk = min(1.0, cand.terrain_slope_pct / 8.0) * 0.2

            composite_risk = round(0.65 * flood_score + 0.20 * hist_events_factor + 0.15 * slope_risk, 3)

            passed_risk = True
            rejection_reasons = list(cand.rejection_reasons)

            # High risk threshold: sites in Zone AE or with composite risk > 0.75 are flagged/penalized
            if composite_risk > 0.75:
                passed_risk = False
                rejection_reasons.append(f"Excessive flood hazard profile ({flood_resp.flood_zone}, risk index: {composite_risk:.2f})")

            cand.flood_risk_score = flood_score
            cand.hazard_score = composite_risk
            cand.composite_risk = composite_risk
            cand.passed_screening = cand.passed_screening and passed_risk
            cand.rejection_reasons = rejection_reasons
            cand.provenance["flood"] = flood_resp.provenance

            updated_candidates.append(cand)

            emit(AgentTraceEvent(
                event_id=str(uuid.uuid4()),
                agent_name=self.name,
                action="CandidateRiskEvaluated",
                status="progress" if passed_risk else "warning",
                message=f"Risk evaluated for '{cand.name}' -> Zone: {flood_resp.flood_zone}, Risk Score: {composite_risk:.2f} ({'PASS' if passed_risk else 'HIGH RISK'})",
                details={
                    "candidate_id": cand.id,
                    "flood_zone": flood_resp.flood_zone,
                    "annual_flood_probability": flood_resp.annual_flood_probability,
                    "flood_risk_index": flood_score,
                    "composite_risk": composite_risk,
                    "passed": passed_risk
                },
                timestamp="",
                provenance=flood_resp.provenance
            ))

        # Rank the survivors against one another now that every risk value is in.
        score_candidates(updated_candidates)

        qualified_count = sum(1 for c in updated_candidates if c.passed_screening)
        emit(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="HazardScoring",
            status="complete",
            message=f"Hazard scoring completed. {qualified_count}/{len(updated_candidates)} candidates qualified for logistics graph.",
            details={"qualified_candidates": qualified_count},
            timestamp=""
        ))

        return updated_candidates, trace_events
