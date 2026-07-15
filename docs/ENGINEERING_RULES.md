# Engineering Rules

When behavior fails, reproduce it, isolate the root cause, repair the cause, add a regression test,
rerun affected checks, and refactor when the design requires it. Never relax a schema, evidence gate,
state transition, hash identity, verdict limit, safety boundary, or test solely to pass validation.

Changes must be deterministic offline, keep direct dependencies exactly pinned, preserve canonical
representations, and use typed provider boundaries. The C++ sibling is read-only. Live trading and
arbitrary shell authority are outside the project boundary.
