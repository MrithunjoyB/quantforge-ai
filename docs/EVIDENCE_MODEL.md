# Evidence Model

Every evidence object records stable and schema identities, case, related claims and experiment,
locked constitution hash, adapter and safe relative artifact, source-artifact digest, optional
normalized JSON pointer, content digest, timestamp, validation status and method, structured numeric
facts and closed units, assumptions, limitations, relationship, and provenance.

The ledger accepts only new identifiers and exact case, experiment, constitution, and claim bindings.
Objects are immutable; replacement is not supported. Numeric fact identifiers, values, and units
must exactly equal the `content.facts` mapping covered by the content digest. Package-owned mock
artifacts are checked for existence, containment, regular-file status, symlink traversal, size, and
SHA-256 identity before admission. A reference can cite facts only by evidence and fact identifier.
Review and Chair boundaries require referenced evidence to be validated and every fact identifier to
exist. Unstructured reviewer narratives reject ordinary, exponent, and non-finite numerical forms.

The claim graph has claim, evidence, and amendment nodes with `supports`, `contradicts`, `qualifies`,
`derived_from`, and `amends` edges. Edge types have a closed source/target matrix; cycles and semantic
duplicates are rejected; snapshots are identifier-sorted. Evidence node hashes, validation statuses,
inventories, and relationship edges are checked against the ledger. Each substantive final claim
must have a reachable validated evidence node.
