"""Pydantic v2 schemas for the Three-Agent Council and Pixel Office event bus.

Every model uses ``extra="forbid"`` and exports a provider-safe JSON Schema
(inlined ``$defs``, ``additionalProperties: False`` on every object, and all
properties listed in ``required``) so ``codex exec --output-schema``,
``claude -p --json-schema``, and ``agy --json-schema`` all enforce identical
contracts.
"""
from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .providers import ProviderError

ConfidenceLevel = Literal["low", "medium", "high"]
ProviderName = Literal["claude", "codex", "agy"]
AnonymousLabel = Literal["Proposal A", "Proposal B", "Proposal C"]
EvidenceSource = Literal["packet_observation", "file_line", "diff_hunk", "test_output", "inference"]
CritiqueVerdict = Literal["strong", "viable_with_changes", "flawed"]
ReviewVerdict = Literal["approve", "request_changes", "reject"]
FindingSeverity = Literal["critical", "major", "minor", "nit"]
RunMode = Literal["discuss", "plan", "execute"]
RunStatus = Literal[
    "CREATED",
    "CONTEXT_BUILT",
    "PROPOSING",
    "CRITIQUING",
    "SYNTHESIZING",
    "AWAITING_APPROVAL",
    "WORKTREE_READY",
    "EXECUTING",
    "VERIFYING",
    "REVIEWING",
    "REPAIRING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Evidence, Assumptions & Disagreements
# ---------------------------------------------------------------------------

class EvidenceItem(_StrictModel):
    id: str = Field(description="Short identifier such as E1, E2")
    source: EvidenceSource
    reference: str = Field(description="File path/line range, observation, or test name")
    claim: str = Field(description="What this evidence establishes")
    verified: bool = Field(description="True if directly observed in the packet/test output; False if inferred")


class AssumptionItem(_StrictModel):
    id: str = Field(description="Short identifier such as A1, A2")
    assumption: str = Field(description="Unverified assumption made by the proposal or plan")
    impact_if_false: str = Field(description="Consequence if this assumption turns out to be false")
    validation_check: str = Field(description="Concrete check to verify or falsify the assumption")


class DisagreementPosition(_StrictModel):
    agent_or_proposal: str = Field(description="Proposal label or agent identifier")
    stance: str = Field(description="The position argued and its rationale")


class UnresolvedDisagreement(_StrictModel):
    topic: str = Field(description="Core point of contention between council members")
    positions: list[DisagreementPosition]
    blocking: bool = Field(description="True if execution should not proceed without resolving this item")
    recommended_resolution: str = Field(description="Chair recommendation or discriminating experiment")


# ---------------------------------------------------------------------------
# Stage 1: Independent Proposal
# ---------------------------------------------------------------------------

class AlternativeOption(_StrictModel):
    option: str
    tradeoffs: str


class ProposalOutput(_StrictModel):
    summary: str = Field(description="Concise executive summary of the diagnosis or design proposal")
    assessment: str = Field(description="Detailed technical analysis separating evidence from hypotheses")
    recommendation: str = Field(description="Primary recommended course of action")
    proposed_approach: str = Field(description="Step-by-step technical design or fix strategy")
    affected_files: list[str] = Field(description="Relative file paths expected to be inspected or modified")
    implementation_steps: list[str] = Field(description="Ordered implementation steps")
    alternatives: list[AlternativeOption]
    risks: list[str]
    verification_steps: list[str]
    missing_context: list[str]
    evidence: list[EvidenceItem]
    assumptions: list[AssumptionItem]
    proposed_code: str = Field(description="Optional code snippet or unified diff; empty string if none")
    confidence: ConfidenceLevel


# ---------------------------------------------------------------------------
# Stage 2: Anonymized Cross-Critique
# ---------------------------------------------------------------------------

class ProposalCritique(_StrictModel):
    target_proposal: AnonymousLabel
    verdict: CritiqueVerdict
    strengths: list[str]
    flaws_and_blindspots: list[str]
    challenged_assumptions: list[str]
    evidence_gaps: list[str]
    suggested_improvements: list[str]


class CritiqueOutput(_StrictModel):
    overall_comparison: str = Field(description="Comparative evaluation of Proposal A, Proposal B, and Proposal C")
    critiques: list[ProposalCritique]
    best_elements_to_combine: list[str]
    newly_identified_risks: list[str]
    unresolved_questions: list[str]
    confidence: ConfidenceLevel


# ---------------------------------------------------------------------------
# Stage 3: Chair Synthesis & Actionable Plan
# ---------------------------------------------------------------------------

class PlanStep(_StrictModel):
    step_id: str = Field(description="Step identifier such as S1, S2")
    title: str
    description: str
    target_files: list[str]
    verification: str


class SynthesisOutput(_StrictModel):
    executive_summary: str
    final_recommendation: str
    consensus_points: list[str]
    rejected_ideas: list[str]
    unresolved_disagreements: list[UnresolvedDisagreement]
    evidence_ledger: list[EvidenceItem]
    assumptions_ledger: list[AssumptionItem]
    recommended_writer: ProviderName
    writer_rationale: str
    authorized_files: list[str] = Field(description="Explicit list of relative file paths/globs the writer may touch")
    forbidden_paths: list[str] = Field(description="Paths that must not be modified during execution")
    acceptance_criteria: list[str]
    verification_commands: list[str]
    steps: list[PlanStep]
    risks: list[str]
    confidence: ConfidenceLevel


# ---------------------------------------------------------------------------
# Stage 4: Single-Writer Execution & Dual Read-Only Peer Review
# ---------------------------------------------------------------------------

class FilePatchItem(_StrictModel):
    path: str = Field(description="Relative file path inside the worktree")
    action: Literal["create", "modify", "delete"]
    content: str = Field(description="Full UTF-8 file content for create/modify; empty string for delete")


class WriterOutput(_StrictModel):
    summary_of_changes: str
    modified_files: list[str]
    file_patches: list[FilePatchItem] = Field(
        description="Optional explicit file snapshots when direct filesystem write is restricted by OS sandbox"
    )
    commands_ran: list[str]
    self_verification_notes: str
    notes_for_reviewers: str
    confidence: ConfidenceLevel


class PeerReviewFinding(_StrictModel):
    severity: FindingSeverity
    file_path: str
    line_range: str
    description: str
    suggested_fix: str


class PeerReviewOutput(_StrictModel):
    verdict: ReviewVerdict
    summary: str
    scope_compliance: bool = Field(description="True if changes stayed strictly within authorized_files")
    acceptance_criteria_met: list[str]
    acceptance_criteria_missed: list[str]
    findings: list[PeerReviewFinding]
    security_concerns: list[str]
    verification_assessment: str
    confidence: ConfidenceLevel


# ---------------------------------------------------------------------------
# Pixel Office & Event Bus Schemas
# ---------------------------------------------------------------------------

CharacterAnimationState = Literal[
    "idle",
    "working",
    "thinking",
    "reading",
    "coding",
    "reviewing",
    "waiting",
    "failed",
    "completed",
]

OfficeRoomName = Literal["desks", "meeting_room", "coding_room", "review_room"]


class CouncilEvent(_StrictModel):
    seq: int = 0
    event_id: str
    run_id: str
    timestamp: str
    stage: str
    agent: str
    event_type: str
    animation_state: CharacterAnimationState = "idle"
    room: OfficeRoomName = "desks"
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strict JSON Schema Generator & Validator
# ---------------------------------------------------------------------------

def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"]
            prefix = "#/$defs/"
            if isinstance(ref, str) and ref.startswith(prefix):
                target_name = ref[len(prefix):]
                target = copy.deepcopy(defs[target_name])
                return _inline_refs(target, defs)
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in ("$defs", "title", "default"):
                continue
            out[k] = _inline_refs(v, defs)
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"].keys())
        return out
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def strict_json_schema(model_cls: type[_StrictModel]) -> dict[str, Any]:
    """Return a provider-compatible strict JSON Schema with all $defs inlined."""
    raw = model_cls.model_json_schema()
    defs = raw.get("$defs", {})
    schema = _inline_refs(raw, defs)
    schema.pop("$defs", None)
    schema.pop("title", None)
    return schema


def make_pydantic_validator(model_cls: type[_StrictModel], check_non_empty: tuple[str, ...] = ()):
    """Create a validator callable for provider adapters that raises ProviderError on schema mismatch."""
    def _validate(obj: Any) -> dict[str, Any]:
        if not isinstance(obj, dict):
            raise ProviderError("malformed_output", f"expected JSON object for {model_cls.__name__}")
        try:
            instance = model_cls.model_validate(obj)
        except ValidationError as e:
            raise ProviderError(
                "malformed_output",
                f"{model_cls.__name__} schema validation failed: {e.errors()[0].get('msg', str(e))}",
                False,
                {"validation_errors": e.errors()},
            ) from e
        if check_non_empty and not any(str(getattr(instance, f, "")).strip() for f in check_non_empty):
            raise ProviderError("malformed_output", f"{model_cls.__name__} returned empty primary fields {check_non_empty}")
        return instance.model_dump(mode="json")

    return _validate


PROPOSAL_SCHEMA = strict_json_schema(ProposalOutput)
CRITIQUE_SCHEMA = strict_json_schema(CritiqueOutput)
SYNTHESIS_SCHEMA = strict_json_schema(SynthesisOutput)
WRITER_SCHEMA = strict_json_schema(WriterOutput)
PEER_REVIEW_SCHEMA = strict_json_schema(PeerReviewOutput)

validate_proposal = make_pydantic_validator(ProposalOutput, ("summary", "recommendation"))
validate_critique = make_pydantic_validator(CritiqueOutput, ("overall_comparison",))
validate_synthesis = make_pydantic_validator(SynthesisOutput, ("executive_summary", "final_recommendation"))
validate_writer_output = make_pydantic_validator(WriterOutput, ("summary_of_changes",))
validate_peer_review = make_pydantic_validator(PeerReviewOutput, ("summary",))
