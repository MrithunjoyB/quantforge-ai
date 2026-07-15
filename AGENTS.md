# QuantForge AI repository guidance

- Phase 1 is offline, deterministic, and non-executing. Never add broker, order, or live-trading behavior.
- Treat `../cpp-event-driven-backtester` as a protected read-only external release. Never edit it.
- Preserve strict schemas, canonical hashing, state transitions, evidence validation, and verdict limits.
- Do not add shell or unrestricted filesystem tools to role providers.
- Run `scripts/quality.sh` before committing. Fix root causes; do not weaken gates.
- Keep generated demos, caches, credentials, environment files, and absolute local paths untracked.
