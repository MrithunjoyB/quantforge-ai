# QuantForge architecture

This is the judge-facing, screenshot-ready view of the governed flagship path.

```mermaid
flowchart LR
    claim["Research claim"] --> researcher["Researcher<br/>proposal"]
    researcher --> method["Methodology<br/>review"]
    method --> approval["Human<br/>approval"]
    approval --> constitution["Locked<br/>constitution"]
    constitution --> cpp["Trusted C++<br/>execution"]
    cpp --> stats["Statistical<br/>review"]
    stats --> adversarial["Adversarial<br/>review"]
    adversarial --> repro["Reproducibility<br/>review"]
    repro --> verdict["Code-owned<br/>verdict"]
    verdict --> chair["Chair<br/>explanation"]
    chair --> export["Export<br/>and replay"]

    authority["Deterministic QuantForge authority<br/>workflow · schemas · admission · verdict policy"]
    evidence[("C++ numerical<br/>evidence")]
    audit[("Durable evidence<br/>and audit state")]

    approval -. governed by .-> authority
    constitution -. locked by .-> authority
    cpp --> evidence
    evidence --> audit
    researcher -. recorded in .-> audit
    method -. recorded in .-> audit
    stats -. recorded in .-> audit
    adversarial -. recorded in .-> audit
    repro -. recorded in .-> audit
    authority --> verdict
    audit --> verdict
    export --> audit

    classDef model fill:#e8f0fe,stroke:#356ac3,color:#102a43;
    classDef deterministic fill:#e8f5e9,stroke:#2e7d32,color:#17351a;
    classDef numeric fill:#fff3e0,stroke:#ef6c00,color:#4e2600;
    classDef durable fill:#f3e5f5,stroke:#7b1fa2,color:#32103f;
    class researcher,method,stats,adversarial,repro,chair model;
    class approval,constitution,verdict,authority deterministic;
    class cpp,evidence numeric;
    class audit,export durable;
```

## Legend

| Colour | Responsibility |
| --- | --- |
| Blue | Model-generated proposal, specialist review, or final explanation |
| Green | Deterministic QuantForge authority, including human approval capture and verdict limits |
| Orange | Trusted C++ numerical execution and admitted numerical evidence |
| Purple | Durable case, evidence, audit, export, and reconstruction state |

The model never crosses into the authority or numerical-evidence boundaries. It cannot approve a
case, change a locked constitution, run the engine, create admissible evidence, advance workflow
state, or strengthen the computed verdict.

## Screenshot guidance

- Use GitHub's light theme at 100% zoom.
- Capture the title, diagram, and legend together if they remain legible.
- If a 16:9 crop is required, capture the diagram first and the legend as a second insert.
- Keep the colour legend visible when this diagram is used without narration.
