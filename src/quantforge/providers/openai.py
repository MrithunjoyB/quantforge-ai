"""Official OpenAI Responses API transport for governed structured role output."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Protocol, cast

import openai
from openai import OpenAI

from quantforge.domain.models import StrictModel
from quantforge.providers.config import (
    CredentialSource,
    EnvironmentCredentialSource,
    OpenAIProviderConfig,
)
from quantforge.providers.failures import ProviderFailure, ProviderFailureKind
from quantforge.providers.strict_output import validate_structured_output
from quantforge.roles.contracts import (
    ProviderAttemptObservation,
    ProviderCallContext,
    ProviderObservationalProvenance,
    ProviderResult,
    ProviderResultAny,
    ProviderTransportOutcome,
    create_provider_result,
)
from quantforge.roles.governance import role_contract
from quantforge.roles.requests import GovernedRoleRequest
from quantforge.serialization.canonical import canonical_sha256

_RETRY_DELAYS_SECONDS = (0.25, 1.0)
OFFICIAL_OPENAI_BASE_URL = "https://api.openai.com/v1"
_RATE_LIMIT_HEADER_NAMES = frozenset(
    {
        "retry-after",
        "x-ratelimit-limit-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens",
    }
)


class _ResponsesAPI(Protocol):
    def parse(self, **kwargs: object) -> object: ...


class _OpenAIClient(Protocol):
    responses: _ResponsesAPI


class _Response(Protocol):
    id: str
    model: str
    output: list[object]
    output_text: str
    output_parsed: object | None
    status: str | None
    incomplete_details: object | None
    usage: object | None


def _now() -> datetime:
    return datetime.now(UTC)


def _usage(response: _Response) -> dict[str, int]:
    usage = response.usage
    if usage is None:
        return {}
    observations: dict[str, int] = {}
    for source, target in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        value = getattr(usage, source, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            observations[target] = value
    return observations


def _request_id(value: object) -> str | None:
    candidate = getattr(value, "_request_id", None) or getattr(value, "request_id", None)
    return candidate[:200] if isinstance(candidate, str) and candidate else None


def _provider_status(value: object) -> str | None:
    status = getattr(value, "status", None) or getattr(value, "status_code", None)
    return str(status)[:100] if status is not None else None


def _rate_limit_observations(value: object) -> dict[str, str | int]:
    response = getattr(value, "response", None) or value
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return {}
    observations: dict[str, str | int] = {}
    for name, header_value in headers.items():
        normalized = str(name).casefold()
        if normalized in _RATE_LIMIT_HEADER_NAMES:
            observations[normalized] = str(header_value)[:200]
    return dict(sorted(observations.items()))


def _contains_refusal(response: _Response) -> bool:
    for item in response.output:
        for content in getattr(item, "content", ()):
            if getattr(content, "type", None) == "refusal":
                return True
    return False


def _contains_tool_or_side_effect(response: _Response) -> bool:
    harmless = {"message", "reasoning"}
    return any(getattr(item, "type", None) not in harmless for item in response.output)


class OpenAIStructuredRoleProvider:
    """Return typed advisory data only; this object has no store, engine, or tools."""

    def __init__(
        self,
        config: OpenAIProviderConfig,
        *,
        credential_source: CredentialSource | None = None,
        client: _OpenAIClient | None = None,
        clock: Callable[[], datetime] = _now,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._clock = clock
        self._monotonic = monotonic
        self._sleeper = sleeper
        if client is None:
            source = credential_source or EnvironmentCredentialSource()
            try:
                api_key = source.api_key()
            except Exception:
                raise RuntimeError(
                    "OpenAI credentials are unavailable from the configured source"
                ) from None
            self._client = cast(
                _OpenAIClient,
                OpenAI(
                    api_key=api_key,
                    base_url=OFFICIAL_OPENAI_BASE_URL,
                    max_retries=0,
                    timeout=float(config.timeout_seconds),
                ),
            )
        else:
            self._client = client

    @property
    def provider_identity(self) -> str:
        return "openai"

    @property
    def model_snapshot(self) -> str:
        """Return the explicitly requested identifier until a response supplies its snapshot."""

        return self._config.model

    @property
    def endpoint_class(self) -> str:
        return "responses.parse"

    @property
    def sdk_version(self) -> str:
        return version("openai")

    def invoke(self, request: GovernedRoleRequest) -> ProviderResultAny:
        contract = role_contract(request.action)
        attempts: list[ProviderAttemptObservation] = []
        for attempt_index in range(self._config.maximum_retries + 1):
            response: _Response | None = None
            raw = ""
            requested_at = self._clock()
            started = self._monotonic()
            try:
                candidate = self._client.responses.parse(
                    input=list(request.provider_input()),
                    max_output_tokens=min(
                        request.maximum_output_tokens,
                        contract.maximum_output_tokens,
                    ),
                    model=self._config.model,
                    parallel_tool_calls=False,
                    store=False,
                    text_format=contract.output_type,
                    tools=[],
                    truncation="disabled",
                )
                response = cast(_Response, candidate)
                raw = response.output_text
                self._validate_response_status(response)
                output = self._validate_response_output(response, raw, contract.output_type)
            except Exception as error:
                kind, outcome, retryable = self._classify(error)
                observation_source: object = response if response is not None else error
                observation = self._attempt_observation(
                    attempt_index=attempt_index,
                    requested_at=requested_at,
                    started=started,
                    outcome=outcome,
                    retryable=retryable,
                    source=observation_source,
                    response_id=response.id if response is not None else None,
                    usage=_usage(response) if response is not None else {},
                    refusal=kind
                    in {ProviderFailureKind.PROVIDER_REFUSAL, ProviderFailureKind.SAFETY_REFUSAL},
                    truncated=kind is ProviderFailureKind.TRUNCATED,
                )
                attempts.append(observation)
                if retryable and attempt_index < self._config.maximum_retries:
                    self._sleeper(_RETRY_DELAYS_SECONDS[attempt_index])
                    continue
                raise ProviderFailure(
                    kind,
                    attempts=tuple(attempts),
                    safe_detail=self._safe_failure_detail(kind),
                ) from None

            accepted = self._attempt_observation(
                attempt_index=attempt_index,
                requested_at=requested_at,
                started=started,
                outcome=ProviderTransportOutcome.ACCEPTED,
                retryable=False,
                source=response,
                response_id=response.id,
                usage=_usage(response),
                refusal=False,
                truncated=False,
            )
            attempts.append(accepted)
            return cast(
                ProviderResultAny,
                self._result(request, output, response, raw, tuple(attempts)),
            )

        raise AssertionError("bounded provider loop exited without a result")  # pragma: no cover

    def _validate_response_status(self, response: _Response) -> None:
        if response.status == "incomplete" or response.incomplete_details is not None:
            raise _TruncatedResponse
        if _contains_refusal(response):
            raise _SafetyRefusal
        if response.status not in {None, "completed"}:
            raise _ProviderRefusal
        if _contains_tool_or_side_effect(response):
            raise _SemanticPolicyFailure

    def _validate_response_output[OutputT: StrictModel](
        self, response: _Response, raw: str, output_type: type[OutputT]
    ) -> OutputT:
        try:
            output = validate_structured_output(
                raw,
                output_type,
                maximum_response_bytes=self._config.maximum_response_bytes,
            )
        except ValueError as error:
            if "domain schema" in str(error):
                raise _SchemaValidationFailure from error
            raise _MalformedStructuredOutput from error
        sdk_parsed = response.output_parsed
        if type(sdk_parsed) is not output_type or canonical_sha256(sdk_parsed) != canonical_sha256(
            output
        ):
            raise _SchemaValidationFailure
        return output

    def _result[OutputT: StrictModel](
        self,
        request: GovernedRoleRequest,
        output: OutputT,
        response: _Response,
        raw: str,
        attempts: tuple[ProviderAttemptObservation, ...],
    ) -> ProviderResult[OutputT]:
        final = attempts[-1]
        observations = ProviderObservationalProvenance(
            request_id=final.request_id or "unavailable",
            response_id=response.id,
            requested_at=attempts[0].requested_at,
            responded_at=final.responded_at,
            latency_ms=sum(attempt.latency_ms for attempt in attempts),
            usage=final.usage,
            retry_count=len(attempts) - 1,
            transport_outcome=ProviderTransportOutcome.ACCEPTED,
            provider_status=final.provider_status,
            rate_limit_observations=final.rate_limit_observations,
            attempts=attempts,
            transport_metadata={"official_endpoint": True, "response_stored_by_provider": False},
        )
        context = ProviderCallContext(
            role=request.role,
            action=request.action,
            case_id=request.case_id,
            case_revision=request.case_revision,
            constitution_identity=request.constitution_identity,
            amendment_chain_identity=request.amendment_chain_identity,
            evidence_references=request.evidence_references,
            context_item_identities=tuple(item.identity for item in request.context),
            role_context_sha256=request.context_identity,
            canonical_request_sha256=request.request_semantic_sha256,
        )
        digest = None
        if self._config.retain_raw_response_digest:
            digest = hashlib.sha256(raw.encode("utf-8", errors="strict")).hexdigest()
        return create_provider_result(
            result_type=ProviderResult[OutputT],
            action=request.action,
            output=output,
            provider_identity=self.provider_identity,
            requested_model=self._config.model,
            model_snapshot=response.model,
            endpoint_class=self.endpoint_class,
            sdk_version=self.sdk_version,
            observations=observations,
            call_context=context,
            raw_response_sha256=digest,
        )

    def _attempt_observation(
        self,
        *,
        attempt_index: int,
        requested_at: datetime,
        started: float,
        outcome: ProviderTransportOutcome,
        retryable: bool,
        source: object,
        response_id: str | None,
        usage: Mapping[str, int],
        refusal: bool,
        truncated: bool,
    ) -> ProviderAttemptObservation:
        responded_at = self._clock()
        elapsed = max(0.0, self._monotonic() - started)
        return ProviderAttemptObservation(
            attempt_index=attempt_index,
            request_id=_request_id(source),
            response_id=response_id,
            requested_at=requested_at,
            responded_at=responded_at,
            latency_ms=min(86_400_000, round(elapsed * 1_000)),
            outcome=outcome,
            provider_status=_provider_status(source),
            retryable=retryable,
            usage=dict(usage),
            rate_limit_observations=_rate_limit_observations(source),
            refusal=refusal,
            truncated=truncated,
        )

    @staticmethod
    def _classify(
        error: Exception,
    ) -> tuple[ProviderFailureKind, ProviderTransportOutcome, bool]:
        if isinstance(error, openai.AuthenticationError | openai.PermissionDeniedError):
            return (
                ProviderFailureKind.AUTHENTICATION_FAILURE,
                ProviderTransportOutcome.AUTHENTICATION_FAILURE,
                False,
            )
        if isinstance(error, openai.RateLimitError):
            return (
                ProviderFailureKind.RATE_LIMITED,
                ProviderTransportOutcome.RATE_LIMITED,
                True,
            )
        if isinstance(error, openai.APITimeoutError):
            return ProviderFailureKind.TIMEOUT, ProviderTransportOutcome.TIMEOUT, True
        if isinstance(error, openai.LengthFinishReasonError | _TruncatedResponse):
            return ProviderFailureKind.TRUNCATED, ProviderTransportOutcome.TRUNCATED, False
        if isinstance(error, openai.ContentFilterFinishReasonError | _SafetyRefusal):
            return (
                ProviderFailureKind.SAFETY_REFUSAL,
                ProviderTransportOutcome.SAFETY_REFUSAL,
                False,
            )
        if isinstance(error, _ProviderRefusal):
            return (
                ProviderFailureKind.PROVIDER_REFUSAL,
                ProviderTransportOutcome.PROVIDER_REFUSAL,
                False,
            )
        if isinstance(error, _MalformedStructuredOutput):
            return (
                ProviderFailureKind.MALFORMED_STRUCTURED_OUTPUT,
                ProviderTransportOutcome.MALFORMED_STRUCTURED_OUTPUT,
                False,
            )
        if isinstance(error, openai.APIResponseValidationError | _SchemaValidationFailure):
            return (
                ProviderFailureKind.SCHEMA_VALIDATION_FAILURE,
                ProviderTransportOutcome.SCHEMA_VALIDATION_FAILURE,
                False,
            )
        if isinstance(error, _SemanticPolicyFailure):
            return (
                ProviderFailureKind.SEMANTIC_POLICY_FAILURE,
                ProviderTransportOutcome.SEMANTIC_POLICY_FAILURE,
                False,
            )
        if isinstance(error, openai.BadRequestError | openai.UnprocessableEntityError):
            return (
                ProviderFailureKind.UNSUPPORTED_MODEL_CAPABILITY,
                ProviderTransportOutcome.UNSUPPORTED_MODEL_CAPABILITY,
                False,
            )
        if isinstance(error, openai.APIConnectionError):
            return (
                ProviderFailureKind.TRANSPORT_FAILURE,
                ProviderTransportOutcome.TRANSPORT_FAILURE,
                True,
            )
        if isinstance(error, openai.APIStatusError):
            retryable = getattr(error, "status_code", 0) >= 500
            return (
                ProviderFailureKind.TRANSPORT_FAILURE,
                ProviderTransportOutcome.TRANSPORT_FAILURE,
                retryable,
            )
        return (
            ProviderFailureKind.TRANSPORT_FAILURE,
            ProviderTransportOutcome.TRANSPORT_FAILURE,
            False,
        )

    @staticmethod
    def _safe_failure_detail(kind: ProviderFailureKind) -> str:
        details = {
            ProviderFailureKind.AUTHENTICATION_FAILURE: "official provider authentication failed",
            ProviderFailureKind.MALFORMED_STRUCTURED_OUTPUT: (
                "response was not one strict JSON object"
            ),
            ProviderFailureKind.PROVIDER_REFUSAL: "provider declined the structured request",
            ProviderFailureKind.RATE_LIMITED: "bounded rate-limit retries were exhausted",
            ProviderFailureKind.SAFETY_REFUSAL: "provider returned a safety refusal",
            ProviderFailureKind.SCHEMA_VALIDATION_FAILURE: (
                "response did not satisfy the governed schema"
            ),
            ProviderFailureKind.SEMANTIC_POLICY_FAILURE: (
                "response attempted a prohibited side effect"
            ),
            ProviderFailureKind.TIMEOUT: "bounded provider timeout retries were exhausted",
            ProviderFailureKind.TRANSPORT_FAILURE: "bounded transport retries were exhausted",
            ProviderFailureKind.TRUNCATED: "provider response was incomplete",
            ProviderFailureKind.UNSUPPORTED_MODEL_CAPABILITY: (
                "operator-selected model did not accept the governed structured request"
            ),
        }
        return details[kind]


class _ProviderRefusal(Exception):
    pass


class _SafetyRefusal(Exception):
    pass


class _TruncatedResponse(Exception):
    pass


class _MalformedStructuredOutput(Exception):
    pass


class _SchemaValidationFailure(Exception):
    pass


class _SemanticPolicyFailure(Exception):
    pass


__all__ = ["OFFICIAL_OPENAI_BASE_URL", "OpenAIStructuredRoleProvider"]
