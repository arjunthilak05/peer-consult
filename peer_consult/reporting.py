"""Human-readable Markdown report generator for Council runs (discuss, plan, execute)."""
from __future__ import annotations

from typing import Any


def render_council_markdown(run: dict[str, Any], stage_outputs: list[dict[str, Any]]) -> str:
    """Render a comprehensive Markdown report from a persisted council run and its stage outputs."""
    lines: list[str] = []
    run_id = run.get("run_id", "unknown")
    mode = run.get("mode", "discuss")
    status = run.get("status", "UNKNOWN")
    question = run.get("question", "")
    chair = run.get("chair", "claude")
    writer = run.get("writer") or "none"

    lines.append(f"# Three-Agent Council Report — `{run_id}`")
    lines.append("")
    lines.append("## 1. Run Overview")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| **Run ID** | `{run_id}` |")
    lines.append(f"| **Task ID** | `{run.get('task_id', '')}` |")
    lines.append(f"| **Mode** | `{mode}` |")
    lines.append(f"| **Status** | `{status}` |")
    lines.append(f"| **Caller** | `{run.get('caller', '')}` |")
    lines.append(f"| **Synthesis Chair** | `{chair}` |")
    lines.append(f"| **Selected Writer** | `{writer}` |")
    lines.append(f"| **Created At** | `{run.get('created_at', '')}` |")
    lines.append(f"| **Updated At** | `{run.get('updated_at', '')}` |")
    if run.get("worktree_path"):
        lines.append(f"| **Git Worktree** | `{run['worktree_path']}` |")
    if run.get("base_revision"):
        lines.append(f"| **Base Revision** | `{run['base_revision']}` |")
    lines.append("")
    lines.append("### Question / Objective")
    lines.append("")
    lines.append(f"> {question}")
    lines.append("")

    # Stage telemetry table
    if stage_outputs:
        lines.append("## 2. Agent Telemetry & Model Verification")
        lines.append("")
        lines.append("| Stage | Attempt | Agent | Anon Label | Requested Model | Reported Model | Effort | Elapsed (s) | Status |")
        lines.append("|---|---:|---|---|---|---|---|---:|---|")
        for so in stage_outputs:
            lines.append(
                f"| `{so.get('stage')}` | {so.get('attempt', 1)} | `{so.get('agent')}` | "
                f"{so.get('anonymous_label') or '—'} | `{so.get('model_requested') or '—'}` | "
                f"`{so.get('model_reported') or 'unreported'}` | `{so.get('effort_requested') or '—'}` | "
                f"{so.get('elapsed_seconds') if so.get('elapsed_seconds') is not None else '—'} | `{so.get('status')}` |"
            )
        lines.append("")

    # Proposals
    proposals = [s for s in stage_outputs if s.get("stage") == "proposal" and s.get("status") == "ok"]
    if proposals:
        lines.append("## 3. Stage 1 — Independent Proposals")
        lines.append("")
        anon_map = run.get("anonymization_map") or {}
        if anon_map:
            mapping_str = ", ".join(f"**{lbl}** = `{ag}`" for lbl, ag in sorted(anon_map.items()))
            lines.append(f"*Anonymization Mapping (revealed post-critique):* {mapping_str}")
            lines.append("")
        for p in proposals:
            ag = p.get("agent")
            lbl = p.get("anonymous_label") or ag
            out = p.get("output") or {}
            lines.append(f"### {lbl} (`{ag}` — confidence: `{out.get('confidence', 'unknown')}`)")
            lines.append("")
            lines.append(f"**Summary:** {out.get('summary', '')}")
            lines.append("")
            lines.append(f"**Assessment:** {out.get('assessment', '')}")
            lines.append("")
            lines.append(f"**Recommendation:** {out.get('recommendation', '')}")
            lines.append("")
            if out.get("affected_files"):
                lines.append("**Affected Files:** " + ", ".join(f"`{f}`" for f in out["affected_files"]))
                lines.append("")
            if out.get("implementation_steps"):
                lines.append("**Implementation Steps:**")
                for idx, st in enumerate(out["implementation_steps"], 1):
                    lines.append(f"{idx}. {st}")
                lines.append("")
            if out.get("risks"):
                lines.append("**Risks:**")
                for r in out["risks"]:
                    lines.append(f"- {r}")
                lines.append("")

    # Cross-Critiques
    critiques = [s for s in stage_outputs if s.get("stage") == "critique" and s.get("status") == "ok"]
    if critiques:
        lines.append("## 4. Stage 2 — Anonymized Cross-Critiques")
        lines.append("")
        for c in critiques:
            ag = c.get("agent")
            out = c.get("output") or {}
            lines.append(f"### Reviewer: `{ag}` (confidence: `{out.get('confidence', 'unknown')}`)")
            lines.append("")
            lines.append(f"**Overall Comparison:** {out.get('overall_comparison', '')}")
            lines.append("")
            for item in out.get("critiques") or []:
                lines.append(f"#### On {item.get('target_proposal')} — Verdict: `{item.get('verdict')}`")
                if item.get("strengths"):
                    lines.append("- **Strengths:** " + "; ".join(item["strengths"]))
                if item.get("flaws_and_blindspots"):
                    lines.append("- **Flaws & Blindspots:** " + "; ".join(item["flaws_and_blindspots"]))
                if item.get("challenged_assumptions"):
                    lines.append("- **Challenged Assumptions:** " + "; ".join(item["challenged_assumptions"]))
                if item.get("evidence_gaps"):
                    lines.append("- **Evidence Gaps:** " + "; ".join(item["evidence_gaps"]))
                lines.append("")

    # Synthesis
    synth = run.get("synthesis")
    if synth:
        lines.append(f"## 5. Stage 3 — Chair Synthesis (`{chair}`)")
        lines.append("")
        lines.append(f"**Executive Summary:** {synth.get('executive_summary', '')}")
        lines.append("")
        lines.append(f"**Final Recommendation:** {synth.get('final_recommendation', '')}")
        lines.append("")
        lines.append(
            f"**Recommended Single Writer:** `{synth.get('recommended_writer')}` — {synth.get('writer_rationale', '')}"
        )
        lines.append("")

        if synth.get("consensus_points"):
            lines.append("### Consensus Points")
            for pt in synth["consensus_points"]:
                lines.append(f"- {pt}")
            lines.append("")

        lines.append("### Unresolved Disagreements")
        disagreements = synth.get("unresolved_disagreements") or []
        if not disagreements:
            lines.append("- *None — full council consensus achieved.*")
        else:
            for d in disagreements:
                blk = "BLOCKING" if d.get("blocking") else "Non-blocking"
                lines.append(f"- **{d.get('topic')}** (`{blk}`)")
                for pos in d.get("positions") or []:
                    lines.append(f"  - `{pos.get('agent_or_proposal')}`: {pos.get('stance')}")
                lines.append(f"  - *Resolution Path:* {d.get('recommended_resolution')}")
        lines.append("")

        lines.append("### Evidence Ledger")
        ev_list = synth.get("evidence_ledger") or []
        if ev_list:
            lines.append("| ID | Source | Reference | Claim | Verified |")
            lines.append("|---|---|---|---|---|")
            for ev in ev_list:
                lines.append(
                    f"| `{ev.get('id')}` | `{ev.get('source')}` | `{ev.get('reference')}` | "
                    f"{ev.get('claim')} | `{ev.get('verified')}` |"
                )
        else:
            lines.append("- *No explicit evidence items recorded.*")
        lines.append("")

        lines.append("### Assumptions Ledger")
        as_list = synth.get("assumptions_ledger") or []
        if as_list:
            lines.append("| ID | Assumption | Impact if False | Validation Check |")
            lines.append("|---|---|---|---|")
            for a in as_list:
                lines.append(
                    f"| `{a.get('id')}` | {a.get('assumption')} | {a.get('impact_if_false')} | {a.get('validation_check')} |"
                )
        else:
            lines.append("- *No unverified assumptions recorded.*")
        lines.append("")

        if synth.get("steps"):
            lines.append("### Approved Implementation Steps")
            for st in synth["steps"]:
                tfiles = ", ".join(f"`{f}`" for f in (st.get("target_files") or []))
                lines.append(f"1. **`{st.get('step_id')}` — {st.get('title')}** ({tfiles})")
                lines.append(f"   - {st.get('description')}")
                lines.append(f"   - *Verification:* {st.get('verification')}")
            lines.append("")

        if synth.get("authorized_files"):
            lines.append("**Authorized File Scope:** " + ", ".join(f"`{f}`" for f in synth["authorized_files"]))
            lines.append("")
        if synth.get("acceptance_criteria"):
            lines.append("### Acceptance Criteria")
            for ac in synth["acceptance_criteria"]:
                lines.append(f"- [ ] {ac}")
            lines.append("")

    # Execution & Peer Reviews
    exec_info = run.get("execution")
    if exec_info:
        lines.append("## 6. Stage 4 — Sandboxed Single-Writer Execution & Peer Review")
        lines.append("")
        lines.append(f"- **Writer Agent:** `{exec_info.get('writer')}`")
        lines.append(f"- **Worktree Path:** `{exec_info.get('worktree_path')}`")
        lines.append(f"- **Branch:** `{exec_info.get('branch')}`")
        lines.append(f"- **Repair Attempts Used:** `{exec_info.get('repair_attempts', 0)}` / `{exec_info.get('max_repairs', 2)}`")
        lines.append(f"- **Scope Check Passed:** `{exec_info.get('scope_ok')}`")
        lines.append(f"- **Deterministic Tests Passed:** `{exec_info.get('tests_passed')}`")
        lines.append("- **Modified Files:** " + (", ".join(f"`{f}`" for f in (exec_info.get("modified_files") or [])) or "*None*"))
        lines.append("")
        if exec_info.get("test_output"):
            lines.append("### Deterministic Test Output")
            lines.append("```text")
            lines.append(str(exec_info["test_output"]).strip()[:4000])
            lines.append("```")
            lines.append("")
        reviews = [s for s in stage_outputs if s.get("stage") == "review" and s.get("status") == "ok"]
        if reviews:
            lines.append("### Independent Read-Only Peer Reviews")
            lines.append("")
            for rv in reviews:
                rout = rv.get("output") or {}
                lines.append(
                    f"#### Reviewer `{rv.get('agent')}` (Attempt {rv.get('attempt', 1)}) — Verdict: `{rout.get('verdict')}`"
                )
                lines.append(f"- **Summary:** {rout.get('summary')}")
                lines.append(f"- **Scope Compliance:** `{rout.get('scope_compliance')}`")
                for fnd in rout.get("findings") or []:
                    lines.append(
                        f"  - **[{fnd.get('severity', '').upper()}]** `{fnd.get('file_path')}:{fnd.get('line_range')}` — "
                        f"{fnd.get('description')} *(Fix: {fnd.get('suggested_fix')})*"
                    )
                lines.append("")

    if run.get("error"):
        err = run["error"]
        lines.append("## Error Summary")
        lines.append("")
        lines.append(f"- **Kind:** `{err.get('kind')}`")
        lines.append(f"- **Message:** {err.get('message')}")
        lines.append("")

    return "\n".join(lines)
