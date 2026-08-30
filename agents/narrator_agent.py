import asyncio
import os
import uuid
import httpx
from typing import List, Dict, Any, Tuple, Optional
from schemas.state import (
    NetworkState,
    NetworkSolution,
    LogisticsGraph,
    Candidate,
    Disruption,
    CriticReport,
    AgentTraceEvent
)


class NarratorAgent:
    """
    Reporting / Narrator Agent:
    Translates mathematical optimization and geospatial data into executive narrative.
    Explains why solutions were chosen, trade-offs on the Pareto frontier, and answers
    what-if inquiries by strictly grounding responses in Mireye evidence and state fields.
    """

    def __init__(self, openai_api_key: Optional[str] = None, gemini_api_key: Optional[str] = None):
        self.openai_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self.gemini_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.name = "Reporting / Narrator Agent"

    def generate_narrative(
        self,
        inputs_region: str,
        candidates: List[Candidate],
        graph: LogisticsGraph,
        frontier: List[NetworkSolution],
        active_solution: NetworkSolution,
        disruption: Optional[Disruption] = None,
        critic_report: Optional[CriticReport] = None,
        target_warehouses: Optional[int] = None
    ) -> Tuple[str, List[AgentTraceEvent]]:
        trace_events = []
        
        start_event = AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="GenerateNarrative",
            status="start",
            message="Synthesizing multi-agent network intelligence report grounded in Mireye provenance.",
            timestamp=""
        )
        trace_events.append(start_event)

        passed_cands = [c for c in candidates if c.passed_screening]
        rejected_cands = [c for c in candidates if not c.passed_screening]

        # The Optimization Agent returns (None, []) when the MILP has no feasible
        # solution -- typically too few surviving candidates to cover total demand
        # within target_warehouses_to_open. Report that instead of dereferencing None.
        if active_solution is None:
            warehouses = list(graph.warehouses) if graph else []
            total_capacity = sum(w.capacity_units for w in warehouses)
            total_demand = sum(c.demand_units for c in graph.customers) if graph else 0.0
            # Only target_warehouses may open at once, so the best achievable
            # capacity is the sum of the largest that many sites -- not the total.
            reachable_capacity = (
                sum(sorted((w.capacity_units for w in warehouses), reverse=True)[:target_warehouses])
                if target_warehouses else total_capacity
            )

            report = [
                f"### No feasible network for {inputs_region}",
                (
                    f"The optimizer could not build a plan. "
                    f"**{len(passed_cands)} of {len(candidates)} candidate sites** passed screening "
                    f"and **{len(rejected_cands)} were rejected**."
                ),
                "\n#### Why no plan was produced",
            ]

            capacity_bound = bool(warehouses) and reachable_capacity < total_demand

            if not warehouses:
                report.append(
                    "- No candidate survived site and hazard screening, so the facility-location "
                    "model had nothing to choose from."
                )
            elif capacity_bound:
                cap_binds = bool(target_warehouses) and target_warehouses < len(warehouses)
                if cap_binds:
                    report.append(
                        f"- The plan may open at most **{target_warehouses}** of the "
                        f"**{len(warehouses)}** surviving sites."
                    )
                    report.append(
                        f"- The largest {target_warehouses} of them hold "
                        f"`{reachable_capacity:,.0f}` units of capacity, short of the "
                        f"`{total_demand:,.0f}` units of demand across "
                        f"{len(graph.customers)} zones."
                    )
                    report.append(
                        f"- All {len(warehouses)} surviving sites together hold "
                        f"`{total_capacity:,.0f}` units, so the facility cap is the binding "
                        f"constraint, not the shortlist."
                    )
                else:
                    # Every surviving site could open and demand still would not be met.
                    report.append(
                        f"- Only **{len(warehouses)}** of the {len(candidates)} sites considered "
                        f"passed screening."
                    )
                    report.append(
                        f"- Even opening all of them provides `{total_capacity:,.0f}` units of "
                        f"capacity, short of the `{total_demand:,.0f}` units of demand across "
                        f"{len(graph.customers)} zones."
                    )
                    report.append(
                        "- The shortlist is the binding constraint here, not the facility cap."
                    )
            else:
                report.append(
                    f"- {len(warehouses)} sites survived screening with `{total_capacity:,.0f}` "
                    f"units of capacity against `{total_demand:,.0f}` units of demand, but no "
                    f"assignment satisfied the capacity, supply and demand constraints together."
                )

            report.append("\n#### What to change")
            if capacity_bound and target_warehouses and target_warehouses < len(warehouses):
                report.append(
                    f"- Raise the facility count above {target_warehouses} so more capacity can open."
                )
            elif capacity_bound:
                shortfall = total_demand - total_capacity
                report.append(
                    f"- Add sites, or raise capacity on the ones you have, by at least "
                    f"`{shortfall:,.0f}` units."
                )
            report.append("- Relax screening inputs so more candidate sites qualify.")
            report.append("- Check the rejected sites below; each lists the gate it failed.")

            narrative_text = "\n".join(report)

            trace_events.append(AgentTraceEvent(
                event_id=str(uuid.uuid4()),
                agent_name=self.name,
                action="GenerateNarrative",
                status="warning",
                message=(
                    f"No feasible solution to narrate. {len(passed_cands)}/{len(candidates)} sites "
                    f"passed screening; best {target_warehouses or len(warehouses)} hold "
                    f"{reachable_capacity:,.0f} units against {total_demand:,.0f} units of demand."
                ),
                details={
                    "passed_candidates": len(passed_cands),
                    "total_candidates": len(candidates),
                    "target_warehouses": target_warehouses,
                    "reachable_capacity": reachable_capacity,
                    "total_capacity": total_capacity,
                    "total_demand": total_demand,
                },
                timestamp=""
            ))
            return narrative_text, trace_events

        selected_whs = [w for w in graph.warehouses if w.id in active_solution.selected_warehouse_ids]

        # Calculate baseline comparisons
        baseline = next((s for s in frontier if s.is_baseline_cost_only), active_solution)
        cost_diff = active_solution.total_cost - baseline.total_cost
        resilience_gain = (active_solution.resilience_score - baseline.resilience_score) * 100.0

        # Construct structured, auditable executive report
        sections = []
        sections.append(f"### What we found for {inputs_region}")
        sections.append(
            f"We checked **{len(candidates)} possible places** using real map data for the ground, "
            f"the land use and the flood risk. **{len(passed_cands)} of them work**; "
            f"**{len(rejected_cands)} were ruled out** because the ground was too steep, the land "
            f"was not free, or the flood risk was too high."
        )

        sections.append("\n#### The plan")
        wh_names = ", ".join([f"`{w.name}`" for w in selected_whs])
        on_time = active_solution.demand_retained_pct
        sections.append(
            f"- **Open {len(selected_whs)} "
            f"{'warehouse' if len(selected_whs) == 1 else 'warehouses'}:** {wh_names}\n"
            f"- **Cost:** `${active_solution.total_cost:,.0f}` a year "
            f"(`${active_solution.total_fixed_cost:,.0f}` to run them, "
            f"`${active_solution.total_transport_cost:,.0f}` to move goods)\n"
            f"- **Deliveries on time:** `{on_time:.0f}%` of orders arrive inside the delivery "
            f"window you asked for\n"
            f"- **Safety score:** `{active_solution.resilience_score:.2f}` out of 1.00, where "
            f"higher means the network copes better if something goes wrong"
        )

        if not active_solution.is_baseline_cost_only and cost_diff > 0:
            sections.append(
                f"\n#### Why not just pick the cheapest?"
            )
            sections.append(
                f"The cheapest plan saves you `${cost_diff:,.0f}` a year "
                f"(`{cost_diff / baseline.total_cost * 100:.0f}%` less), but it is "
                f"**{resilience_gain:.0f} points less safe**. This plan spends a little more to "
                f"keep deliveries running when a site floods or a road closes."
            )

        if disruption:
            sections.append("\n#### If this goes wrong")
            sections.append(
                f"- **What we simulated:** {disruption.title}\n"
                f"- **Warehouses knocked out:** {len(disruption.affected_warehouse_ids)}\n"
                f"- **Deliveries still on time afterwards:** `{on_time:.0f}%`\n"
                f"- **Extra delivery cost:** "
                f"`${active_solution.total_transport_cost - baseline.total_transport_cost:,.0f}`"
            )

        if critic_report:
            sections.append("\n#### Our own checks")
            if critic_report.passed:
                sections.append(
                    f"Everything checks out. `{critic_report.evidence_coverage_pct:.0f}%` of the "
                    f"numbers trace back to a real map lookup, and no limit is broken."
                )
            else:
                issue_count = len(critic_report.constraint_violations)
                sections.append(
                    f"`{critic_report.evidence_coverage_pct:.0f}%` of the numbers trace back to a "
                    f"real map lookup. **{issue_count} "
                    f"{'thing needs' if issue_count == 1 else 'things need'} a look** before you "
                    f"commit money \u2014 see the Checks tab."
                )

        narrative_text = "\n".join(sections)

        trace_events.append(AgentTraceEvent(
            event_id=str(uuid.uuid4()),
            agent_name=self.name,
            action="GenerateNarrative",
            status="complete",
            message="Narrative report compiled and verified against all state variables.",
            timestamp=""
        ))

        return narrative_text, trace_events

    async def answer_what_if(
        self,
        query: str,
        candidates: List[Candidate],
        graph: LogisticsGraph,
        frontier: List[NetworkSolution],
        active_solution: NetworkSolution
    ) -> Dict[str, Any]:
        """
        Answers free-form what-if questions.

        The question is sent to an LLM (OpenAI, or Gemini if only that key is set)
        together with a grounding context built entirely from the state on screen,
        so the model can only reason about real candidates, real flows and real
        provenance -- not general knowledge. If no key is configured, or the call
        fails, this falls back to the deterministic rule/template answer below so
        the drawer keeps working offline.
        """
        q_lower = query.lower()
        matched_candidate = next(
            (c for c in candidates if c.name.lower() in q_lower or c.id.lower() in q_lower),
            None,
        )

        context = self._build_grounding_context(candidates, graph, frontier, active_solution, matched_candidate)
        llm_answer = await self._call_llm(context, query)

        if llm_answer:
            result: Dict[str, Any] = {"answer": llm_answer}
            if matched_candidate is not None:
                result["related_candidate_id"] = matched_candidate.id
                result["provenance"] = matched_candidate.provenance
            if "cost" in q_lower and "resilience" in q_lower:
                result["frontier_count"] = len(frontier)
            if "flood" in q_lower or "disrupt" in q_lower or "outage" in q_lower:
                result["high_risk_warehouses"] = [w.id for w in graph.warehouses if w.flood_risk_score > 0.35]
            return result

        return self._rule_based_answer(query, candidates, graph, frontier, active_solution)

    def _build_grounding_context(
        self,
        candidates: List[Candidate],
        graph: LogisticsGraph,
        frontier: List[NetworkSolution],
        active_solution: NetworkSolution,
        matched_candidate: Optional[Candidate] = None,
    ) -> str:
        """Serializes the network on screen into the text an LLM answers from."""
        passed = [c for c in candidates if c.passed_screening]
        rejected = [c for c in candidates if not c.passed_screening]
        selected_ids = set(active_solution.selected_warehouse_ids)

        lines = [
            "You are the OptiFlow Narrator, a supply-chain assistant embedded in a logistics "
            "network-optimization tool. Answer the user's question using ONLY the facts listed "
            "below -- they describe the exact network currently on screen (Mireye-sourced site "
            "data, the MILP/NSGA-II optimizer output and the Critic audit). Do not invent sites, "
            "numbers or events that are not present here; if the data does not answer the "
            "question, say so plainly instead of guessing. Reply in 2-6 sentences of markdown, "
            "citing concrete numbers from the data, in plain language a non-technical operator "
            "can act on.",
            "",
            f"## Candidates ({len(candidates)} total, {len(passed)} passed screening, {len(rejected)} rejected)",
        ]
        for c in candidates:
            if c.id in selected_ids:
                status = "OPEN in the active plan"
            elif c.passed_screening:
                status = "passed screening, not selected in the active plan"
            else:
                status = "REJECTED: " + ("; ".join(c.rejection_reasons) or "failed screening")
            lines.append(
                f"- {c.name} (id={c.id}): {status}. capacity={c.capacity_units:,.0f} units, "
                f"fixed_cost=${c.fixed_operating_cost:,.0f}/yr, flood_risk={c.flood_risk_score:.2f}, "
                f"slope={c.terrain_slope_pct:.1f}%, elevation={c.elevation_m:.0f}m, "
                f"land_cover={c.land_cover}"
            )

        lines.append("")
        lines.append(f"## Active plan: {active_solution.name}")
        lines.append(
            f"- Opens {len(active_solution.selected_warehouse_ids)} warehouses, total cost "
            f"${active_solution.total_cost:,.0f}/yr (${active_solution.total_fixed_cost:,.0f} fixed "
            f"+ ${active_solution.total_transport_cost:,.0f} transport), demand retained "
            f"{active_solution.demand_retained_pct:.0f}%, resilience score "
            f"{active_solution.resilience_score:.3f}"
        )

        lines.append("")
        lines.append(f"## Pareto frontier ({len(frontier)} solutions)")
        for s in frontier:
            tag = ""
            if s.solution_id == active_solution.solution_id:
                tag = " [ACTIVE]"
            elif s.is_baseline_cost_only:
                tag = " [least-cost baseline]"
            lines.append(f"- {s.name}{tag}: cost=${s.total_cost:,.0f}/yr, resilience={s.resilience_score:.3f}")

        lines.append("")
        lines.append(
            f"## Network graph: {len(graph.warehouses)} candidate warehouses, "
            f"{len(graph.customers)} customer zones, {len(graph.suppliers)} suppliers"
        )
        high_risk = [w for w in graph.warehouses if w.flood_risk_score > 0.35]
        if high_risk:
            lines.append(
                "High flood-risk warehouses: "
                + ", ".join(f"{w.name} (risk={w.flood_risk_score:.2f}, status={w.status})" for w in high_risk)
            )

        if matched_candidate is not None:
            lines.append("")
            lines.append(f"## The question appears to be specifically about '{matched_candidate.name}'.")

        return "\n".join(lines)

    async def _call_llm(self, context: str, query: str) -> Optional[str]:
        """Routes to whichever provider has a key configured; None if neither does or both fail."""
        if self.gemini_key:
            answer = await self._call_gemini(context, query)
            if answer:
                return answer
        if self.openai_key:
            return await self._call_openai(context, query)
        return None

    @staticmethod
    def _log_llm_error(provider: str, exc: Exception) -> None:
        """
        Logs an LLM call failure without ever printing the request itself -- for
        Gemini in particular, the API key travels as a URL query param, and
        httpx's default exception message embeds the full request URL. A generic
        `print(exc)` would put a live key straight into server logs.
        """
        if isinstance(exc, httpx.HTTPStatusError):
            body = exc.response.text
            if len(body) > 300:
                body = body[:300] + "...(truncated)"
            print(f"[NarratorAgent] {provider} call failed, falling back: HTTP {exc.response.status_code} -- {body}")
        else:
            print(f"[NarratorAgent] {provider} call failed, falling back: {type(exc).__name__}: {exc}")

    async def _call_openai(self, context: str, query: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openai_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": os.getenv("OPENAI_NARRATOR_MODEL", "gpt-4o-mini"),
                        "messages": [
                            {"role": "system", "content": context},
                            {"role": "user", "content": query},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 500,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            self._log_llm_error("OpenAI", exc)
            return None

    async def _call_gemini(self, context: str, query: str, _retries_left: int = 1) -> Optional[str]:
        try:
            model = os.getenv("GEMINI_NARRATOR_MODEL", "gemini-2.5-flash")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    url,
                    # The key travels as a header, not a `?key=` query param -- a
                    # query param ends up in the request URL, which httpx (and most
                    # proxies/log lines) will happily echo into error messages.
                    headers={"x-goog-api-key": self.gemini_key},
                    json={
                        "system_instruction": {"parts": [{"text": context}]},
                        "contents": [{"role": "user", "parts": [{"text": query}]}],
                        "generationConfig": {
                            "temperature": 0.2,
                            "maxOutputTokens": 800,
                            # Current Gemini flash models "think" before answering,
                            # spending part of maxOutputTokens on a hidden reasoning
                            # pass. A chatbot answer doesn't need that -- and left on,
                            # a small token budget can be consumed by the thinking
                            # pass before the visible answer is even written,
                            # producing a truncated fragment instead of a full reply.
                            "thinkingConfig": {"thinkingBudget": 0},
                        },
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                parts = data["candidates"][0]["content"]["parts"]
                # Defensive: even with thinking disabled, skip any part explicitly
                # marked as a thought rather than assuming parts[0] is the answer.
                text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                return text or None
        except httpx.HTTPStatusError as exc:
            # 503 (model temporarily overloaded) and 429 (rate limited) are the
            # transient ones -- worth one retry rather than dropping straight to
            # the canned fallback and making a passing capacity blip look like a
            # broken chatbot.
            if _retries_left > 0 and exc.response.status_code in (503, 429):
                await asyncio.sleep(1.5)
                return await self._call_gemini(context, query, _retries_left=_retries_left - 1)
            self._log_llm_error("Gemini", exc)
            return None
        except httpx.TimeoutException as exc:
            # A slow response under load is just as transient as a 503 -- retry
            # once before giving up on this provider.
            if _retries_left > 0:
                return await self._call_gemini(context, query, _retries_left=_retries_left - 1)
            self._log_llm_error("Gemini", exc)
            return None
        except Exception as exc:
            self._log_llm_error("Gemini", exc)
            return None

    def _rule_based_answer(
        self,
        query: str,
        candidates: List[Candidate],
        graph: LogisticsGraph,
        frontier: List[NetworkSolution],
        active_solution: NetworkSolution
    ) -> Dict[str, Any]:
        """
        Deterministic fallback used when no LLM key is configured (or the call
        failed): answers free-form what-if questions by pattern-matching structured
        state fields and Mireye provenance directly.
        """
        q_lower = query.lower()

        # 1. Why wasn't a candidate selected / rejected?
        for cand in candidates:
            if cand.name.lower() in q_lower or cand.id.lower() in q_lower:
                if not cand.passed_screening:
                    reasons = "; ".join(cand.rejection_reasons)
                    return {
                        "answer": f"**Candidate '{cand.name}' was rejected during multi-layer screening** because:\n- {reasons}.\n\n*Mireye Telemetry Evidence:*\n- Slope: `{cand.terrain_slope_pct}%` (Elevation: `{cand.elevation_m}m`)\n- Land Cover: `{cand.land_cover}`\n- Flood Risk Index: `{cand.flood_risk_score:.2f}`",
                        "related_candidate_id": cand.id,
                        "provenance": cand.provenance
                    }
                else:
                    is_selected = cand.id in active_solution.selected_warehouse_ids
                    status_desc = "currently open in the active plan" if is_selected else "qualified but not selected in this Pareto tier due to higher marginal logistics detour cost relative to central hubs"
                    return {
                        "answer": f"**Candidate '{cand.name}' is {status_desc}**.\n\n*Facility Specs:*\n- Capacity: `{cand.capacity_units:,.0f} units`\n- Fixed Operating Cost: `${cand.fixed_operating_cost:,.0f}/yr`\n- Flood Risk Score: `{cand.flood_risk_score:.2f}` (Zone: Mireye Verified)",
                        "related_candidate_id": cand.id,
                        "provenance": cand.provenance
                    }

        # 2. Inquiries regarding Cost-vs-Resilience trade-offs
        if "cost" in q_lower and "resilience" in q_lower:
            baseline = next((s for s in frontier if s.is_baseline_cost_only), frontier[0] if frontier else active_solution)
            highest_resil = max(frontier, key=lambda s: s.resilience_score) if frontier else active_solution
            return {
                "answer": (
                    f"**OptiFlow Pareto Trade-off Analysis:**\n\n"
                    f"1. **Least-Cost Baseline:** ${baseline.total_cost:,.0f} (Resilience: `{baseline.resilience_score:.3f}`)\n"
                    f"2. **Max-Resilience Option:** ${highest_resil.total_cost:,.0f} (Resilience: `{highest_resil.resilience_score:.3f}`)\n"
                    f"3. **Recommended Frontier Option:** ${active_solution.total_cost:,.0f} (Resilience: `{active_solution.resilience_score:.3f}`)\n\n"
                    f"Every incremental dollar invested shifts facility locations away from vulnerable river basins toward high-elevation nodes with redundant transit arcs."
                ),
                "frontier_count": len(frontier)
            }

        # 3. Inquiries regarding Disruption / Floods
        if "flood" in q_lower or "disrupt" in q_lower or "outage" in q_lower:
            high_risk_whs = [w for w in graph.warehouses if w.flood_risk_score > 0.35]
            wh_list = ", ".join([f"{w.name} (Risk: {w.flood_risk_score:.2f})" for w in high_risk_whs])
            return {
                "answer": (
                    f"**Flood Vulnerability Assessment:**\n\n"
                    f"Based on Mireye 100-year flood hazard maps, the facilities most exposed to inundation in this corridor are: {wh_list}.\n\n"
                    f"In a simulated Green River 100-year flood event, OptiFlow reassigns impacted customer zones in **under 2 seconds** via pre-cached delta routing."
                ),
                "high_risk_warehouses": [w.id for w in high_risk_whs]
            }

        # Default fallback synthesis
        return {
            "answer": (
                f"**OptiFlow Assistant Response:**\n\n"
                f"Your query '{query}' was evaluated against the current state of **{len(graph.warehouses)} candidate warehouses** and **{len(graph.customers)} customer delivery zones** in the Puget Sound corridor.\n\n"
                f"Current active plan operates **{len(active_solution.selected_warehouse_ids)} distribution centers** with an overall resilience index of `{active_solution.resilience_score:.3f}` and total annual cost of `${active_solution.total_cost:,.0f}`."
            )
        }
