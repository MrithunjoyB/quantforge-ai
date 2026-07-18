from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import ValidationError

import quantforge.providers.openai as openai_provider_module
from quantforge.adapters.mock import MockRoleProvider, load_scenario
from quantforge.domain.models import ResearchClaim, TribunalCase, WorkflowState
from quantforge.providers.config import (
    EnvironmentCredentialSource,
    OpenAIProviderConfig,
    ProviderMode,
    ProviderSelection,
)
from quantforge.providers.factory import select_role_provider
from quantforge.providers.failures import ProviderFailure, ProviderFailureKind
from quantforge.providers.openai import OFFICIAL_OPENAI_BASE_URL, OpenAIStructuredRoleProvider
from quantforge.providers.strict_output import validate_structured_output
from quantforge.roles.contracts import RoleAction
from quantforge.roles.governance import ROLE_CONTRACTS, _artifact_text, role_contract
from quantforge.roles.requests import GovernedRoleRequest, RoleRequestBuilder
from quantforge.serialization.canonical import canonical_sha256

_EFFECTIVE_AT = datetime(2026, 1, 2, tzinfo=UTC)


class _FakeResponses:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.responses = _FakeResponses(outcomes)


def _request(claim: ResearchClaim) -> GovernedRoleRequest:
    case = TribunalCase(
        case_id="case_provider_contract",
        state=WorkflowState.CLAIM_RECEIVED,
        claim=claim,
    )
    return RoleRequestBuilder().build(
        action=RoleAction.PROPOSE_PROTOCOL,
        case=case,
        case_revision=1,
        effective_at=_EFFECTIVE_AT,
    )


def _output(request: GovernedRoleRequest, claim: ResearchClaim) -> object:
    provider = MockRoleProvider(load_scenario("provisional"), timestamp=_EFFECTIVE_AT)
    return provider.propose(claim).output.model_copy(
        update={"experiment_id": request.expected_output_id}
    )


def _response(output: object, *, raw: str | None = None) -> object:
    assert hasattr(output, "model_dump_json")
    text = output.model_dump_json() if raw is None else raw
    content = SimpleNamespace(type="output_text", text=text, parsed=output)
    message = SimpleNamespace(type="message", content=[content])
    usage = SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150)
    return SimpleNamespace(
        _request_id="request_official_1",
        id="response_official_1",
        model="operator-model-snapshot",
        output=[message],
        output_text=text,
        output_parsed=output,
        status="completed",
        incomplete_details=None,
        usage=usage,
    )


def _provider(
    client: _FakeClient,
    *,
    maximum_retries: int = 0,
    retain_raw_response_digest: bool = True,
) -> OpenAIStructuredRoleProvider:
    return OpenAIStructuredRoleProvider(
        OpenAIProviderConfig(
            mode=ProviderMode.OPENAI,
            model="operator-model",
            maximum_retries=maximum_retries,
            retain_raw_response_digest=retain_raw_response_digest,
        ),
        client=client,
        sleeper=lambda _: None,
    )


def test_exactly_six_role_contracts_are_differentiated() -> None:
    assert len(ROLE_CONTRACTS) == 6
    assert len({contract.role for contract in ROLE_CONTRACTS.values()}) == 6
    assert len({contract.prompt_sha256 for contract in ROLE_CONTRACTS.values()}) == 6
    assert len({contract.schema_sha256 for contract in ROLE_CONTRACTS.values()}) == 6
    assert len({contract.validation_policy_sha256 for contract in ROLE_CONTRACTS.values()}) == 6


def test_prompt_artifact_identity_ignores_source_indentation_but_not_policy_change() -> None:
    contract = role_contract(RoleAction.PROPOSE_PROTOCOL)
    assert canonical_sha256(
        {"id": contract.prompt_id, "prompt": contract.prompt, "version": "1.0"}
    ) == (contract.prompt_sha256)
    assert (
        canonical_sha256(
            {"id": contract.prompt_id, "prompt": contract.prompt + " changed", "version": "1.0"}
        )
        != contract.prompt_sha256
    )
    assert _artifact_text("\n    governed line\n") == _artifact_text("governed line")
    assert _artifact_text("governed  line") != _artifact_text("governed line")


def test_openai_mode_and_operator_model_are_mandatory() -> None:
    selection = ProviderSelection()
    assert selection.mode is ProviderMode.MOCK
    mock = MockRoleProvider(load_scenario("provisional"), timestamp=_EFFECTIVE_AT)
    assert select_role_provider(selection, mock_provider=mock) is mock
    with pytest.raises(ValidationError, match="mode"):
        OpenAIProviderConfig(mode=ProviderMode.MOCK, model="operator-model")
    with pytest.raises(ValidationError, match="model"):
        OpenAIProviderConfig.model_validate({"mode": "openai"})
    with pytest.raises(ValidationError, match="explicit OpenAI"):
        ProviderSelection(mode=ProviderMode.OPENAI)


