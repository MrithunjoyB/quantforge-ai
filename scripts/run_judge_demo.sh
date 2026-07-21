#!/usr/bin/env bash
set -euo pipefail

DEMONSTRATION_LABEL="OFFLINE GOVERNED DEMONSTRATION — MOCK PROVIDER"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_judge_demo.sh CPP_REPOSITORY OUTPUT_DIRECTORY [WORK_ROOT]

Builds the protected C++ v1.0.0 executable outside both source trees, runs the
offline governed mock-provider demonstration, writes its reports, and verifies
the complete artifact set.

Environment:
  QUANTFORGE_CLI  Optional path to an installed quantforge executable.
EOF
}

fail() {
  echo "judge demo: $*" >&2
  exit 1
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "$#" -lt 2 || "$#" -gt 3 ]]; then
  usage >&2
  exit 2
fi

for required_command in git cmake; do
  command -v "${required_command}" >/dev/null 2>&1 \
    || fail "required command is unavailable: ${required_command}"
done

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
quantforge_repository="$(git -C "${script_directory}" rev-parse --show-toplevel 2>/dev/null)" \
  || fail "the wrapper must be run from a QuantForge source checkout"

cpp_repository="$1"
[[ -d "${cpp_repository}" && ! -L "${cpp_repository}" ]] \
  || fail "CPP_REPOSITORY must be a non-symlink directory"
cpp_repository="$(cd "${cpp_repository}" && pwd -P)"
cpp_repository_root="$(git -C "${cpp_repository}" rev-parse --show-toplevel 2>/dev/null)" \
  || fail "CPP_REPOSITORY is not a Git checkout"
[[ "${cpp_repository}" == "${cpp_repository_root}" ]] \
  || fail "CPP_REPOSITORY must name the checkout root"
[[ -z "$(git -C "${cpp_repository}" status --porcelain=v1 --untracked-files=all)" ]] \
  || fail "the protected C++ repository is not clean"

output_directory="$2"
[[ "${output_directory}" == /* ]] || fail "OUTPUT_DIRECTORY must be absolute"
output_parent="$(dirname "${output_directory}")"
[[ -d "${output_parent}" && ! -L "${output_parent}" ]] \
  || fail "the output parent must be an existing non-symlink directory"
output_directory="$(cd "${output_parent}" && pwd -P)/$(basename "${output_directory}")"
[[ ! -e "${output_directory}" ]] || fail "OUTPUT_DIRECTORY already exists"

case "${output_directory}/" in
  "${quantforge_repository}/"*|"${cpp_repository}/"*)
    fail "OUTPUT_DIRECTORY must be outside both source trees"
    ;;
esac

if [[ "$#" -eq 3 ]]; then
  work_root="$3"
elif [[ -d /private/tmp && ! -L /private/tmp ]]; then
  work_root=/private/tmp
else
  work_root=/tmp
fi
[[ "${work_root}" == /* ]] || fail "WORK_ROOT must be absolute"
[[ -d "${work_root}" && ! -L "${work_root}" ]] \
  || fail "WORK_ROOT must be an existing non-symlink directory"
work_root="$(cd "${work_root}" && pwd -P)"

case "${work_root}/" in
  "${quantforge_repository}/"*|"${cpp_repository}/"*)
    fail "WORK_ROOT must be outside both source trees"
    ;;
esac

if [[ -n "${QUANTFORGE_CLI:-}" ]]; then
  quantforge_cli="${QUANTFORGE_CLI}"
elif [[ -x "${quantforge_repository}/.venv/bin/quantforge" ]]; then
  quantforge_cli="${quantforge_repository}/.venv/bin/quantforge"
else
  quantforge_cli="$(command -v quantforge 2>/dev/null || true)"
fi
[[ -n "${quantforge_cli}" && -x "${quantforge_cli}" ]] \
  || fail "install QuantForge or set QUANTFORGE_CLI to its executable"

"${quantforge_cli}" --version >/dev/null \
  || fail "the QuantForge CLI is not runnable with its Python 3.12+ environment"

if command -v sha256sum >/dev/null 2>&1; then
  sha256_command=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  sha256_command=(shasum -a 256)
else
  fail "sha256sum or shasum is required"
fi

quantforge_status_before="$(git -C "${quantforge_repository}" status --porcelain=v1 --untracked-files=all)"
cpp_status_before="$(git -C "${cpp_repository}" status --porcelain=v1 --untracked-files=all)"
build_root="$(mktemp -d "${work_root%/}/quantforge-judge-demo.XXXXXX")"
build_directory="${build_root}/cpp-build"

echo "${DEMONSTRATION_LABEL}"
echo "Checking dependencies and protected repository identity: passed"
echo "Building the trusted C++ executable outside the source trees..."

if ! cmake -S "${cpp_repository}" -B "${build_directory}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DQUANT_ENABLE_STRICT_WARNINGS=ON \
  >"${build_root}/cmake-configure.log" 2>&1; then
  tail -n 80 "${build_root}/cmake-configure.log" >&2
  fail "C++ configuration failed; full log: ${build_root}/cmake-configure.log"
fi
if ! cmake --build "${build_directory}" --parallel 2 \
  >"${build_root}/cmake-build.log" 2>&1; then
  tail -n 80 "${build_root}/cmake-build.log" >&2
  fail "C++ build failed; full log: ${build_root}/cmake-build.log"
fi
echo "External C++ build: passed"

cpp_executable="${build_directory}/quant_cli"
[[ -x "${cpp_executable}" && ! -L "${cpp_executable}" ]] \
  || fail "the expected C++ executable was not built"
executable_sha256="$("${sha256_command[@]}" "${cpp_executable}")"
executable_sha256="${executable_sha256%% *}"

PYTHONDONTWRITEBYTECODE=1 "${quantforge_cli}" demo run \
  --repository "${cpp_repository}" \
  --executable "${cpp_executable}" \
  --expected-executable-sha256 "${executable_sha256}" \
  --work-root "${work_root}" \
  --output-dir "${output_directory}"

PYTHONDONTWRITEBYTECODE=1 "${quantforge_cli}" demo verify "${output_directory}"

[[ -f "${output_directory}/tribunal-result.json" ]] \
  || fail "machine report is missing"
[[ -f "${output_directory}/tribunal-report.md" ]] \
  || fail "human report is missing"

quantforge_status_after="$(git -C "${quantforge_repository}" status --porcelain=v1 --untracked-files=all)"
cpp_status_after="$(git -C "${cpp_repository}" status --porcelain=v1 --untracked-files=all)"
[[ "${quantforge_status_after}" == "${quantforge_status_before}" ]] \
  || fail "the QuantForge source tree changed during the demonstration"
[[ "${cpp_status_after}" == "${cpp_status_before}" ]] \
  || fail "the protected C++ source tree changed during the demonstration"

echo "Judge artifact verification: passed"
echo "Machine report: ${output_directory}/tribunal-result.json"
echo "Human report: ${output_directory}/tribunal-report.md"
echo "Temporary external build: ${build_root}"
