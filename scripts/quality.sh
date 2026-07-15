#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-.venv/bin/python}"

"${PYTHON}" -m ruff format --check src tests scripts
"${PYTHON}" -m ruff check src tests scripts
"${PYTHON}" -m mypy src/quantforge scripts/check_secrets.py
PYTHONPATH=src "${PYTHON}" -m pytest \
  --cov=quantforge --cov-branch --cov-report=term-missing --cov-report=xml
"${PYTHON}" -m coverage report \
  --include='src/quantforge/audit/*,src/quantforge/domain/*,src/quantforge/evidence/*,src/quantforge/roles/*,src/quantforge/serialization/*,src/quantforge/verdict/*,src/quantforge/workflow/*' \
  --fail-under=90
"${PYTHON}" scripts/check_secrets.py
"${PYTHON}" -m build --no-isolation

if [[ "${RUN_DEPENDENCY_AUDIT:-0}" == "1" ]]; then
  "${PYTHON}" -m pip_audit -r requirements.lock --disable-pip
fi