def test_environment_credentials_are_redacted_and_constructor_failure_has_no_secret_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = EnvironmentCredentialSource()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        source.api_key()
    synthetic_key = "sk" + "-synthetic-redacted-value"
    monkeypatch.setenv("OPENAI_API_KEY", synthetic_key)
    assert source.api_key() == synthetic_key
    assert "sk" + "-synthetic" not in repr(source)

    class _BrokenCredentialSource:
        def api_key(self) -> str:
            raise RuntimeError("sk" + "-secret-in-source-exception")

    with pytest.raises(RuntimeError) as captured:
        OpenAIStructuredRoleProvider(
            OpenAIProviderConfig(mode=ProviderMode.OPENAI, model="operator-model"),
            credential_source=_BrokenCredentialSource(),
        )
    assert captured.value.__cause__ is None
    assert "sk" + "-secret" not in str(captured.value)


def test_mock_mode_forbids_dormant_openai_configuration() -> None:
    openai_config = OpenAIProviderConfig(mode=ProviderMode.OPENAI, model="operator-model")
    with pytest.raises(ValidationError, match="forbidden"):
        ProviderSelection(mode=ProviderMode.MOCK, openai=openai_config)


def test_official_client_base_url_is_pinned_and_environment_cannot_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_openai(**kwargs: object) -> _FakeClient:
        captured.update(kwargs)
        return _FakeClient([])

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-credential")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.invalid/v1")
    monkeypatch.setattr(openai_provider_module, "OpenAI", fake_openai)
    OpenAIStructuredRoleProvider(
        OpenAIProviderConfig(mode=ProviderMode.OPENAI, model="operator-model")
    )
    assert captured["base_url"] == OFFICIAL_OPENAI_BASE_URL
    assert captured["max_retries"] == 0


def test_model_identifier_cannot_be_used_as_a_credential_sink() -> None:
    with pytest.raises(ValidationError, match="resembles a credential"):
        OpenAIProviderConfig(mode=ProviderMode.OPENAI, model="sk-synthetic-secret")


def test_official_transport_uses_bounded_tool_free_structured_request(
    simple_claim: ResearchClaim,
) -> None:
    request = _request(simple_claim)
    output = _output(request, simple_claim)
    client = _FakeClient([_response(output)])

    result = _provider(client).invoke(request)

    assert result.output == output
    assert result.semantic_provenance.provider_identity == "openai"
    assert result.semantic_provenance.requested_model == "operator-model"
    assert result.semantic_provenance.model_snapshot == "operator-model-snapshot"
    assert result.semantic_provenance.canonical_request_sha256 == request.request_semantic_sha256
    assert result.semantic_provenance.raw_response_sha256 is not None
    assert result.observational_provenance.usage == {
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
    }
    call = client.responses.calls[0]
    assert call["model"] == "operator-model"
    assert call["tools"] == []
    assert call["store"] is False
    assert call["truncation"] == "disabled"
    assert call["text_format"] is role_contract(request.action).output_type


def test_observations_can_omit_usage_and_raw_digest(simple_claim: ResearchClaim) -> None:
    request = _request(simple_claim)
    output = _output(request, simple_claim)
    response = _response(output)
    response.usage = None
    result = _provider(
        _FakeClient([response]),
        retain_raw_response_digest=False,
    ).invoke(request)
    assert result.observational_provenance.usage == {}
    assert result.semantic_provenance.raw_response_sha256 is None


def test_raw_transport_format_digest_does_not_change_semantic_identity(
    simple_claim: ResearchClaim,
) -> None:
    request = _request(simple_claim)
    output = _output(request, simple_claim)
    compact = output.model_dump_json()
    spaced = " \n" + compact + "\n "
    first = _provider(_FakeClient([_response(output, raw=compact)])).invoke(request)
    second = _provider(_FakeClient([_response(output, raw=spaced)])).invoke(request)
    assert first.semantic_provenance.raw_response_sha256 != (
        second.semantic_provenance.raw_response_sha256
    )
    assert first.semantic_hash == second.semantic_hash


@pytest.mark.malicious
@pytest.mark.parametrize(
    "raw",
    [
        "```json\n{}\n```",
        '{"experiment_id":"x","experiment_id":"y"}',
        "{} trailing",
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":"e\\u0301"}',
        "[{}]",
    ],
)
def test_strict_output_rejects_ambiguous_json(raw: str, simple_claim: ResearchClaim) -> None:
    output_type = type(_output(_request(simple_claim), simple_claim))
    with pytest.raises(ValueError):
        validate_structured_output(raw, output_type, maximum_response_bytes=10_000)


