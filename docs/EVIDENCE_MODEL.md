# Evidence Model

Every evidence object records stable and schema identities, related claims and experiment, locked
constitution hash, adapter and safe relative artifact, optional structured location, content digest,
timestamp, validation status and method, structured numeric facts and units, assumptions,
limitations, relationship, and provenance.

The ledger accepts only new identifiers, the active constitution hash, and known claim identifiers.
Objects are immutable; replacement is not supported. A reference can cite facts only by evidence and
fact identifier. Review and Chair boundaries require referenced evidence to be validated and every
fact identifier to exist. Unstructured reviewer narratives reject numerical tokens so numerical
assertions cannot evade this mechanism.

The claim graph has claim, evidence, and amendment nodes with `supports`, `contradicts`, `qualifies`,
`derived_from`, and `amends` edges. Endpoint and identifier validation are strict. Each substantive
final claim must have a reachable evidence node.
