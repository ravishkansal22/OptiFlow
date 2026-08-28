"""
Shared suitability scoring for candidate warehouse sites.

The same four components decide a score whether a site arrives through the full
pipeline or through /api/evaluate-sites, so a site never scores one way in the
shortlist and another way in a standalone check. Every component is a ratio of
values the Site and Risk agents measured through the Mireye Gateway.
"""

from typing import Dict, List, Optional

from schemas.state import Candidate

#: Component weights. Normalised before use, so an override need not sum to 1.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "hazard_headroom": 0.40,
    "slope_headroom": 0.25,
    "parcel_adequacy": 0.20,
    "capacity_share": 0.15,
}

#: The gates the Site agent enforces, reused here so headroom is measured
#: against the same limits a site is screened against.
MAX_BUILDABLE_SLOPE_PCT = 8.0
MIN_PARCEL_SQM = 25000.0


def normalise_weights(weights: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update({k: v for k, v in weights.items() if k in w and v is not None})
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


def score_components(candidate: Candidate, max_capacity: float) -> Dict[str, float]:
    """Each component is 0-1, higher meaning more headroom against the gate."""
    cap = max_capacity or 1.0
    return {
        "hazard_headroom": round(max(0.0, 1.0 - candidate.composite_risk), 4),
        "slope_headroom": round(max(0.0, 1.0 - (candidate.terrain_slope_pct / MAX_BUILDABLE_SLOPE_PCT)), 4),
        "parcel_adequacy": round(min(1.0, candidate.parcel_area_sqm / MIN_PARCEL_SQM), 4),
        "capacity_share": round(candidate.capacity_units / cap, 4),
    }


def score_candidates(
    candidates: List[Candidate],
    weights: Optional[Dict[str, float]] = None
) -> Dict[str, Dict[str, float]]:
    """
    Scores every candidate in place and returns each one's components.
    A rejected site scores 0: it is not a ranking, it is out.
    """
    w = normalise_weights(weights)
    max_capacity = max((c.capacity_units for c in candidates), default=1.0) or 1.0
    components_by_id: Dict[str, Dict[str, float]] = {}

    for cand in candidates:
        components = score_components(cand, max_capacity)
        components_by_id[cand.id] = components
        cand.score_components = components
        cand.suitability_score = (
            round(sum(components[k] * w[k] for k in components), 4)
            if cand.passed_screening else 0.0
        )

    return components_by_id
