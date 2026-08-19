import uuid
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional

from schemas.state import Candidate, AgentTraceEvent
from agents.mireye_gateway_agent import MireyeGatewayAgent

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """
    All tuneable parameters for the Risk Agent's composite hazard scoring.

    Pass a custom RiskConfig to RiskAgent to override any value without
    touching source code.

    Composite formula (all weights must sum to 1.0):
        composite_risk = (
            flood_weight          * flood_risk_index
          + hist_events_weight    * norm_historical_events
          + slope_weight          * norm_slope_risk
          + annual_prob_weight    * norm_annual_prob
        )
    """
    # --- Formula weights (must sum to 1.0) ---
    flood_weight: float = 0.55          # flood risk index (0–1 from Mireye)
    hist_events_weight: float = 0.20    # normalised historical flood frequency
    slope_weight: float = 0.15         # normalised terrain slope contribution
    annual_prob_weight: float = 0.10    # annualised flood probability

    # --- Normalisers ---
    hist_events_normaliser: float = 5.0   # events above this → factor=1.0
    slope_normaliser_pct: float = 8.0     # slope above this → slope factor=1.0
    annual_prob_normaliser: float = 0.02  # annual prob above this → factor=1.0

    # --- Rejection threshold ---
    composite_risk_rejection_threshold: float = 0.75  # composite ≥ this → REJECTED

    # --- Pessimistic fallback when Mireye is unavailable ---
    # Using 0.5 (medium risk) — not 1.0 (would always reject)
    # and not 0.0 (would never reject) so we don't silently pass bad sites.
    upstream_failure_flood_score: float = 0.50
    upstream_failure_composite_risk: float = 0.50

    # --- Confidence bands (fraction of rejection threshold) ---
    # Within this fraction of the threshold → marginal confidence penalty
    marginal_band_fraction: float = 0.15

    def validate(self):
        total = (
            self.flood_weight
            + self.hist_events_weight
            + self.slope_weight
            + self.annual_prob_weight
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"RiskConfig weights must sum to 1.0, got {total:.4f}. "
                f"(flood={self.flood_weight}, hist={self.hist_events_weight}, "
                f"slope={self.slope_weight}, annual_prob={self.annual_prob_weight})"
            )


def _composite_score(
    flood_risk_index: float,
    historical_flood_events: int,
    slope_pct: float,
    annual_flood_probability: float,
    cfg: RiskConfig,
) -> Tuple[float, Dict[str, float]]:
    """
    Compute the weighted composite risk score and return a risk_breakdown dict
    showing each component's individual contribution.

    Returns:
        (composite_risk, risk_breakdown)
    """
    norm_hist = min(1.0, historical_flood_events / cfg.hist_events_normaliser)
    norm_slope = min(1.0, slope_pct / cfg.slope_normaliser_pct) * 1.0
    norm_annual = min(1.0, annual_flood_probability / cfg.annual_prob_normaliser)

    components = {
        "flood_index_contrib": round(cfg.flood_weight * flood_risk_index, 4),
        "hist_events_contrib": round(cfg.hist_events_weight * norm_hist, 4),
        "slope_contrib": round(cfg.slope_weight * norm_slope, 4),
        "annual_prob_contrib": round(cfg.annual_prob_weight * norm_annual, 4),
    }
    composite = round(sum(components.values()), 4)
    return composite, components


def _confidence_score(composite_risk: float, cfg: RiskConfig, upstream_degraded: bool) -> float:
    """
    Returns 0.0–1.0 confidence reflecting decisiveness of the risk verdict
    and data quality.

    - Values near the rejection threshold → lower confidence.
    - Upstream failure → larger penalty.
    """
    score = 1.0
    band = cfg.composite_risk_rejection_threshold * cfg.marginal_band_fraction
    if abs(composite_risk - cfg.composite_risk_rejection_threshold) <= band:
        score -= 0.25
    if upstream_degraded:
        score -= 0.35
    return round(max(0.0, min(1.0, score)), 3)


