# OpenAI Build Week submission baseline verification — 2026-07-22

This historical record captures the verified OpenAI Build Week submission baseline before
submission-specific repository edits on 2026-07-22. It contains public repository and release
identities only. It does not contain credentials, private paths, generated demo artifacts, or
private evidence. It is not the current release manifest.

## Protected baselines

| Repository | Branch | Verified clean HEAD |
| --- | --- | --- |
| QuantForge | `main` | `09318da86cace5b54fedaea3a8a39a106c764965` |
| C++ numerical engine | `main` | `f6ae42da9d80cbacfc722c6d7ea28e3d0206aa9c` |

Both working trees and indexes were clean. The C++ repository was treated as read-only.

## QuantForge `v0.1.0`

- Annotated tag object: `c461cbb20cf600d737e3d46ecbadc2696ef1b647`
- Peeled target: `50c73f8a1bc6c7abea64edcf8a2f50e5e3dd2dec`
- Release: [QuantForge AI v0.1.0](https://github.com/MrithunjoyB/quantforge-ai/releases/tag/v0.1.0)
- Published, non-draft, non-prerelease
- GitHub-native immutable: **true**
- Uploaded assets: 7

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `SHA256SUMS` | 611 | `bb20962664269193711c7c3679a3ac69b0f2daf80fc9599dc37d402d3fd5400b` |
| `determinism-validation.json` | 3,557 | `0eb088d082dfd2ffd187c64444c93336f07e0532855ae81d7ae3afb89d373020` |
| `quantforge-ai-v0.1.0-release-validation.json` | 13,758 | `9e34d7a55403d2cfdf0618a0f067c798c8d4ab00e806bc430fc8230b330059ce` |
| `quantforge-ai-v0.1.0-release-validation.md` | 2,086 | `1377a8f57568da249028dd0f72a5cc112b14ce8b6de35a805fbcfed6f012ea81` |
| `quantforge-ai-v0.1.0-sbom.cdx.json` | 18,559 | `3df44fe13627dab65aee9c5d30fa8694196f94e136fd16f12dd0d6b93fc75230` |
| `quantforge_ai-0.1.0-py3-none-any.whl` | 50,611 | `bdc9baa2b3cb2e14c35df494b8c472d1058cd2e6fd6b7024190fbdd5378e2be6` |
| `quantforge_ai-0.1.0.tar.gz` | 114,784 | `afdc677576a1505c57e0b811d28186c49a4b8138b8767d618de7b0dcbb6e5e1c` |

The recorded post-release verification downloaded every asset, verified every SHA-256, checked the
checksum file and SBOM, and installed the wheel outside the source tree.

## C++ numerical engine `v1.0.0`

- Annotated tag object: `20ac53c5e4b61ae7b431d5bb263f246e35f8d2a2`
- Peeled target: `2f86b71dbc9f29dbda861942d8afbb10c04b6625`
- Release: [cpp-event-driven-backtester v1.0.0](https://github.com/MrithunjoyB/cpp-event-driven-backtester/releases/tag/v1.0.0)
- Published, non-draft, non-prerelease
- Tag protected and published assets hash-verified: **true**
- GitHub-native immutable: **false**
- Published assets: 12

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `SHA256SUMS` | 1,185 | `9abaae1e956c96d4e5d80d25b967b8f9b06d5b6c58e182a6ae33dcc16d670556` |
| `cpp-event-driven-backtester-v1.0.0-linux-x86_64.tar.gz` | 750,507 | `749a5f1c81d03407e689e195b6f7c2e40a78f4dcca1750a7162cd71f5afb6ecb` |
| `cpp-event-driven-backtester-v1.0.0-macos-arm64.tar.gz` | 654,609 | `50a3b29c3eb7374694c8a1d7379bae704edb63a9d940bf61037db290f91490d5` |
| `cpp-event-driven-backtester-v1.0.0-release-notes.md` | 4,258 | `71ea8076974eab9f43dc20fdd7cd9520605882654d2916d87f898ac731ad9603` |
| `cpp-event-driven-backtester-v1.0.0-release-validation-report.json` | 962 | `152df5314b15b424d95a17c63443ddb7eae571f5fea6d86c1f0333628b5540ad` |
| `cpp-event-driven-backtester-v1.0.0-reproducibility.tar.gz` | 910,775 | `93db985c797a02b25ce690971fa67166a54f71572f5a493290b737336784bd98` |
| `cpp-event-driven-backtester-v1.0.0-sbom.spdx.json` | 27,070 | `d8f86a0c5803bdf430276753785e77db229d719f63046c5a7012ba469c3ac083` |
| `linux-package-smoke.json` | 449 | `3e1f65bc782d49cd164e774c8e8f26347444be60b40c60a9e0663e56946ae064` |
| `linux-toolchain.txt` | 161 | `0fb2b7600daf68adb3ab7c66cca1e358ff93ca5b385e4100d308085d8a75f8e3` |
| `macos-package-smoke.json` | 448 | `f76acc842345ac6c57b9e494b10dc1825d81b39a751adbcb4c8d180038deb28a` |
| `macos-toolchain.txt` | 164 | `8b7033ef5c026e0be055d5d0ca40f10a51741a36695a1873d1c9b1b544898717` |
| `release-aggregation-toolchain.txt` | 60 | `e5e656f8cdc21ee0fbc81e9c7ce9620d35580189c789eaf1c20c56213dc74f77` |

This release is accurately described as tag-protected and asset-hash verified. Its native GitHub
immutable-release flag is not enabled, so the package does not claim that it is GitHub-native
immutable. No tag or release asset was changed during submission preparation.

## Pre-write reconstruction and gates

- Flagship governed demo: passed.
- Demonstration label: `OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER`.
- Verdict: `INCONCLUSIVE`.
- Demonstration semantic SHA-256:
  `412c0fb423eedfcdf429caa54568fb99356425e2bd25af99b1852932305f990e`.
- Durable case reconstruction: 12 revisions, 6 governed role results, 0 duplicate transitions.
- Comparative evaluation: 24 cases, 3 architectures, 72 results; export verification and replay
  passed.
- Comparative suite semantic SHA-256:
  `78b67143e87158cb4ab9bdb4ca350e6118de1e4419e630f574852e48f1a0131e`.
- Formatting, Ruff, strict mypy, malicious-input tests, repository policy, secret scan, CFF
  validation, source build, wheel build, and package inspection: passed.
- Main test phase: 556 passed, 1 environment-gated C++ integration test skipped; the same C++ path
  was exercised successfully by the governed flagship reconstruction.
- Combined coverage: 90.37%; governance-critical combined coverage: 90.25%.
- Runtime and development lockfile vulnerability audits: no known vulnerabilities found.

These are baseline records, not a substitute for rerunning the affected gates on the final pull
request commit and after the protected merge.
