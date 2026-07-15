"""QuantForge offline CLI."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from quantforge.audit import AuditLog
from quantforge.domain.models import TribunalCase
from quantforge.serialization.canonical import canonical_json
from quantforge.serialization.export import export_demo
from quantforge.serialization.safe_json import safe_load_json
from quantforge.workflow.demo import run_demo


def _load_case(path: Path) -> TribunalCase:
    value = safe_load_json(path)
    return TribunalCase.model_validate_json(canonical_json(value))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quantforge", description="Offline governed tribunal core"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    case = commands.add_parser("case")
    case_commands = case.add_subparsers(dest="case_command", required=True)
    demo = case_commands.add_parser("run-demo")
    demo.add_argument(
        "--scenario", choices=("provisional", "fragile", "inconclusive"), required=True
    )
    demo.add_argument("--output-dir", type=Path)
    validate = case_commands.add_parser("validate")
    validate.add_argument("case_file", type=Path)
    validate.add_argument("--audit-file", type=Path, required=True)
    inspect = case_commands.add_parser("inspect")
    inspect.add_argument("case_file", type=Path)
    audit = commands.add_parser("audit")
    audit_commands = audit.add_subparsers(dest="audit_command", required=True)
    verify = audit_commands.add_parser("verify")
    verify.add_argument("audit_file", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "case" and args.case_command == "run-demo":
            result = run_demo(args.scenario)
            eligibility = result.case.verdict_eligibility
            if eligibility is None:
                raise ValueError("demo completed without verdict eligibility")
            output = args.output_dir or Path(f"quantforge-demo-{args.scenario}")
            export_demo(result, output)
            print(
                canonical_json(
                    {
                        "case_id": result.case.case_id,
                        "output_directory": str(output),
                        "scenario": args.scenario,
                        "state": result.case.state.value,
                        "verdict": eligibility.verdict.value,
                    }
                )
            )
            return 0
        if args.command == "case" and args.case_command in {"validate", "inspect"}:
            case = _load_case(args.case_file)
            if args.case_command == "validate":
                log = AuditLog.read_jsonl(args.audit_file)
                if log.replay_case() != case:
                    raise ValueError("case snapshot does not match its complete audit history")
                print(canonical_json({"case_id": case.case_id, "valid": True}))
            else:
                print(
                    canonical_json(
                        {
                            "case_id": case.case_id,
                            "evidence_count": len(case.evidence_ids),
                            "state": case.state.value,
                            "verdict": (
                                case.verdict_eligibility.verdict.value
                                if case.verdict_eligibility
                                else None
                            ),
                        }
                    )
                )
            return 0
        if args.command == "audit" and args.audit_command == "verify":
            log = AuditLog.read_jsonl(args.audit_file)
            print(canonical_json({"events": len(log.events), "valid": True}))
            return 0
    except (OSError, PermissionError, TypeError, ValueError, ValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2
