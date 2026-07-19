"""Deterministic differentiated role outputs for the governed offline flagship demo."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from quantforge.adapters.mock import MockRoleProvider, load_scenario
from quantforge.domain.models import (
    AdversarialChallenge,
    AdversarialReview,
    BenchmarkDefinition,
    ChairExplanation,
    ChallengeStatus,
    ChallengeType,
    CorrectedInference,
    DataRequirement,
    ExecutionAssumption,
    ExperimentProposal,
    FailureCriterion,
    FindingSeverity,
    GateStatus,
    MethodologyReview,
    MetricDefinition,
    Money,
    NullHypothesis,
    PrimaryHypothesis,
    Rate,
    ReproducibilityReview,
    ReproducibilityStatus,
    ResearchClaim,
    ReviewDecision,
    ReviewerFinding,
    Sensitivity,
    Stability,
    StatisticalReview,
    TribunalCase,
    VerdictEligibility,
)
from quantforge.roles.chair import create_chair_explanation
from quantforge.roles.contracts import ProviderResult, RoleAction


class GovernedTribunalMockProvider(MockRoleProvider):
    """Offline advisory outputs; code retains every transition and evidence authority."""

    provider_identity = "quantforge_offline_governed_demo_mock"
    model_snapshot = "governed-tribunal-fixture-v1"

    def __init__(self) -> None:
        super().__init__(
            load_scenario("governed_tribunal"),
            timestamp=datetime(2099, 1, 1, tzinfo=UTC),
        )

    def propose(self, claim: ResearchClaim) -> ProviderResult[ExperimentProposal]:
        timestamp = self._now()
        output = ExperimentProposal(
            experiment_id="experiment_governed_tribunal",
            claim_id=claim.claim_id,
            primary_hypothesis=PrimaryHypothesis(
                hypothesis_id="hypothesis_reliable_active_return",
                statement=(
                    "The frozen policy has positive, practically material, statistically reliable "
                    "active return after its declared execution costs"
                ),
                expected_direction="positive",
            ),
            null_hypothesis=NullHypothesis(
                hypothesis_id="null_no_reliable_active_return",
                statement=(
                    "The frozen policy does not establish reliable positive active return after "
                    "costs and corrected inference"
                ),
            ),
            metrics=(
                MetricDefinition(
                    metric_id="metric_active_return",
                    name="benchmark excess return",
                    unit="fraction",
                    calculation="Causal portfolio total return minus the SYN_BENCH total return",
                    primary=True,
                ),
                MetricDefinition(
                    metric_id="metric_corrected_p_value",
                    name="corrected reality-check p-value",
                    unit="ratio",
                    calculation="Centered moving-block reality check from the frozen candidate set",
                    primary=True,
                ),
                MetricDefinition(
                    metric_id="metric_drawdown",
                    name="maximum drawdown",
                    unit="fraction",
                    calculation="Maximum peak-to-trough loss in the validated portfolio path",
                    primary=False,
                ),
            ),
            data_requirements=(
                DataRequirement(
                    requirement_id="data_public_synthetic_v1",
                    description=(
                        "Only the five project-owned deterministic synthetic series and their "
                        "frozen release metadata may be used"
                    ),
                ),
                DataRequirement(
                    requirement_id="data_complete_lineage",
                    description=(
                        "Every input, configuration, executable, output, and validator identity "
                        "must be retained"
                    ),
                ),
            ),
            execution_assumptions=(
                ExecutionAssumption(
                    assumption_id="execution_causal_costed",
                    description=(
                        "Causal daily decisions, next-open fills, monthly equal-weight allocation, "
                        "and the frozen release cost model"
                    ),
                    commission=Rate(value=Decimal("10"), unit="basis_points"),
                    slippage=Rate(value=Decimal("5"), unit="basis_points"),
                    starting_capital=Money(amount=Decimal("100000"), currency="USD"),
                ),
            ),
            benchmarks=(
                BenchmarkDefinition(
                    benchmark_id="benchmark_syn_bench",
                    name="SYN_BENCH",
                    parity_rule=(
                        "Use the same declared date scope, causal valuation calendar, and "
                        "validated benchmark output"
                    ),
                ),
            ),
            periods=(
                "declared deterministic synthetic date scope",
                "three-year training, six-month test, and six-month step windows",
            ),
            exclusions=(
                "live or proprietary market data",
                "post-hoc parameter changes",
                "financial advice or future-return interpretation",
            ),
            failure_criteria=(
                FailureCriterion(
                    criterion_id="failure_corrected_inference",
                    description=(
                        "Do not support reliability unless the corrected reality-check p-value "
                        "passes the preregistered threshold"
                    ),
                ),
                FailureCriterion(
                    criterion_id="failure_return_interval",
                    description=(
                        "Do not support reliability when the preregistered bootstrap return "
                        "interval includes zero"
                    ),
                ),
                FailureCriterion(
                    criterion_id="failure_drawdown",
                    description=(
                        "Flag robustness when maximum drawdown breaches its preregistered limit"
                    ),
                ),
                FailureCriterion(
                    criterion_id="failure_loss_probability",
                    description=(
                        "Flag robustness when bootstrap loss probability breaches its "
                        "preregistered limit"
                    ),
                ),
                FailureCriterion(
                    criterion_id="failure_reproducibility",
                    description=(
                        "Return inconclusive unless exact reconstruction is independently verified"
                    ),
                ),
            ),
            proposed_at=timestamp,
        )
        return self._result(
            RoleAction.PROPOSE_PROTOCOL,
            output,
            timestamp,
            ProviderResult[ExperimentProposal],
        )

    def review_methodology(self, proposal: ExperimentProposal) -> ProviderResult[MethodologyReview]:
        timestamp = self._now()
        output = MethodologyReview(
            review_id="methodology_governed_tribunal",
            experiment_id=proposal.experiment_id,
            decision=ReviewDecision.APPROVED,
            causality_checked=True,
            leakage_checked=True,
            benchmark_parity_checked=True,
            execution_assumptions_checked=True,
            multiple_testing_checked=True,
            evaluable=True,
            findings=(
                ReviewerFinding(
                    finding_id="methodology_headline_insufficient",
                    severity=FindingSeverity.NONCRITICAL,
                    summary=(
                        "A headline return is insufficient; corrected inference, drawdown, costs, "
                        "benchmark parity, and loss probability are decisive constitution criteria"
                    ),
                    resolved=True,
                ),
                ReviewerFinding(
                    finding_id="methodology_synthetic_scope",
                    severity=FindingSeverity.NONCRITICAL,
                    summary=(
                        "Synthetic scope permits architecture validation but cannot establish "
                        "live-market generalization"
                    ),
                    resolved=False,
                ),
            ),
            reviewed_at=timestamp,
        )
        return self._result(
            RoleAction.REVIEW_METHODOLOGY,
            output,
            timestamp,
            ProviderResult[MethodologyReview],
        )

    def review_statistics(self, case: TribunalCase) -> ProviderResult[StatisticalReview]:
        del case
        timestamp = self._now()
        output = StatisticalReview(
            review_id="statistics_governed_tribunal",
            effect_direction="positive",
            corrected_inference=CorrectedInference.FAIL,
            practical_significance=True,
            findings=(
                ReviewerFinding(
                    finding_id="statistics_large_point_estimate",
                    severity=FindingSeverity.INFO,
                    summary=(
                        "The net point estimate is economically large relative to the declared "
                        "benchmark and costs"
                    ),
                    resolved=True,
                ),
                ReviewerFinding(
                    finding_id="statistics_reliability_unsupported",
                    severity=FindingSeverity.NONCRITICAL,
                    summary=(
                        "The corrected p-value fails its threshold and the preregistered return "
                        "interval crosses zero, so statistical reliability is unsupported"
                    ),
                    resolved=False,
                ),
            ),
            sample_limitations=(
                (
                    "The sample is deterministic synthetic validation data rather than empirical "
                    "market data"
                ),
                "The portfolio-policy series contains one eligible policy candidate",
            ),
            reviewed_at=timestamp,
        )
        return self._result(
            RoleAction.REVIEW_STATISTICS,
            output,
            timestamp,
            ProviderResult[StatisticalReview],
        )

    def review_adversarially(self, case: TribunalCase) -> ProviderResult[AdversarialReview]:
        del case
        timestamp = self._now()
        output = AdversarialReview(
            review_id="adversarial_governed_tribunal",
            challenges=(
                AdversarialChallenge(
                    challenge_id="challenge_costs",
                    challenge_type=ChallengeType.COST,
                    description=(
                        "Test whether declared commissions and slippage erase the point estimate"
                    ),
                    status=ChallengeStatus.PASSED,
                    evidence_references=(),
                ),
                AdversarialChallenge(
                    challenge_id="challenge_drawdown",
                    challenge_type=ChallengeType.ROBUSTNESS,
                    description=("Compare maximum drawdown with its preregistered limit"),
                    status=ChallengeStatus.FAILED,
                    evidence_references=(),
                ),
                AdversarialChallenge(
                    challenge_id="challenge_loss_probability",
                    challenge_type=ChallengeType.BENCHMARK,
                    description=("Compare bootstrap loss probability with its preregistered limit"),
                    status=ChallengeStatus.FAILED,
                    evidence_references=(),
                ),
                AdversarialChallenge(
                    challenge_id="challenge_concentration",
                    challenge_type=ChallengeType.CONCENTRATION,
                    description="Test whether one synthetic asset dominates net profit attribution",
                    status=ChallengeStatus.FAILED,
                    evidence_references=(),
                ),
                AdversarialChallenge(
                    challenge_id="challenge_parameter_stability",
                    challenge_type=ChallengeType.PARAMETER,
                    description=(
                        "Require stability evidence beyond the single portfolio-policy series"
                    ),
                    status=ChallengeStatus.UNRESOLVED,
                    evidence_references=(),
                ),
            ),
            robustness_status=GateStatus.FAIL,
            cost_sensitivity=Sensitivity.MODERATE,
            parameter_stability=Stability.MIXED,
            regime_stability=Stability.UNSTABLE,
            concentration_risk=Sensitivity.HIGH,
            findings=(
                ReviewerFinding(
                    finding_id="adversarial_headline_fragile",
                    severity=FindingSeverity.NONCRITICAL,
                    summary=(
                        "Drawdown, loss probability, concentration, and regime dependence prevent "
                        "a robust interpretation of the headline return"
                    ),
                    resolved=False,
                ),
            ),
            reviewed_at=timestamp,
        )
        return self._result(
            RoleAction.REQUEST_CHALLENGE,
            output,
            timestamp,
            ProviderResult[AdversarialReview],
        )

    def review_reproducibility(self, case: TribunalCase) -> ProviderResult[ReproducibilityReview]:
        del case
        timestamp = self._now()
        output = ReproducibilityReview(
            review_id="reproducibility_governed_tribunal",
            status=ReproducibilityStatus.VERIFIED,
            configuration_verified=True,
            manifests_verified=True,
            hashes_verified=True,
            software_identity_verified=True,
            data_lineage_verified=True,
            evidence_complete=True,
            reconstruction_status="exact semantic reconstruction verified by code",
            findings=(
                ReviewerFinding(
                    finding_id="reproducibility_observational_variance",
                    severity=FindingSeverity.INFO,
                    summary=(
                        "Wall-clock and raw-byte observations are separated from stable semantic "
                        "identities and remain tamper-evident"
                    ),
                    resolved=True,
                ),
            ),
            reviewed_at=timestamp,
        )
        return self._result(
            RoleAction.REVIEW_REPRODUCIBILITY,
            output,
            timestamp,
            ProviderResult[ReproducibilityReview],
        )

    def explain(
        self,
        case: TribunalCase,
        eligibility: VerdictEligibility,
    ) -> ProviderResult[ChairExplanation]:
        del case
        timestamp = self._now()
        output = create_chair_explanation(
            explanation_id="chair_governed_tribunal",
            eligibility=eligibility,
            requested_verdict=eligibility.verdict,
            summary=(
                "The attractive net return does not establish the claimed reliability because "
                "corrected inference fails and material robustness objections remain"
            ),
            limitations=(
                "All numerical evidence is deterministic synthetic research evidence",
                "Mock role wording demonstrates contracts and governance, not model intelligence",
                "No live-market performance or future return is established",
            ),
            verdict_change_conditions=(
                "Only newly admitted evidence that passes corrected inference and robustness gates "
                "can change eligibility",
                "Chair wording and provider preference cannot change the code-owned verdict",
            ),
            created_at=timestamp,
        )
        return self._result(
            RoleAction.EXPLAIN_VERDICT,
            output,
            timestamp,
            ProviderResult[ChairExplanation],
        )


__all__ = ["GovernedTribunalMockProvider"]