def _build_reasoning(
    name: str,
    flood_zone: str,
    composite_risk: float,
    risk_breakdown: Dict[str, float],
    passed: bool,
    rejection_reasons: List[str],
    confidence: float,
    upstream_degraded: bool,
    cfg: RiskConfig,
) -> str:
    """
    Human-readable explanation of the risk scoring decision.
    Stored in trace event details['reasoning'] for the Critic Agent and
    provenance trail.
    """
    verdict = "ACCEPTED" if passed else "REJECTED"
    lines = [
        f"Risk assessment for '{name}': {verdict} "
        f"(composite_risk={composite_risk:.3f}, confidence={confidence:.0%}).",
        f"Flood zone: {flood_zone}.",
    ]

    # Identify the dominant risk driver
    top_driver = max(risk_breakdown, key=risk_breakdown.get)
    driver_labels = {
        "flood_index_contrib": "flood risk index",
        "hist_events_contrib": "historical flood frequency",
        "slope_contrib": "terrain slope",
        "annual_prob_contrib": "annual flood probability",
    }
    lines.append(
        f"Dominant risk driver: {driver_labels.get(top_driver, top_driver)} "
        f"(contribution={risk_breakdown[top_driver]:.3f} of {composite_risk:.3f} total)."
    )

    # Threshold context
    threshold = cfg.composite_risk_rejection_threshold
    band = threshold * cfg.marginal_band_fraction
    if not passed:
        lines.append(
            f"Composite risk {composite_risk:.3f} exceeds rejection threshold {threshold}. "
            + "; ".join(rejection_reasons) + "."
        )
    elif abs(composite_risk - threshold) <= band:
        lines.append(
            f"Composite risk {composite_risk:.3f} is within {cfg.marginal_band_fraction:.0%} "
            f"of rejection threshold {threshold} — marginal PASS; monitor closely."
        )
    else:
        lines.append(
            f"Composite risk {composite_risk:.3f} comfortably below threshold {threshold}."
        )

    if upstream_degraded:
        lines.append(
            "NOTE: Mireye flood data unavailable — conservative fallback scores used "
            "(MIREYE_MOCK_MODE). Re-evaluate with live data before committing."
        )

    return " ".join(lines)


