#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-.venv/bin/python}"
CFFCONVERT="${CFFCONVERT:-$(dirname "${PYTHON}")/cffconvert}"

"${PYTHON}" -m ruff format --check src tests scripts
"${PYTHON}" -m ruff check src tests scripts
"${PYTHON}" -m mypy src/quantforge scripts
"${PYTHON}" -m pytest \
  --cov=quantforge --cov-branch --cov-report=term-missing --cov-report=xml \
  --cov-report=json:.critical-coverage.json
"${PYTHON}" -m scripts.check_critical_coverage \
  --coverage-json=.critical-coverage.json --minimum=90
"${PYTHON}" -m pytest -m malicious
"${PYTHON}" -m scripts.check_repository
"${PYTHON}" -m scripts.check_secrets
"${CFFCONVERT}" --validate -i CITATION.cff
"${PYTHON}" -m build --no-isolation
"${PYTHON}" -m scripts.inspect_packages --dist-dir dist

if [[ "${RUN_DEPENDENCY_AUDIT:-0}" == "1" ]]; then
  "${PYTHON}" -m pip_audit -r requirements.lock --disable-pip --strict \
    --cache-dir "${PIP_AUDIT_CACHE_DIR:-.release-work/pip-audit-cache}"
  "${PYTHON}" -m pip_audit -r requirements-dev.lock --disable-pip --strict \
    --cache-dir "${PIP_AUDIT_CACHE_DIR:-.release-work/pip-audit-cache}"
fi
