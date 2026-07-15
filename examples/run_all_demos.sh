#!/usr/bin/env bash
set -euo pipefail

for scenario in provisional fragile inconclusive; do
  quantforge case run-demo --scenario "${scenario}" --output-dir "quantforge-demo-${scenario}"
done
