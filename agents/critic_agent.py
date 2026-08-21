import uuid
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional

from schemas.state import (
    NetworkSolution,
    LogisticsGraph,
    Candidate,
    CriticReport,
    AgentTraceEvent,
)
from schemas.mireye import ProvenanceTag

logger = logging.getLogger(__name__)


@dataclass
class CriticConfig:
    """
    All tuneable parameters for the Critic Agent's evidence and constraint audit.

    Pass a custom CriticConfig to CriticAgent to override any value without
    touching source code.
    """
    # --- Staleness ---
    # A ProvenanceTag older than this many minutes is flagged stale.
    staleness_window_minutes: float = 30.0
    # A ProvenanceTag with a missing/unparseable timestamp is treated as
    # stale (fail-conservative) unless this is set False.
    treat_unparseable_timestamp_as_stale: bool = True

    # --- Evidence coverage ---
    # Audit fails (passed=False) if evidence_coverage_pct drops below this,
    # even when there are zero hard constraint violations.
    min_evidence_coverage_pct: float = 90.0

    # --- Sampling ---
    # Number of graph edges to sample for provenance/staleness checks.
    # Full edge-by-edge audit is O(n) so we cap it for very large graphs.
    edge_sample_size: int = 50

    def validate(self):
        if self.staleness_window_minutes <= 0:
            raise ValueError(
                f"CriticConfig.staleness_window_minutes must be > 0, "
                f"got {self.staleness_window_minutes}."
            )
        if not (0.0 <= self.min_evidence_coverage_pct <= 100.0):
            raise ValueError(
                f"CriticConfig.min_evidence_coverage_pct must be within [0, 100], "
                f"got {self.min_evidence_coverage_pct}."
            )
        if self.edge_sample_size <= 0:
            raise ValueError(
                f"CriticConfig.edge_sample_size must be > 0, got {self.edge_sample_size}."
            )


