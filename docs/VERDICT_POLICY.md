# Verdict Policy

Policy version `1.0` is a pure function over explicit typed inputs. It is intentionally conservative:

- methodology rejection or unresolved critical findings produce `REJECTED`;
- incomplete experiments, invalid evidence, or unverified reconstruction produce `INCONCLUSIVE`;
- unresolved corrected inference, nonpositive direction, or absent practical significance produce
  `INCONCLUSIVE`;
- failed robustness, high cost sensitivity, unstable parameters or regimes, or high concentration
  produce `FRAGILE`;
- all strict gates, with no contradictions or unresolved limitations, produce `SUPPORTED`;
- remaining positive cases with noncritical limitations produce `PROVISIONALLY_SUPPORTED`.

The returned eligibility includes policy version, decisive reasons, evidence references, and a
timestamp. The Chair constructor requires exact verdict equality and separately rejects any stronger
requested verdict.
