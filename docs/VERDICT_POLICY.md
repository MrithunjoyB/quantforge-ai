# Verdict Policy

Policy version `1.0` is a pure function over explicit typed inputs. It is intentionally conservative:

- methodology rejection or unresolved critical findings produce `REJECTED`;
- methodology revision, incomplete experiments, invalid evidence, or unverified reconstruction
  produce `INCONCLUSIVE`;
- unresolved corrected inference, null or mixed direction, or absent practical significance produce
  `INCONCLUSIVE`; a validated direction opposite the locked hypothesis produces `REJECTED`;
- failed robustness, high cost sensitivity, unstable parameters or regimes, or high concentration
  produce `FRAGILE`; validated contradictory evidence also caps the result at `FRAGILE`;
- all strict gates, with no contradictions or unresolved limitations, produce `SUPPORTED`;
- remaining positive cases with noncritical limitations produce `PROVISIONALLY_SUPPORTED`.

Inputs are reconstructed from the locked hypothesis, methodology review, evidence ledger,
statistical review, adversarial review, reproducibility review, and unresolved findings. Fixture
labels and free-form provider flags are not policy inputs. The returned eligibility includes policy
version, decisive and contradictory evidence, reasons, and timestamp. The Chair constructor and case
model require exact verdict and evidence equality.