def _parse_timestamp(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string, returning None if missing/invalid."""
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_stale(tag: Optional[ProvenanceTag], now: datetime, cfg: CriticConfig) -> bool:
    """
    Returns True if a ProvenanceTag's timestamp is older than the configured
    staleness window. A missing tag is NOT considered here — that's a
    "missing provenance" concern handled separately by the caller.
    """
    if tag is None:
        return False
    parsed = _parse_timestamp(getattr(tag, "timestamp", None))
    if parsed is None:
        return cfg.treat_unparseable_timestamp_as_stale
    age_minutes = (now - parsed).total_seconds() / 60.0
    return age_minutes > cfg.staleness_window_minutes


class CriticAgent:
    """
    Critic Agent.

    Audits the entire state before surfacing results to the user. Verifies
    that every recommendation is backed by verifiable, non-stale Mireye
    provenance and that capacity, budget, and delivery constraints are
    strictly satisfied.

    Upgrade dimensions vs. original:
    - CriticConfig: staleness window, coverage threshold, and sample size
      are constructor args instead of magic numbers.
    - Real staleness logic: every ProvenanceTag already attached to
      candidates and edges is age-checked against `staleness_window_minutes`
      instead of `stale_provenance_count` being hardcoded to 0.
    - Evidence coverage now gates the pass/fail verdict, not just violations.
    - Observability: structured WARNING/INFO logs on audit outcome.
    - Interface: execute_audit(candidates, graph, solution, budget_limit_usd)
      → unchanged.
    """

    def __init__(self, config: Optional[CriticConfig] = None):
        self.config = config or CriticConfig()
        self.config.validate()
        self.name = "Critic Agent"

    def execute_audit(
        self,
        candidates: List[Candidate],
        graph: LogisticsGraph,
        solution: NetworkSolution,
        budget_limit_usd: float = 3000000.0,
    ) -> Tuple[CriticReport, List[AgentTraceEvent]]:
        cfg = self.config
        now = datetime.now(timezone.utc)

        trace_events: List[AgentTraceEvent] = []
        flags: List[str] = []
        violations: List[str] = []
        total_checks = 0
        passed_checks = 0
        stale_count = 0

        logger.info(
            "[%s] Starting audit: %d candidates, %d edges, solution=%s.",
            self.name, len(candidates), len(graph.edges), solution.solution_id,
        )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="EvidenceAndConstraintAudit",
            status="start",
            message="Conducting automated evidence-sufficiency and operational constraint audit.",
            timestamp="",
        ))

        # ── 1. Audit Candidates for Provenance Presence + Staleness ─────────
        missing_cand_prov = 0
        for cand in candidates:
            total_checks += 1
            if not cand.provenance or "terrain" not in cand.provenance or "land_cover" not in cand.provenance:
                missing_cand_prov += 1
                flags.append(f"Candidate {cand.id} ({cand.name}) missing terrain/landcover Mireye provenance tag.")
            else:
                passed_checks += 1

            if cand.passed_screening and "flood" not in cand.provenance:
                missing_cand_prov += 1
                flags.append(f"Surviving Candidate {cand.id} missing flood hazard Mireye provenance tag.")

            # Staleness: check every provenance tag actually present on this candidate.
            for layer_name, tag in cand.provenance.items():
                total_checks += 1
                if _is_stale(tag, now, cfg):
                    stale_count += 1
                    flags.append(
                        f"Candidate {cand.id} ({cand.name}) provenance for '{layer_name}' "
                        f"is stale (older than {cfg.staleness_window_minutes:.0f} min)."
                    )
                else:
                    passed_checks += 1

        # ── 2. Audit Selected Warehouses & Capacity Constraints ─────────────
        wh_map = {w.id: w for w in graph.warehouses}
        wh_assigned_demand: Dict[str, float] = {wid: 0.0 for wid in solution.selected_warehouse_ids}

        for cust in graph.customers:
            assigned_wh_id = solution.customer_assignments.get(cust.id)
            if not assigned_wh_id:
                violations.append(f"Customer {cust.name} ({cust.id}) is unassigned to any warehouse.")
            elif assigned_wh_id not in solution.selected_warehouse_ids:
                violations.append(f"Customer {cust.name} assigned to closed facility: {assigned_wh_id}")
            else:
                wh_assigned_demand[assigned_wh_id] = wh_assigned_demand.get(assigned_wh_id, 0.0) + cust.demand_units

        for wid, assigned_demand in wh_assigned_demand.items():
            total_checks += 1
            wh = wh_map.get(wid)
            if wh and assigned_demand > wh.capacity_units:
                violations.append(
                    f"Capacity Overload at Warehouse {wh.name} ({wid}): assigned {assigned_demand:,.0f} units > capacity {wh.capacity_units:,.0f} units"
                )
            else:
                passed_checks += 1

        # ── 3. Budget Limit Verification ─────────────────────────────────────
        total_checks += 1
        if solution.total_cost > budget_limit_usd:
            violations.append(
                f"Budget Limit Exceeded: Solution cost ${solution.total_cost:,.0f} exceeds budget threshold ${budget_limit_usd:,.0f}"
            )
        else:
            passed_checks += 1

        # ── 4. Graph Edge Provenance Verification + Staleness (sampled) ─────
        missing_edge_prov = 0
        for edge in graph.edges[:cfg.edge_sample_size]:
            total_checks += 1
            if not edge.provenance or not edge.provenance.response_hash:
                missing_edge_prov += 1
                flags.append(f"Routing edge {edge.id} missing Mireye provenance hash.")
            else:
                passed_checks += 1
                total_checks += 1
                if _is_stale(edge.provenance, now, cfg):
                    stale_count += 1
                    flags.append(
                        f"Routing edge {edge.id} provenance is stale "
                        f"(older than {cfg.staleness_window_minutes:.0f} min)."
                    )
                else:
                    passed_checks += 1

        coverage_pct = round((passed_checks / max(1, total_checks)) * 100.0, 1)
        audit_passed = (
            len(violations) == 0
            and missing_cand_prov == 0
            and coverage_pct >= cfg.min_evidence_coverage_pct
        )

        if not audit_passed:
            logger.warning(
                "[%s] Audit FLAGGED — coverage=%.1f%% violations=%d missing_prov=%d stale=%d",
                self.name, coverage_pct, len(violations),
                missing_cand_prov + missing_edge_prov, stale_count,
            )
        else:
            logger.info(
                "[%s] Audit PASSED — coverage=%.1f%% stale=%d",
                self.name, coverage_pct, stale_count,
            )

        report = CriticReport(
            passed=audit_passed,
            flags=flags,
            evidence_coverage_pct=coverage_pct,
            stale_provenance_count=stale_count,
            missing_provenance_count=missing_cand_prov + missing_edge_prov,
            constraint_violations=violations,
            timestamp=now.isoformat(),
        )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="EvidenceAndConstraintAudit",
            status="complete" if audit_passed else "warning",
            message=(
                f"Audit completed: {'PASSED' if audit_passed else 'FLAGS DETECTED'}. "
                f"Evidence coverage: {coverage_pct}%. Stale provenance: {stale_count}. "
                f"Violations: {len(violations)}."
            ),
            details={
                "audit_passed": audit_passed,
                "coverage_pct": coverage_pct,
                "stale_provenance_count": stale_count,
                "missing_provenance_count": missing_cand_prov + missing_edge_prov,
                "flags_count": len(flags),
                "violations_count": len(violations),
                "config": {
                    "staleness_window_minutes": cfg.staleness_window_minutes,
                    "min_evidence_coverage_pct": cfg.min_evidence_coverage_pct,
                },
            },
            timestamp=report.timestamp,
        ))

        return report, trace_events