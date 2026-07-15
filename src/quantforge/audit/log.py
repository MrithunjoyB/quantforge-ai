"""Deterministic single-case SHA-256 audit log with governed state reconstruction."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from quantforge.domain.models import (
    AdversarialReview,
    AuditEvent,
    ChairExplanation,
    EvidenceRelationship,
    ExperimentConstitution,
    ExperimentProposal,
    FindingSeverity,
    HumanApproval,
    MethodologyReview,
    ReproducibilityReview,
    ResearchClaim,
    RoleName,
    StatisticalReview,
    TribunalCase,
    VerdictEligibility,
    WorkflowState,
    validated_model_update,
)
from quantforge.evidence.ledger import EvidenceLedger, EvidenceLedgerSnapshot
from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.serialization.safe_json import (
    reject_symlink_components,
    safe_parse_json,
    safe_write_text,
)
from quantforge.verdict.policy import VerdictInputs, VerdictPolicy
from quantforge.workflow.rules import require_transition_authority

GENESIS_HASH = "0" * 64


def _parse_model[ModelT: BaseModel](model_type: type[ModelT], value: Any) -> ModelT:
    return model_type.model_validate_json(canonical_json(value))


class AuditLog:
    def __init__(self, events: tuple[AuditEvent, ...] = ()) -> None:
        self._events = list(events)
        self.verify(require_complete=False)

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        *,
        timestamp: datetime,
        case_id: str,
        workflow_state: WorkflowState,
        actor: RoleName,
        action: str,
        payload: Any,
        expected_case: TribunalCase | None = None,
    ) -> AuditEvent:
        source = self._events[-1].workflow_state if self._events else None
        require_transition_authority(source, workflow_state, actor, action)
        if self._events and case_id != self._events[0].case_id:
            raise ValueError("audit events from different cases cannot be concatenated")
        if self._events and timestamp <= self._events[-1].timestamp:
            raise ValueError("audit timestamps must be strictly increasing")
        normalized_payload = safe_parse_json(canonical_json(payload))
        sequence = len(self._events) + 1
        previous_hash = self._events[-1].current_event_hash if self._events else GENESIS_HASH
        event_payload: dict[str, Any] = {
            "event_id": f"audit_{sequence:06d}",
            "schema_version": "1.0",
            "sequence": sequence,
            "timestamp": timestamp,
            "case_id": case_id,
            "workflow_state": workflow_state,
            "actor": actor,
            "action": action,
            "payload": normalized_payload,
            "payload_hash": canonical_sha256(normalized_payload),
            "previous_event_hash": previous_hash,
        }
        event = AuditEvent(**event_payload, current_event_hash=canonical_sha256(event_payload))
        self._events.append(event)
        try:
            self.verify(require_complete=False)
            if (
                expected_case is not None
                and self.replay_case(require_complete=False) != expected_case
            ):
                raise ValueError("audit payload does not reconstruct the proposed case transition")
        except (TypeError, ValueError):
            self._events.pop()
            raise
        return event

    def verify(self, *, require_complete: bool = False, replay: bool = True) -> None:
        if not self._events:
            if require_complete:
                raise ValueError("complete audit chain cannot be empty")
            return
        previous_hash = GENESIS_HASH
        previous_state: WorkflowState | None = None
        previous_timestamp: datetime | None = None
        case_id = self._events[0].case_id
        for expected_sequence, event in enumerate(self._events, start=1):
            if (
                event.sequence != expected_sequence
                or event.event_id != f"audit_{expected_sequence:06d}"
            ):
                raise ValueError(
                    "audit sequence gap, identifier alteration, or reordering detected"
                )
            if event.case_id != case_id:
                raise ValueError("audit events from different cases cannot be concatenated")
            if previous_timestamp is not None and event.timestamp <= previous_timestamp:
                raise ValueError("audit timestamps must be strictly increasing")
            require_transition_authority(
                previous_state, event.workflow_state, event.actor, event.action
            )
            if event.previous_event_hash != previous_hash:
                raise ValueError("audit previous-hash mismatch")
            if canonical_sha256(event.payload) != event.payload_hash:
                raise ValueError("audit payload hash mismatch")
            payload = event.model_dump(mode="python", exclude={"current_event_hash"})
            if canonical_sha256(payload) != event.current_event_hash:
                raise ValueError("audit event tampering detected")
            previous_hash = event.current_event_hash
            previous_state = event.workflow_state
            previous_timestamp = event.timestamp
        if require_complete and previous_state is not WorkflowState.CHAIR_EXPLANATION:
            raise ValueError("audit chain is a valid but incomplete prefix")
        if replay:
            self.replay_cases(require_complete=require_complete, _verified=True)

    def replay_states(self, *, require_complete: bool = True) -> tuple[WorkflowState, ...]:
        self.verify(require_complete=require_complete)
        return tuple(event.workflow_state for event in self._events)

    def replay_case(self, *, require_complete: bool = True) -> TribunalCase:
        cases = self.replay_cases(require_complete=require_complete)
        if not cases:
            raise ValueError("cannot reconstruct a case from an empty audit chain")
        return cases[-1]

    def replay_cases(
        self, *, require_complete: bool = True, _verified: bool = False
    ) -> tuple[TribunalCase, ...]:
        if not _verified:
            self.verify(require_complete=require_complete, replay=False)
        if not self._events:
            return ()
        cases: list[TribunalCase] = []
        ledger: EvidenceLedger | None = None
        first = self._events[0]
        claim = _parse_model(ResearchClaim, first.payload)
        if first.timestamp != claim.submitted_at:
            raise ValueError("claim receipt timestamp does not match the audited claim")
        case = TribunalCase(
            case_id=first.case_id,
            state=WorkflowState.CLAIM_RECEIVED,
            claim=claim,
        )
        cases.append(case)
        for event in self._events[1:]:
            updates: dict[str, Any]
            domain_timestamps: tuple[datetime, ...] = ()
            if event.workflow_state is WorkflowState.RESEARCHER_PROTOCOL_PROPOSED:
                proposal = _parse_model(ExperimentProposal, event.payload)
                updates = {"proposal": proposal}
                domain_timestamps = (proposal.proposed_at,)
            elif event.workflow_state is WorkflowState.METHODOLOGY_REVIEWED:
                methodology_review = _parse_model(MethodologyReview, event.payload)
                updates = {"methodology_review": methodology_review}
                domain_timestamps = (methodology_review.reviewed_at,)
            elif event.workflow_state is WorkflowState.HUMAN_APPROVAL:
                approval = _parse_model(HumanApproval, event.payload)
                updates = {"human_approval": approval}
                domain_timestamps = (approval.approved_at,)
            elif event.workflow_state is WorkflowState.CONSTITUTION_LOCKED:
                constitution = _parse_model(ExperimentConstitution, event.payload)
                updates = {"constitution": constitution}
                domain_timestamps = (constitution.locked_at,)
            elif event.workflow_state is WorkflowState.EXPERIMENT_EXECUTED:
                snapshot = _parse_model(EvidenceLedgerSnapshot, event.payload)
                if case.constitution is None or case.proposal is None:
                    raise ValueError("evidence replay requires a locked constitution")
                if (
                    snapshot.case_id != case.case_id
                    or snapshot.experiment_id != case.proposal.experiment_id
                    or snapshot.constitution_hash != case.constitution.constitution_hash
                ):
                    raise ValueError("audited evidence ledger is bound to a foreign case")
                ledger = EvidenceLedger.from_snapshot(snapshot, claim_ids={case.claim.claim_id})
                updates = {
                    "evidence_ids": tuple(item.evidence_id for item in snapshot.evidence),
                }
                domain_timestamps = tuple(item.created_at for item in snapshot.evidence)
            elif event.workflow_state is WorkflowState.STATISTICS_REVIEWED:
                statistical_review = _parse_model(StatisticalReview, event.payload)
                updates = {"statistical_review": statistical_review}
                domain_timestamps = (statistical_review.reviewed_at,)
            elif event.workflow_state is WorkflowState.ADVERSARIAL_REVIEWED:
                adversarial_review = _parse_model(AdversarialReview, event.payload)
                updates = {"adversarial_review": adversarial_review}
                domain_timestamps = (adversarial_review.reviewed_at,)
            elif event.workflow_state is WorkflowState.OPTIONAL_FOLLOW_UP:
                if event.payload != {"follow_up_required": False}:
                    raise ValueError("optional follow-up entry payload is invalid")
                updates = {}
            elif event.workflow_state is WorkflowState.REPRODUCIBILITY_VERIFIED:
                if not isinstance(event.payload, dict):
                    raise ValueError("follow-up disposition payload must be an object")
                disposition = event.payload.get("disposition")
                reason = event.payload.get("reason")
                review_payload = event.payload.get("reproducibility_review")
                expected_disposition = (
                    "skipped" if event.action == "skip_follow_up" else "completed"
                )
                if (
                    disposition != expected_disposition
                    or not isinstance(reason, str)
                    or not reason.strip()
                ):
                    raise ValueError("follow-up disposition is not explicit or action-consistent")
                reproducibility_review = _parse_model(ReproducibilityReview, review_payload)
                updates = {
                    "follow_up_disposition": disposition,
                    "reproducibility_review": reproducibility_review,
                }
                domain_timestamps = (reproducibility_review.reviewed_at,)
            elif event.workflow_state is WorkflowState.VERDICT_ELIGIBILITY_COMPUTED:
                if not isinstance(event.payload, dict):
                    raise ValueError("verdict computation payload must be an object")
                inputs = _parse_model(VerdictInputs, event.payload.get("inputs"))
                eligibility = _parse_model(VerdictEligibility, event.payload.get("eligibility"))
                self._validate_policy_inputs(case, ledger, inputs)
                recomputed = VerdictPolicy.compute(
                    inputs,
                    eligibility_id=eligibility.eligibility_id,
                    computed_at=eligibility.computed_at,
                )
                if recomputed != eligibility:
                    raise ValueError("audited verdict does not match deterministic policy")
                updates = {"verdict_eligibility": eligibility}
                domain_timestamps = (eligibility.computed_at,)
            elif event.workflow_state is WorkflowState.CHAIR_EXPLANATION:
                explanation = _parse_model(ChairExplanation, event.payload)
                updates = {"chair_explanation": explanation}
                domain_timestamps = (explanation.created_at,)
            else:  # pragma: no cover - exhaustive enum guard
                raise ValueError("unsupported workflow state during replay")
            if any(timestamp > event.timestamp for timestamp in domain_timestamps):
                raise ValueError("audited domain object postdates its recording event")
            case = validated_model_update(case, state=event.workflow_state, **updates)
            cases.append(case)
        return tuple(cases)

    @staticmethod
    def _validate_policy_inputs(
        case: TribunalCase, ledger: EvidenceLedger | None, inputs: VerdictInputs
    ) -> None:
        if (
            ledger is None
            or case.proposal is None
            or case.methodology_review is None
            or case.statistical_review is None
            or case.adversarial_review is None
            or case.reproducibility_review is None
        ):
            raise ValueError("verdict inputs require every governed review")
        snapshot = ledger.snapshot()
        findings = (
            *case.methodology_review.findings,
            *case.statistical_review.findings,
            *case.adversarial_review.findings,
            *case.reproducibility_review.findings,
        )
        unresolved_critical = any(
            finding.severity is FindingSeverity.CRITICAL and not finding.resolved
            for finding in findings
        )
        unresolved_noncritical = any(
            finding.severity is FindingSeverity.NONCRITICAL and not finding.resolved
            for finding in findings
        )
        expected: dict[str, Any] = {
            "methodology_status": case.methodology_review.decision,
            "primary_experiment_complete": True,
            "evidence_validation_statuses": tuple(
                item.validation_status for item in snapshot.evidence
            ),
            "corrected_inference": case.statistical_review.corrected_inference,
            "expected_direction": case.proposal.primary_hypothesis.expected_direction,
            "effect_direction": case.statistical_review.effect_direction,
            "practical_significance": case.statistical_review.practical_significance,
            "robustness_status": case.adversarial_review.robustness_status,
            "cost_sensitivity": case.adversarial_review.cost_sensitivity,
            "parameter_stability": case.adversarial_review.parameter_stability,
            "regime_stability": case.adversarial_review.regime_stability,
            "concentration_risk": case.adversarial_review.concentration_risk,
            "reproducibility_status": case.reproducibility_review.status,
            "unresolved_critical_findings": unresolved_critical,
            "unresolved_noncritical_limitations": unresolved_noncritical,
        }
        actual = inputs.model_dump(mode="python")
        for name, value in expected.items():
            if actual[name] != value:
                raise ValueError(f"verdict input {name} is not derived from governed state")
        decisive_ids = {reference.evidence_id for reference in inputs.decisive_evidence}
        if decisive_ids != {item.evidence_id for item in snapshot.evidence}:
            raise ValueError("decisive policy evidence must cover the audited evidence ledger")
        for reference in inputs.decisive_evidence:
            ledger.validate_reference(reference)
        contradictory_ids = {
            item.evidence_id
            for item in snapshot.evidence
            if item.relationship is EvidenceRelationship.CONTRADICTS
        }
        if {item.evidence_id for item in inputs.contradictory_evidence} != contradictory_ids:
            raise ValueError("contradictory policy evidence does not match the ledger")
        for reference in inputs.contradictory_evidence:
            evidence = ledger.validate_reference(reference)
            if evidence.relationship is not EvidenceRelationship.CONTRADICTS:
                raise ValueError("noncontradictory evidence is mislabeled as contradictory")

    def write_jsonl(self, path: Path) -> None:
        self.verify(require_complete=True)
        safe_write_text(
            path,
            "".join(canonical_json(event) + "\n" for event in self._events),
        )

    @classmethod
    def read_jsonl(cls, path: Path, *, max_bytes: int = 2_000_000) -> AuditLog:
        reject_symlink_components(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            raise ValueError("audit input must be a bounded regular file")
        events: list[AuditEvent] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                raise ValueError(f"empty audit record at line {line_number}")
            try:
                value = safe_parse_json(line, max_bytes=max_bytes)
                events.append(AuditEvent.model_validate_json(canonical_json(value)))
            except (TypeError, ValueError) as error:
                raise ValueError(f"invalid audit record at line {line_number}") from error
        if not events:
            raise ValueError("audit input cannot be empty")
        log = cls(tuple(events))
        log.verify(require_complete=True)
        return log
