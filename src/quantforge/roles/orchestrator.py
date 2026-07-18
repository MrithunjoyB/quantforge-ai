"""Code-owned provider orchestration with no provider workflow authority."""

from __future__ import annotations

from datetime import datetime
from typing import TypeVar, cast

from quantforge.audit import AuditLog
from quantforge.domain.models import (
    AdversarialReview,
    AuditEvent,
    ChairExplanation,
    ExperimentProposal,
    MethodologyReview,
    ReproducibilityReview,
    ResearchClaim,
    RoleName,
    StatisticalReview,
    StrictModel,
    TribunalCase,
    VerdictEligibility,
    WorkflowState,
)
from quantforge.evidence.graph import ClaimGraph
from quantforge.providers.failures import ProviderFailure, ProviderFailureKind
from quantforge.roles.contracts import (
    PROVIDER_CONTRACT_NAME,
    PROVIDER_CONTRACT_VERSION,
    RETRY_POLICY_ID,
    RETRY_POLICY_VERSION,
    GovernedRoleProvider,
    ProviderAttemptObservation,
    ProviderRequestProvenance,
    ProviderResult,
    ProviderResultAny,
    ProviderTransportOutcome,
    RoleAction,
    RoleAuthority,
    RoleOutput,
    RoleProvider,
)
from quantforge.roles.governance import role_contract
from quantforge.roles.requests import EvidenceSummary, GovernedRoleRequest, RoleRequestBuilder
from quantforge.roles.validation import validate_role_output
from quantforge.storage.base import (
    CaseStore,
    ProviderInvocationRecord,
    ProviderInvocationStatus,
)
from quantforge.workflow.machine import StateMachine

ResultT = TypeVar("ResultT", bound=StrictModel)


