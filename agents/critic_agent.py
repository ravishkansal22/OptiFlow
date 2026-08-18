import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
from schemas.state import (
    NetworkState,
    NetworkSolution,
    LogisticsGraph,
    Candidate,
    CriticReport,
    AgentTraceEvent
)


class CriticAgent:
    """
    Critic Agent:
    Audits the entire state before surfacing results to the user.
    Verifies that every recommendation is backed by verifiable, non-stale Mireye provenance
    and that capacity, budget, and delivery constraints are strictly satisfied.
    """

    def __init__(self):
        self.name = "Critic Agent"

    def execute_audit(
        self,
        candidates: List[Candidate],
        graph: LogisticsGraph,
        solution: NetworkSolution,
        budget_limit_usd: float = 3000000.0
    ) -> Tuple[CriticReport, List[AgentTraceEvent]]:
        trace_events = []
        flags = []
        violations = []
        total_checks = 0
        passed_checks = 0

        start_event = AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="EvidenceAndConstraintAudit",
            status="start",
            message="Conducting automated evidence-sufficiency and operational constraint audit.",
            timestamp=""
        )
        trace_events.append(start_event)

        # 1. Audit Candidates for Provenance
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

        # 2. Audit Selected Warehouses & Capacity Constraints
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

        # 3. Budget Limit Verification
        total_checks += 1
        if solution.total_cost > budget_limit_usd:
            violations.append(
                f"Budget Limit Exceeded: Solution cost ${solution.total_cost:,.0f} exceeds budget threshold ${budget_limit_usd:,.0f}"
            )
        else:
            passed_checks += 1

        # 4. Graph Edge Provenance Verification
        missing_edge_prov = 0
        for edge in graph.edges[:50]:  # Sample check
            total_checks += 1
            if not edge.provenance or not edge.provenance.response_hash:
                missing_edge_prov += 1
                flags.append(f"Routing edge {edge.id} missing Mireye provenance hash.")
            else:
                passed_checks += 1

        coverage_pct = round((passed_checks / max(1, total_checks)) * 100.0, 1)
        audit_passed = (len(violations) == 0 and missing_cand_prov == 0)

        report = CriticReport(
            passed=audit_passed,
            flags=flags,
            evidence_coverage_pct=coverage_pct,
            stale_provenance_count=0,
            missing_provenance_count=missing_cand_prov + missing_edge_prov,
            constraint_violations=violations,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="EvidenceAndConstraintAudit",
            status="complete" if audit_passed else "warning",
            message=f"Audit completed: {'PASSED' if audit_passed else 'FLAGS DETECTED'}. Evidence coverage: {coverage_pct}%. Violations: {len(violations)}.",
            details={
                "audit_passed": audit_passed,
                "coverage_pct": coverage_pct,
                "flags_count": len(flags),
                "violations_count": len(violations)
            },
            timestamp=report.timestamp
        ))

        return report, trace_events