@pytest.mark.malicious
def test_transport_rejects_sdk_parsed_and_raw_disagreement(simple_claim: ResearchClaim) -> None:
    request = _request(simple_claim)
    output = _output(request, simple_claim)
    response = _response(output, raw="{}")
    with pytest.raises(ProviderFailure) as captured:
        _provider(_FakeClient([response])).invoke(request)
    assert captured.value.kind is ProviderFailureKind.SCHEMA_VALIDATION_FAILURE

    valid_raw = output.model_dump_json()
    other = output.model_copy(update={"exclusions": ("Different bounded exclusion",)})
    parsed_disagreement = _response(output, raw=valid_raw)
    parsed_disagreement.output_parsed = other
    with pytest.raises(ProviderFailure) as sdk_disagreement:
        _provider(_FakeClient([parsed_disagreement])).invoke(request)
    assert sdk_disagreement.value.kind is ProviderFailureKind.SCHEMA_VALIDATION_FAILURE


@pytest.mark.malicious
@pytest.mark.parametrize("mutation", ["extra", "missing", "oversized", "deep"])
def test_transport_rejects_schema_drift_and_resource_abuse(
    mutation: str,
    simple_claim: ResearchClaim,
) -> None:
    request = _request(simple_claim)
    output = _output(request, simple_claim)
    value = output.model_dump(mode="json")
    if mutation == "extra":
        value["provider_selected_authority"] = "verdict"
    elif mutation == "missing":
        value.pop("claim_id")
    elif mutation == "oversized":
        value["exclusions"] = ["x" * 300_000]
    else:
        nested: object = "leaf"
        for _ in range(70):
            nested = [nested]
        value["unknown"] = nested
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    response = _response(output, raw=raw)
    with pytest.raises(ProviderFailure) as captured:
        _provider(_FakeClient([response])).invoke(request)
    assert captured.value.kind in {
        ProviderFailureKind.MALFORMED_STRUCTURED_OUTPUT,
        ProviderFailureKind.SCHEMA_VALIDATION_FAILURE,
    }


@pytest.mark.malicious
def test_transport_rejects_oversized_arrays_below_the_byte_limit(
    simple_claim: ResearchClaim,
) -> None:
    request = _request(simple_claim)
    output = _output(request, simple_claim)
    value = output.model_dump(mode="json")
    value["exclusions"] = ["bounded exclusion"] * 257
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    with pytest.raises(ProviderFailure) as captured:
        _provider(_FakeClient([_response(output, raw=raw)])).invoke(request)
    assert captured.value.kind is ProviderFailureKind.MALFORMED_STRUCTURED_OUTPUT


@pytest.mark.malicious
def test_transport_rejects_refusal_and_truncation(simple_claim: ResearchClaim) -> None:
    request = _request(simple_claim)
    refusal = SimpleNamespace(
        _request_id="request_refusal",
        id="response_refusal",
        model="operator-model",
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="refusal", refusal="safety policy")],
            )
        ],
        output_text="",
        output_parsed=None,
        status="completed",
        incomplete_details=None,
        usage=None,
    )
    with pytest.raises(ProviderFailure) as refused:
        _provider(_FakeClient([refusal])).invoke(request)
    assert refused.value.kind is ProviderFailureKind.SAFETY_REFUSAL
    assert refused.value.attempts[0].request_id == "request_refusal"
    assert refused.value.attempts[0].response_id == "response_refusal"

    truncated = _response(_output(request, simple_claim))
    truncated.status = "incomplete"
    truncated.incomplete_details = SimpleNamespace(reason="max_output_tokens")
    with pytest.raises(ProviderFailure) as incomplete:
        _provider(_FakeClient([truncated])).invoke(request)
    assert incomplete.value.kind is ProviderFailureKind.TRUNCATED
    assert incomplete.value.attempts[0].response_id == "response_official_1"
    assert incomplete.value.attempts[0].usage["total_tokens"] == 150


@pytest.mark.malicious
def test_timeout_retries_are_one_result_with_complete_attempts(simple_claim: ResearchClaim) -> None:
    request = _request(simple_claim)
    output = _output(request, simple_claim)
    timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))
    client = _FakeClient([timeout, _response(output)])
    result = _provider(client, maximum_retries=1).invoke(request)

    assert len(result.observational_provenance.attempts) == 2
    assert result.observational_provenance.retry_count == 1
    assert result.observational_provenance.attempts[0].outcome.value == "timeout"
    assert result.semantic_provenance.validated_output_sha256 == canonical_sha256(output)


