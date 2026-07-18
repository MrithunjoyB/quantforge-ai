# OpenAI Provider Runbook

Normal tests, demos, builds, wheel/sdist smoke tests, exports, and C++ integration are offline. The
default `ProviderSelection()` is `mock`; supplying an OpenAI configuration while mock mode is active
is rejected. OpenAI use requires all three explicit operator settings:

```bash
export QUANTFORGE_LIVE_OPENAI=1
export OPENAI_MODEL='<operator-selected-official-model-or-snapshot>'
export OPENAI_API_KEY='<credential-from-approved-secret-store>'
.venv/bin/python -m scripts.verify_openai_provider_live
```

The command prints its enforced maximum before network access: exactly six calls, one per governed
role, with SDK retries set to zero. It uses a bounded non-sensitive packaged synthetic case, verifies
each schema and provenance record, and proves a mutated Chair verdict is rejected. It contacts only
the official OpenAI API—no broker, market-data source, tool, URL, filesystem target, or external
execution service. It writes no file and never prints credentials or sensitive headers.

If the flag, model, or key is absent, the command exits blocked before a call. A refusal, timeout,
transport error, unsupported structured-output capability, malformed output, schema failure, or
policy failure exits nonzero and prints only sanitized detail. Do not substitute an unofficial
router, gateway, wrapper, or hard-coded fallback model.

The successful summary has deterministic field ordering and contains the six semantic hashes, exact
operator model, provider, and call count. The hashes and model output are inherently nondeterministic
between live runs. Token usage, latency, request IDs, and retry observations remain operational data
and do not change semantic identity. Use recorded usage for cost analysis; the harness provides no
cost promise and prevents more than six calls per invocation.

Never place real credentials in command history, configuration files, test fixtures, snapshots,
case content, or bug reports. Rotate a key immediately if exposure is suspected. An offline-green
merge does not establish live-provider success; report live verification as blocked unless this
exact opt-in command completed against an eligible operator-selected model.