class TribunalOrchestrator:
    """Validate injected providers and commit only complete code-authorized transactions."""

    def __init__(self, provider: RoleProvider | GovernedRoleProvider) -> None:
        self._provider = provider
        self._results: list[ProviderResultAny] = []

    @property
    def provider_results(self) -> tuple[ProviderResultAny, ...]:
        return tuple(self._results)

    @property
    def semantic_hashes(self) -> tuple[str, ...]:
        return tuple(result.semantic_hash for result in self._results)

    # Phase 2A's deterministic offline surface remains source-compatible.
    def propose(self, claim: ResearchClaim) -> ExperimentProposal:
        RoleAuthority.require(RoleName.RESEARCHER, RoleAction.PROPOSE_PROTOCOL)
        provider = cast(RoleProvider, self._provider)
        return self._accept(
            RoleAction.PROPOSE_PROTOCOL,
            provider.propose(claim),
            ExperimentProposal,
        )

    def review_methodology(self, proposal: ExperimentProposal) -> MethodologyReview:
        RoleAuthority.require(RoleName.METHODOLOGY_AUDITOR, RoleAction.REVIEW_METHODOLOGY)
        provider = cast(RoleProvider, self._provider)
        return self._accept(
            RoleAction.REVIEW_METHODOLOGY,
            provider.review_methodology(proposal),
            MethodologyReview,
        )

    def review_statistics(self, case: TribunalCase) -> StatisticalReview:
        RoleAuthority.require(RoleName.STATISTICAL_REVIEWER, RoleAction.REVIEW_STATISTICS)
        provider = cast(RoleProvider, self._provider)
        return self._accept(
            RoleAction.REVIEW_STATISTICS,
            provider.review_statistics(case),
            StatisticalReview,
        )

    def review_adversarially(self, case: TribunalCase) -> AdversarialReview:
        RoleAuthority.require(RoleName.ADVERSARIAL_REVIEWER, RoleAction.REQUEST_CHALLENGE)
        provider = cast(RoleProvider, self._provider)
        return self._accept(
            RoleAction.REQUEST_CHALLENGE,
            provider.review_adversarially(case),
            AdversarialReview,
        )

    def review_reproducibility(self, case: TribunalCase) -> ReproducibilityReview:
        RoleAuthority.require(
            RoleName.REPRODUCIBILITY_REVIEWER,
            RoleAction.REVIEW_REPRODUCIBILITY,
        )
        provider = cast(RoleProvider, self._provider)
        return self._accept(
            RoleAction.REVIEW_REPRODUCIBILITY,
            provider.review_reproducibility(case),
            ReproducibilityReview,
        )

    def explain(
        self,
        case: TribunalCase,
        eligibility: VerdictEligibility,
    ) -> ChairExplanation:
        RoleAuthority.require(RoleName.TRIBUNAL_CHAIR, RoleAction.EXPLAIN_VERDICT)
        provider = cast(RoleProvider, self._provider)
        return self._accept(
            RoleAction.EXPLAIN_VERDICT,
            provider.explain(case, eligibility),
            ChairExplanation,
        )

    def _accept(
        self,
        action: RoleAction,
        result: ProviderResult[ResultT],
        output_type: type[ResultT],
    ) -> ResultT:
        if not isinstance(result, ProviderResult):
            raise TypeError("role provider omitted its required result provenance")
        if not isinstance(result.output, output_type):
            raise TypeError("role provider returned an unauthorized domain output type")
        semantic = result.semantic_provenance
        contract = role_contract(action)
        expected = (
            (semantic.provider_contract_name, PROVIDER_CONTRACT_NAME, "contract name"),
            (semantic.provider_contract_version, PROVIDER_CONTRACT_VERSION, "contract"),
            (semantic.provider_identity, self._provider.provider_identity, "provider"),
            (semantic.model_snapshot, self._provider.model_snapshot, "model"),
            (semantic.role, contract.role, "role"),
            (semantic.action, action, "action"),
            (semantic.prompt_template_id, contract.prompt_id, "prompt identity"),
            (semantic.prompt_template_version, contract.prompt_version, "prompt version"),
            (semantic.prompt_template_sha256, contract.prompt_sha256, "prompt hash"),
            (semantic.structured_output_schema_id, contract.schema_id, "schema identity"),
            (
                semantic.structured_output_schema_version,
                contract.schema_version,
                "schema version",
            ),
            (
                semantic.structured_output_schema_sha256,
                contract.schema_sha256,
                "schema hash",
            ),
            (
                semantic.validation_policy_id,
                contract.validation_policy_id,
                "validation policy identity",
            ),
            (
                semantic.validation_policy_version,
                contract.validation_policy_version,
                "validation policy version",
            ),
            (
                semantic.validation_policy_sha256,
                contract.validation_policy_sha256,
                "validation policy hash",
            ),
        )
        for actual, required, label in expected:
            if actual != required:
                raise ValueError(f"role provider has a mismatched {label}")
        self._results.append(cast(ProviderResultAny, result))
        return result.output

    def invoke_and_advance(
        self,
        store: CaseStore,
        *,
        case_id: str,
        action: RoleAction,
        effective_at: datetime,
        evidence_summaries: tuple[EvidenceSummary, ...] = (),
        code_owned_reproducibility_verified: bool = False,
        final_claim_graph: ClaimGraph | None = None,
    ) -> RoleOutput:
        """Execute one bounded provider call and atomically commit an eligible transition."""

        if (action is RoleAction.EXPLAIN_VERDICT) != (final_claim_graph is not None):
            raise ValueError("Chair invocation requires exactly one code-owned final claim graph")
        durable = store.reconstruct(case_id, require_complete=False)
        replayed = self._immediate_replay(store, durable.revision, durable.case, action)
        if replayed is not None:
            return replayed
        request = RoleRequestBuilder().build(
            action=action,
            case=durable.case,
            case_revision=durable.revision,
            effective_at=effective_at,
            evidence_summaries=evidence_summaries,
            code_owned_reproducibility_verified=code_owned_reproducibility_verified,
        )
        invocation_id = self._next_invocation_id(store, request)
        provider = cast(GovernedRoleProvider, self._provider)
        try:
            result = provider.invoke(request)
        except ProviderFailure as provider_failure:
            store.record_provider_invocation(
                self._failed_record(invocation_id, request, provider, provider_failure),
                None,
                expected_revision=durable.revision,
            )
            raise
        except Exception:
            attempt = ProviderAttemptObservation(
                attempt_index=0,
                requested_at=effective_at,
                responded_at=effective_at,
                latency_ms=0,
                outcome=ProviderTransportOutcome.TRANSPORT_FAILURE,
                provider_status="unclassified_provider_exception",
                retryable=False,
            )
            transport_failure = ProviderFailure(
                ProviderFailureKind.TRANSPORT_FAILURE,
                attempts=(attempt,),
                safe_detail="provider failed before returning a governed result",
            )
            store.record_provider_invocation(
                self._failed_record(invocation_id, request, provider, transport_failure),
                None,
                expected_revision=durable.revision,
            )
            raise transport_failure from None
        try:
            output = self._accept_governed(request, result, durable.case, provider)
        except (TypeError, ValueError, PermissionError):
            attempts = self._semantic_failure_attempts(result, effective_at)
            semantic_failure = ProviderFailure(
                ProviderFailureKind.SEMANTIC_POLICY_FAILURE,
                attempts=attempts,
                safe_detail="provider result failed code-owned authority validation",
            )
            store.record_provider_invocation(
                self._failed_record(invocation_id, request, provider, semantic_failure),
                None,
                expected_revision=durable.revision,
            )
            raise semantic_failure from None
        event = self._workflow_event(durable.case, durable.audit_log, request, output)
        record = ProviderInvocationRecord(
            invocation_id=invocation_id,
            status=ProviderInvocationStatus.ACCEPTED,
            case_id=request.case_id,
            case_revision=request.case_revision,
            role=request.role,
            action=request.action,
            request_semantic_sha256=request.request_semantic_sha256,
            request_provenance=self._request_provenance(request, provider),
            attempts=result.observational_provenance.attempts,
            accepted_result=result,
            recorded_at=result.observational_provenance.responded_at,
        )
        store.record_provider_invocation(
            record,
            event,
            expected_revision=durable.revision,
            final_claim_graph=final_claim_graph,
        )
        self._results.append(result)
        return output

    def replay_accepted(
        self,
        store: CaseStore,
        *,
        case_id: str,
        case_revision: int,
        action: RoleAction,
    ) -> RoleOutput:
        """Return stored semantic output without replaying observations or transitions."""

        record = store.find_accepted_provider_invocation(
            case_id,
            case_revision=case_revision,
            action=action,
        )
        if record is None or record.accepted_result is None:
            raise ValueError("accepted provider result does not exist at that case revision")
        return record.accepted_result.output

    def _accept_governed(
        self,
        request: GovernedRoleRequest,
        result: ProviderResultAny,
        case: TribunalCase,
        provider: GovernedRoleProvider,
    ) -> RoleOutput:
        if not isinstance(result, ProviderResult):
            raise TypeError("governed provider omitted its required result provenance")
        contract = role_contract(request.action)
        if type(result.output) is not contract.output_type:
            raise TypeError("governed provider returned an unauthorized output type")
        semantic = result.semantic_provenance
        expected = (
            (semantic.provider_contract_name, PROVIDER_CONTRACT_NAME, "contract name"),
            (semantic.provider_contract_version, PROVIDER_CONTRACT_VERSION, "contract version"),
            (semantic.provider_identity, provider.provider_identity, "provider identity"),
            (semantic.endpoint_class, provider.endpoint_class, "endpoint class"),
            (semantic.sdk_version, provider.sdk_version, "SDK version"),
            (semantic.requested_model, provider.model_snapshot, "requested model"),
            (semantic.model_snapshot, provider.model_snapshot, "model snapshot"),
            (semantic.role, request.role, "role"),
            (semantic.action, request.action, "action"),
            (semantic.prompt_template_id, request.prompt_template_id, "prompt identity"),
            (
                semantic.prompt_template_version,
                request.prompt_template_version,
                "prompt version",
            ),
            (semantic.prompt_template_sha256, request.prompt_template_sha256, "prompt hash"),
            (
                semantic.structured_output_schema_id,
                request.structured_output_schema_id,
                "schema identity",
            ),
            (
                semantic.structured_output_schema_version,
                request.structured_output_schema_version,
                "schema version",
            ),
            (
                semantic.structured_output_schema_sha256,
                request.structured_output_schema_sha256,
                "schema hash",
            ),
            (
                semantic.validation_policy_id,
                request.validation_policy_id,
                "validation policy identity",
            ),
            (
                semantic.validation_policy_version,
                request.validation_policy_version,
                "validation policy version",
            ),
            (
                semantic.validation_policy_sha256,
                request.validation_policy_sha256,
                "validation policy hash",
            ),
            (
                semantic.canonical_request_sha256,
                request.request_semantic_sha256,
                "request hash",
            ),
            (semantic.role_context_sha256, request.context_identity, "context hash"),
            (semantic.case_id, request.case_id, "case identity"),
            (semantic.case_revision, request.case_revision, "case revision"),
            (
                semantic.constitution_identity,
                request.constitution_identity,
                "constitution identity",
            ),
            (
                semantic.amendment_chain_identity,
                request.amendment_chain_identity,
                "amendment-chain identity",
            ),
            (
                semantic.evidence_references,
                request.evidence_references,
                "evidence references",
            ),
            (
                semantic.context_item_identities,
                tuple(item.identity for item in request.context),
                "context item identities",
            ),
        )
        for actual, required, label in expected:
            if actual != required:
                raise ValueError(f"governed provider has a mismatched {label}")
        observations = result.observational_provenance
        if (
            not observations.attempts
            or observations.transport_outcome is not ProviderTransportOutcome.ACCEPTED
            or observations.refusal
            or observations.truncated
        ):
            raise ValueError("governed provider did not retain one accepted bounded attempt group")
        RoleAuthority.require(request.role, request.action)
        return cast(RoleOutput, validate_role_output(request, result.output, case=case))

    @staticmethod
    def _workflow_event(
        case: TribunalCase,
        audit_log: AuditLog,
        request: GovernedRoleRequest,
        output: RoleOutput,
    ) -> AuditEvent:
        machine = StateMachine(case, audit_log)
        if request.action is RoleAction.PROPOSE_PROTOCOL:
            proposal = cast(ExperimentProposal, output)
            machine.advance(
                WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
                actor=request.role,
                action="propose_protocol",
                timestamp=request.effective_at,
                payload=proposal,
                updates={"proposal": proposal},
            )
        elif request.action is RoleAction.REVIEW_METHODOLOGY:
            methodology = cast(MethodologyReview, output)
            machine.advance(
                WorkflowState.METHODOLOGY_REVIEWED,
                actor=request.role,
                action="review_methodology",
                timestamp=request.effective_at,
                payload=methodology,
                updates={"methodology_review": methodology},
            )
        elif request.action is RoleAction.REVIEW_STATISTICS:
            statistical = cast(StatisticalReview, output)
            machine.advance(
                WorkflowState.STATISTICS_REVIEWED,
                actor=request.role,
                action="review_statistics",
                timestamp=request.effective_at,
                payload=statistical,
                updates={"statistical_review": statistical},
            )
        elif request.action is RoleAction.REQUEST_CHALLENGE:
            adversarial = cast(AdversarialReview, output)
            machine.advance(
                WorkflowState.ADVERSARIAL_REVIEWED,
                actor=request.role,
                action="review_adversarially",
                timestamp=request.effective_at,
                payload=adversarial,
                updates={"adversarial_review": adversarial},
            )
        elif request.action is RoleAction.REVIEW_REPRODUCIBILITY:
            reproducibility = cast(ReproducibilityReview, output)
            machine.skip_follow_up(
                actor=request.role,
                reason="Governed provider review recorded after code owned verification",
                timestamp=request.effective_at,
                reproducibility_review=reproducibility,
            )
        elif request.action is RoleAction.EXPLAIN_VERDICT:
            explanation = cast(ChairExplanation, output)
            machine.advance(
                WorkflowState.CHAIR_EXPLANATION,
                actor=request.role,
                action="explain_verdict",
                timestamp=request.effective_at,
                payload=explanation,
                updates={"chair_explanation": explanation},
            )
        else:  # pragma: no cover - the request registry is closed.
            raise ValueError("unsupported governed workflow action")
        return machine.audit_log.events[-1]

    @staticmethod
    def _next_invocation_id(store: CaseStore, request: GovernedRoleRequest) -> str:
        matching = sum(
            record.request_semantic_sha256 == request.request_semantic_sha256
            for record in store.list_provider_invocations(request.case_id)
        )
        return f"invocation_{request.request_semantic_sha256[:20]}_{matching + 1:03d}"

    @staticmethod
    def _failed_record(
        invocation_id: str,
        request: GovernedRoleRequest,
        provider: GovernedRoleProvider,
        failure: ProviderFailure,
    ) -> ProviderInvocationRecord:
        return ProviderInvocationRecord(
            invocation_id=invocation_id,
            status=ProviderInvocationStatus.FAILED,
            case_id=request.case_id,
            case_revision=request.case_revision,
            role=request.role,
            action=request.action,
            request_semantic_sha256=request.request_semantic_sha256,
            request_provenance=TribunalOrchestrator._request_provenance(request, provider),
            attempts=failure.attempts,
            failure_outcome=ProviderTransportOutcome(failure.kind.value),
            recorded_at=failure.attempts[-1].responded_at,
        )

    @staticmethod
    def _request_provenance(
        request: GovernedRoleRequest,
        provider: GovernedRoleProvider,
    ) -> ProviderRequestProvenance:
        return ProviderRequestProvenance(
            provider_contract_name=PROVIDER_CONTRACT_NAME,
            provider_contract_version=request.provider_contract_version,
            provider_identity=provider.provider_identity,
            endpoint_class=provider.endpoint_class,
            sdk_version=provider.sdk_version,
            requested_model=provider.model_snapshot,
            role=request.role,
            action=request.action,
            prompt_template_id=request.prompt_template_id,
            prompt_template_version=request.prompt_template_version,
            prompt_template_sha256=request.prompt_template_sha256,
            structured_output_schema_id=request.structured_output_schema_id,
            structured_output_schema_version=request.structured_output_schema_version,
            structured_output_schema_sha256=request.structured_output_schema_sha256,
            validation_policy_id=request.validation_policy_id,
            validation_policy_version=request.validation_policy_version,
            validation_policy_sha256=request.validation_policy_sha256,
            canonical_request_sha256=request.request_semantic_sha256,
            retry_policy_id=RETRY_POLICY_ID,
            retry_policy_version=RETRY_POLICY_VERSION,
            role_context_sha256=request.context_identity,
            case_id=request.case_id,
            case_revision=request.case_revision,
            constitution_identity=request.constitution_identity,
            amendment_chain_identity=request.amendment_chain_identity,
            evidence_references=request.evidence_references,
            context_item_identities=tuple(item.identity for item in request.context),
        )

    @staticmethod
    def _semantic_failure_attempts(
        result: object,
        effective_at: datetime,
    ) -> tuple[ProviderAttemptObservation, ...]:
        attempts = (
            result.observational_provenance.attempts if isinstance(result, ProviderResult) else ()
        )
        if not attempts:
            return (
                ProviderAttemptObservation(
                    attempt_index=0,
                    requested_at=effective_at,
                    responded_at=effective_at,
                    latency_ms=0,
                    outcome=ProviderTransportOutcome.SEMANTIC_POLICY_FAILURE,
                    provider_status="code_owned_validation_failed",
                    retryable=False,
                ),
            )
        terminal = attempts[-1].model_copy(
            update={
                "outcome": ProviderTransportOutcome.SEMANTIC_POLICY_FAILURE,
                "provider_status": "code_owned_validation_failed",
                "retryable": False,
            }
        )
        return (*attempts[:-1], terminal)

    @staticmethod
    def _immediate_replay(
        store: CaseStore,
        revision: int,
        case: TribunalCase,
        action: RoleAction,
    ) -> RoleOutput | None:
        target = {
            RoleAction.PROPOSE_PROTOCOL: WorkflowState.RESEARCHER_PROTOCOL_PROPOSED,
            RoleAction.REVIEW_METHODOLOGY: WorkflowState.METHODOLOGY_REVIEWED,
            RoleAction.REVIEW_STATISTICS: WorkflowState.STATISTICS_REVIEWED,
            RoleAction.REQUEST_CHALLENGE: WorkflowState.ADVERSARIAL_REVIEWED,
            RoleAction.REVIEW_REPRODUCIBILITY: WorkflowState.REPRODUCIBILITY_VERIFIED,
            RoleAction.EXPLAIN_VERDICT: WorkflowState.CHAIR_EXPLANATION,
        }.get(action)
        if revision <= 1 or case.state is not target:
            return None
        record = store.find_accepted_provider_invocation(
            case.case_id,
            case_revision=revision - 1,
            action=action,
        )
        if record is None or record.accepted_result is None:
            return None
        return record.accepted_result.output


__all__ = ["TribunalOrchestrator"]