@pytest.mark.malicious
def test_retry_exhaustion_rate_limit_network_and_auth_are_distinct(
    simple_claim: ResearchClaim,
) -> None:
    request = _request(simple_claim)
    http_request = httpx.Request("POST", "https://api.openai.com")
    rate_response = httpx.Response(
        429,
        request=http_request,
        headers={
            "authorization": "must-not-be-retained",
            "retry-after": "2",
            "x-ratelimit-remaining-requests": "0",
        },
    )
    rate_errors = [
        openai.RateLimitError("limited", response=rate_response, body=None),
        openai.RateLimitError("limited", response=rate_response, body=None),
    ]
    with pytest.raises(ProviderFailure) as limited:
        _provider(_FakeClient(rate_errors), maximum_retries=1).invoke(request)
    assert limited.value.kind is ProviderFailureKind.RATE_LIMITED
    assert len(limited.value.attempts) == 2
    assert limited.value.attempts[0].rate_limit_observations == {
        "retry-after": "2",
        "x-ratelimit-remaining-requests": "0",
    }
    assert "authorization" not in limited.value.attempts[0].rate_limit_observations

    connection_error = openai.APIConnectionError(request=http_request)
    with pytest.raises(ProviderFailure) as network:
        _provider(_FakeClient([connection_error])).invoke(request)
    assert network.value.kind is ProviderFailureKind.TRANSPORT_FAILURE

    auth_response = httpx.Response(401, request=http_request)
    auth_error = openai.AuthenticationError(
        "credential rejected",
        response=auth_response,
        body=None,
    )
    with pytest.raises(ProviderFailure) as authentication:
        _provider(_FakeClient([auth_error])).invoke(request)
    assert authentication.value.kind is ProviderFailureKind.AUTHENTICATION_FAILURE

    bad_response = httpx.Response(400, request=http_request)
    unsupported_error = openai.BadRequestError(
        "structured output unsupported",
        response=bad_response,
        body=None,
    )
    with pytest.raises(ProviderFailure) as unsupported:
        _provider(_FakeClient([unsupported_error])).invoke(request)
    assert unsupported.value.kind is ProviderFailureKind.UNSUPPORTED_MODEL_CAPABILITY

    server_response = httpx.Response(503, request=http_request)
    server_error = openai.InternalServerError(
        "provider unavailable",
        response=server_response,
        body=None,
    )
    with pytest.raises(ProviderFailure) as server:
        _provider(_FakeClient([server_error])).invoke(request)
    assert server.value.kind is ProviderFailureKind.TRANSPORT_FAILURE
    assert server.value.attempts[-1].retryable is True


@pytest.mark.malicious
def test_provider_failure_and_tool_output_are_distinct_policy_failures(
    simple_claim: ResearchClaim,
) -> None:
    request = _request(simple_claim)
    output = _output(request, simple_claim)
    failed = _response(output)
    failed.status = "failed"
    with pytest.raises(ProviderFailure) as refusal:
        _provider(_FakeClient([failed])).invoke(request)
    assert refusal.value.kind is ProviderFailureKind.PROVIDER_REFUSAL

    side_effect = _response(output)
    side_effect.output = [SimpleNamespace(type="local_shell_call")]
    with pytest.raises(ProviderFailure) as policy:
        _provider(_FakeClient([side_effect])).invoke(request)
    assert policy.value.kind is ProviderFailureKind.SEMANTIC_POLICY_FAILURE


def test_same_request_with_changed_semantic_output_changes_only_semantic_identity(
    simple_claim: ResearchClaim,
) -> None:
    request = _request(simple_claim)
    first_output = _output(request, simple_claim)
    second_output = first_output.model_copy(
        update={"exclusions": ("Alternative bounded synthetic exclusion",)}
    )
    first = _provider(_FakeClient([_response(first_output)])).invoke(request)
    second = _provider(_FakeClient([_response(second_output)])).invoke(request)
    assert first.semantic_provenance.canonical_request_sha256 == (
        second.semantic_provenance.canonical_request_sha256
    )
    assert first.semantic_hash != second.semantic_hash


@pytest.mark.malicious
def test_secret_in_transport_exception_is_not_exposed(simple_claim: ResearchClaim) -> None:
    request = _request(simple_claim)
    secret = "sk" + "-example-secret-that-must-not-leak"
    error = openai.APIConnectionError(
        message=f"connection failed with {secret}",
        request=httpx.Request("POST", "https://api.openai.com"),
    )
    with pytest.raises(ProviderFailure) as captured:
        _provider(_FakeClient([error])).invoke(request)
    assert secret not in str(captured.value)
    assert secret not in captured.value.safe_detail