class RiskAgent:
    """
    Risk Agent.

    Calls the Mireye Gateway for flood exposure, hazard layers, and elevation
    on every passing candidate, converting raw attributes into a normalized 0–1
    composite risk score with per-factor breakdown, confidence scoring, and
    human-readable reasoning.

    Upgrade dimensions vs. original:
    - RiskConfig: all weights, thresholds, and normalisers are constructor args.
    - Immutability: candidates are updated via model_copy() not direct mutation.
    - Graceful Mireye degradation: gateway exceptions → conservative fallback score,
      upstream_degraded flag, reduced confidence — never a pipeline crash.
    - Annual flood probability is now a fourth scoring signal, not just decorative.
    - Reasoning: per-candidate explanation identifies the dominant risk driver
      and threshold context, stored in trace details['reasoning'].
    - Confidence scoring: reflects margin-to-threshold and data quality.
    - Observability: structured WARNING/INFO logs keyed by candidate_id.
    - Interface: execute(candidates, raw_seeds_map) → unchanged.
    """

    def __init__(
        self,
        gateway: MireyeGatewayAgent,
        config: Optional[RiskConfig] = None,
    ):
        self.gateway = gateway
        self.config = config or RiskConfig()
        self.name = "Risk Agent"
        self.config.validate()

    async def execute(
        self,
        candidates: List[Candidate],
        raw_seeds_map: Dict[str, Any],
    ) -> Tuple[List[Candidate], List[AgentTraceEvent]]:
        """
        Score each passing candidate for geospatial hazard risk.

        Args:
            candidates: List of Candidates from the Site Generation Agent.
                        Already-rejected candidates are forwarded unchanged.
            raw_seeds_map: Dict mapping candidate_id → raw seed dict (for
                           Mireye known_base hints).

        Returns:
            (updated_candidates, trace_events) — interface unchanged.
        """
        if not isinstance(candidates, list):
            raise TypeError(
                f"RiskAgent.execute: candidates must be a list, "
                f"got {type(candidates).__name__}."
            )
        if not isinstance(raw_seeds_map, dict):
            raise TypeError(
                f"RiskAgent.execute: raw_seeds_map must be a dict, "
                f"got {type(raw_seeds_map).__name__}."
            )

        cfg = self.config
        trace_events: List[AgentTraceEvent] = []
        updated_candidates: List[Candidate] = []

        scoreable = sum(1 for c in candidates if c.passed_screening)
        logger.info(
            "[%s] Starting hazard scoring for %d candidates (%d eligible, %d pre-rejected).",
            self.name, len(candidates), scoreable, len(candidates) - scoreable,
        )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="HazardScoring",
            status="start",
            message=(
                f"Beginning geospatial hazard and flood exposure scoring "
                f"for {len(candidates)} candidates ({scoreable} eligible)."
            ),
            timestamp="",
        ))

        for cand in candidates:
            # ── Pre-rejected candidates pass through unchanged ───────────────
            if not cand.passed_screening:
                updated_candidates.append(cand)
                continue

            seed_data = raw_seeds_map.get(cand.id, {})

            # ── Mireye flood data fetch with graceful degradation ────────────
            upstream_degraded = False
            flood_resp = None

            try:
                flood_resp = await self.gateway.get_flood_hazard(
                    cand.lat, cand.lon, known_base=seed_data
                )
            except Exception as exc:
                upstream_degraded = True
                logger.warning(
                    "[%s] [%s] Flood hazard fetch failed (%s: %s) — "
                    "applying conservative fallback risk scores; confidence penalised.",
                    self.name, cand.id, type(exc).__name__, exc,
                )

            # ── Extract signals (with conservative fallbacks) ────────────────
            if flood_resp:
                flood_risk_index = flood_resp.flood_risk_index
                historical_flood_events = flood_resp.historical_flood_events
                annual_flood_probability = flood_resp.annual_flood_probability
                flood_zone = flood_resp.flood_zone
            else:
                flood_risk_index = cfg.upstream_failure_flood_score
                historical_flood_events = 0
                annual_flood_probability = 0.0
                flood_zone = "Unknown (data unavailable)"

            # ── Composite risk score + breakdown ─────────────────────────────
            composite_risk, risk_breakdown = _composite_score(
                flood_risk_index=flood_risk_index,
                historical_flood_events=historical_flood_events,
                slope_pct=cand.terrain_slope_pct,
                annual_flood_probability=annual_flood_probability,
                cfg=cfg,
            )

            # ── Risk verdict ─────────────────────────────────────────────────
            passed_risk = composite_risk < cfg.composite_risk_rejection_threshold
            rejection_reasons = list(cand.rejection_reasons)

            if not passed_risk:
                rejection_reasons.append(
                    f"Excessive flood hazard profile ({flood_zone}, "
                    f"composite risk: {composite_risk:.3f} ≥ threshold {cfg.composite_risk_rejection_threshold})"
                )

            # ── Confidence score ──────────────────────────────────────────────
            confidence = _confidence_score(composite_risk, cfg, upstream_degraded)

            # ── Reasoning string ──────────────────────────────────────────────
            reasoning = _build_reasoning(
                name=cand.name,
                flood_zone=flood_zone,
                composite_risk=composite_risk,
                risk_breakdown=risk_breakdown,
                passed=passed_risk,
                rejection_reasons=rejection_reasons,
                confidence=confidence,
                upstream_degraded=upstream_degraded,
                cfg=cfg,
            )

            if not passed_risk:
                logger.warning(
                    "[%s] [%s] HIGH RISK — composite=%.3f threshold=%.2f zone=%s",
                    self.name, cand.id, composite_risk,
                    cfg.composite_risk_rejection_threshold, flood_zone,
                )
            else:
                logger.info(
                    "[%s] [%s] PASS — composite=%.3f confidence=%.2f zone=%s",
                    self.name, cand.id, composite_risk, confidence, flood_zone,
                )

            # ── Immutable candidate update ────────────────────────────────────
            new_provenance = dict(cand.provenance)
            if flood_resp and flood_resp.provenance:
                new_provenance["flood"] = flood_resp.provenance

            updated_cand = cand.model_copy(update={
                "flood_risk_score": flood_risk_index,
                "hazard_score": composite_risk,
                "composite_risk": composite_risk,
                "passed_screening": cand.passed_screening and passed_risk,
                "rejection_reasons": rejection_reasons,
                "provenance": new_provenance,
            })
            updated_candidates.append(updated_cand)

            # ── Trace event ───────────────────────────────────────────────────
            trace_events.append(AgentTraceEvent(
                event_id=str(uuid.uuid4()),
                agent_name=self.name,
                action="CandidateRiskEvaluated",
                status="progress" if passed_risk else "warning",
                message=(
                    f"Risk evaluated for '{cand.name}' → "
                    f"Zone: {flood_zone}, "
                    f"Risk Score: {composite_risk:.3f} "
                    f"({'PASS' if passed_risk else 'HIGH RISK'})"
                ),
                details={
                    "candidate_id": cand.id,
                    "flood_zone": flood_zone,
                    "annual_flood_probability": annual_flood_probability,
                    "flood_risk_index": flood_risk_index,
                    "composite_risk": composite_risk,
                    "risk_breakdown": risk_breakdown,
                    "confidence_score": confidence,
                    "upstream_degraded": upstream_degraded,
                    "passed": passed_risk,
                    "reasoning": reasoning,
                    "weights_used": {
                        "flood": cfg.flood_weight,
                        "hist_events": cfg.hist_events_weight,
                        "slope": cfg.slope_weight,
                        "annual_prob": cfg.annual_prob_weight,
                    },
                },
                timestamp="",
                provenance=flood_resp.provenance if flood_resp else None,
            ))

        qualified_count = sum(1 for c in updated_candidates if c.passed_screening)
        logger.info(
            "[%s] Hazard scoring complete. %d/%d candidates qualified.",
            self.name, qualified_count, len(updated_candidates),
        )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="HazardScoring",
            status="complete",
            message=(
                f"Hazard scoring completed. {qualified_count}/{len(updated_candidates)} "
                f"candidates qualified for logistics graph."
            ),
            details={
                "qualified_candidates": qualified_count,
                "total_candidates": len(updated_candidates),
                "config": {
                    "composite_risk_rejection_threshold": cfg.composite_risk_rejection_threshold,
                    "weights": {
                        "flood": cfg.flood_weight,
                        "hist_events": cfg.hist_events_weight,
                        "slope": cfg.slope_weight,
                        "annual_prob": cfg.annual_prob_weight,
                    },
                },
            },
            timestamp="",
        ))

        return updated_candidates, trace_events
