# Threat Model

| Threat | Control | Residual limitation |
| --- | --- | --- |
| Prompt injection | No live model; future provider behind typed adapter and role authority | Future prompts require separate evaluation |
| Evidence injection | Strict schema, content hash, constitution binding, append-only ledger | Source truth still depends on approved adapters |
| Fabricated citations | Case/experiment-bound ledger existence, status, fact, and graph checks | Semantic source quality needs future adapter controls |
| Fabricated numerical claims | Facts and closed units must match hashed structured content; numerical prose is rejected | Future provider UX must render structured facts safely |
| Schema bypass | Strict types, forbidden unknown fields, defensive JSON parser | Schema migrations require governance review |
| Post-lock mutation | Frozen constitution, hash recomputation, separate amendments | Persistence-level concurrency is future work |
| Audit tampering, deletion, reordering | Hashed payloads, strict single-case transition replay, and complete-chain requirement | A fully rehashed chain needs an external trusted anchor to prove prior publication |
| Path traversal and artifact references | Normalized relative paths, every-component symlink rejection, containment, and source digest | Remote object references are not implemented |
| Malicious serialized input | Size, depth, duplicates, float and non-finite rejection | Resource isolation beyond process limits is future work |
| Replay attacks | Single-case identity, ordered actor/action sequence, payload reconstruction, immutable constitution identity | Cross-system nonce registry is not implemented |
| Verdict escalation | Pure policy and exact Chair equality/strength checks | Policy changes require version review |
| Role authority violations | Explicit per-role allow list | Provider-specific tool permissions are future work |
| Accidental real trading | No broker/order domain or adapter; research-only scope literal | Future execution remains prohibited |
| Secrets exposure | No API key; ignore rules and local secret scan | Repository hosting scans are not configured locally |
