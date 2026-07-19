"""QuantForge offline governed CLI."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from quantforge import __version__
from quantforge.audit import AuditLog
from quantforge.demo import run_governed_tribunal_demo, verify_governed_tribunal_demo
from quantforge.demo.tribunal import terminal_summary
from quantforge.domain.models import TribunalCase, WorkflowState
from quantforge.engine import LocalCppV1Adapter
from quantforge.evidence.bundle import (
    GENESIS_BUNDLE_HASH,
    EvidenceAdmissionContext,
    EvidenceBundle,
    amendment_chain_hash,
    verify_evidence_bundle,
)
from quantforge.serialization.canonical import canonical_json, canonical_sha256
from quantforge.serialization.export import export_demo
from quantforge.serialization.safe_json import safe_load_json, safe_write_json
from quantforge.storage import (
    SQLiteCaseStore,
    admit_engine_evidence,
    execute_and_admit_engine_evidence,
    export_durable_case,
    persist_audited_case,
    verify_case_package,
)
from quantforge.workflow.demo import run_demo


def _load_case(path: Path) -> TribunalCase:
    value = safe_load_json(path)
    return TribunalCase.model_validate_json(canonical_json(value))


def _load_bundle(path: Path) -> EvidenceBundle:
    value = safe_load_json(path)
    return EvidenceBundle.model_validate_json(canonical_json(value))


def _add_engine_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--expected-executable-sha256", required=True)
    parser.add_argument("--work-root", type=Path, required=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quantforge", description="Offline governed tribunal core"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
    inspect_case = case_commands.add_parser("inspect")
    inspect_case.add_argument("case_file", type=Path)
    initialize_fixture = case_commands.add_parser("initialize-fixture")
    initialize_fixture.add_argument("--store", type=Path, required=True)
    initialize_fixture.add_argument(
        "--scenario", choices=("provisional", "fragile", "inconclusive"), required=True
    )
    persist_demo = case_commands.add_parser("persist-demo")
    persist_demo.add_argument("--store", type=Path, required=True)
    persist_demo.add_argument(
        "--scenario", choices=("provisional", "fragile", "inconclusive"), required=True
    )
    reconstruct = case_commands.add_parser("reconstruct")
    reconstruct.add_argument("--store", type=Path, required=True)
    reconstruct.add_argument("--case-id", required=True)
    reconstruct.add_argument("--require-complete", action="store_true")
    export = case_commands.add_parser("export")
    export.add_argument("--store", type=Path, required=True)
    export.add_argument("--case-id", required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    verify_package = case_commands.add_parser("verify-package")
    verify_package.add_argument("package_dir", type=Path)

    audit = commands.add_parser("audit")
    audit_commands = audit.add_subparsers(dest="audit_command", required=True)
    verify = audit_commands.add_parser("verify")
    verify.add_argument("audit_file", type=Path)

    store = commands.add_parser("store")
    store_commands = store.add_subparsers(dest="store_command", required=True)
    for name in ("init", "inspect", "validate"):
        store_command = store_commands.add_parser(name)
        store_command.add_argument("store_file", type=Path)
    migrate = store_commands.add_parser("migrate")
    migrate.add_argument("store_file", type=Path)
    migrate.add_argument("--dry-run", action="store_true")

    engine = commands.add_parser("engine")
    engine_commands = engine.add_subparsers(dest="engine_command", required=True)
    verify_release = engine_commands.add_parser("verify-release")
    _add_engine_arguments(verify_release)
    execute = engine_commands.add_parser("execute-fixture")
    _add_engine_arguments(execute)
    execute.add_argument("--store", type=Path, required=True)
    execute.add_argument("--case-id", required=True)
    execute.add_argument("--bundle-output", type=Path, required=True)
    execute_and_admit = engine_commands.add_parser("execute-and-admit-fixture")
    _add_engine_arguments(execute_and_admit)
    execute_and_admit.add_argument("--store", type=Path, required=True)
    execute_and_admit.add_argument("--case-id", required=True)
    execute_and_admit.add_argument("--evidence-id", required=True)
    execute_and_admit.add_argument("--bundle-output", type=Path, required=True)

    evidence = commands.add_parser("evidence")
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    for name in ("verify", "admit"):
        evidence_command = evidence_commands.add_parser(name)
        _add_engine_arguments(evidence_command)
        evidence_command.add_argument("--store", type=Path, required=True)
        evidence_command.add_argument("--case-id", required=True)
        evidence_command.add_argument("--bundle-file", type=Path, required=True)
        evidence_command.add_argument("--artifact-root", type=Path, required=True)
        if name == "admit":
            evidence_command.add_argument("--evidence-id", required=True)

    governed_demo = commands.add_parser("demo")
    governed_demo_commands = governed_demo.add_subparsers(dest="demo_command", required=True)
    run_governed_demo = governed_demo_commands.add_parser("run")
    _add_engine_arguments(run_governed_demo)
    run_governed_demo.add_argument("--output-dir", type=Path, required=True)
    verify_governed_demo = governed_demo_commands.add_parser("verify")
    verify_governed_demo.add_argument("artifact_dir", type=Path)
    return parser


def _adapter(args: argparse.Namespace) -> LocalCppV1Adapter:
    return LocalCppV1Adapter(
        repository=args.repository,
        executable=args.executable,
        expected_executable_sha256=args.expected_executable_sha256,
        work_root=args.work_root,
    )


def _admission_context(
    args: argparse.Namespace,
    store: SQLiteCaseStore,
) -> tuple[EvidenceAdmissionContext, LocalCppV1Adapter]:
    durable = store.reconstruct(args.case_id, require_complete=False)
    case = durable.case
    if case.constitution is None:
        raise ValueError("evidence verification requires a locked constitution")
    adapter = _adapter(args)
    approved = adapter.approved_fixture_identity()
    context = EvidenceAdmissionContext(
        case_id=case.case_id,
        workflow_revision=durable.revision,
        constitution_id=case.constitution.constitution_id,
        constitution_hash=case.constitution.constitution_hash,
        amendment_chain_hash=amendment_chain_hash(case.amendments),
        engine=approved.engine,
        configuration_sha256=approved.configuration_sha256,
        input_artifacts=approved.input_semantics,
        input_artifact_observations=approved.input_observations,
        previous_bundle_hash=GENESIS_BUNDLE_HASH,
        now=datetime.now(UTC),
        finalized=case.state is WorkflowState.CHAIR_EXPLANATION,
    )
    return context, adapter


def _handle_store(args: argparse.Namespace) -> int:
    store = SQLiteCaseStore(args.store_file)
    if args.store_command == "init":
        result = store.initialize()
    elif args.store_command == "migrate":
        result = store.migrate(dry_run=args.dry_run)
    elif args.store_command == "validate":
        result = store.verify()
    else:
        result = store.inspect()
    print(canonical_json(result.__dict__))
    return 0


def _handle_case(args: argparse.Namespace) -> int:
    if args.case_command == "run-demo":
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
    if args.case_command in {"validate", "inspect"}:
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
    if args.case_command == "verify-package":
        print(canonical_json(verify_case_package(args.package_dir)))
        return 0
    store = SQLiteCaseStore(args.store)
    if args.case_command in {"initialize-fixture", "persist-demo"}:
        result = run_demo(args.scenario)
        if args.case_command == "initialize-fixture":
            audit = AuditLog(result.audit_log.events[:5])
            durable = persist_audited_case(store, audit)
        else:
            durable = persist_audited_case(store, result.audit_log, claim_graph=result.claim_graph)
        print(
            canonical_json(
                {
                    "case_id": durable.case.case_id,
                    "revision": durable.revision,
                    "semantic_hash": durable.semantic_hash,
                    "state": durable.case.state.value,
                }
            )
        )
        return 0
    if args.case_command == "reconstruct":
        durable = store.reconstruct(args.case_id, require_complete=args.require_complete)
        print(
            canonical_json(
                {
                    "audit_head_hash": durable.audit_head_hash,
                    "case_id": durable.case.case_id,
                    "evidence_count": len(durable.case.evidence_ids),
                    "revision": durable.revision,
                    "semantic_hash": durable.semantic_hash,
                    "state": durable.case.state.value,
                }
            )
        )
        return 0
    exported = export_durable_case(store, args.case_id, args.output_dir)
    print(
        canonical_json(
            {
                "artifact_hashes": exported.artifact_hashes,
                "export_id": exported.export_id,
                "manifest_hash": exported.manifest_hash,
                "output_directory": str(exported.output_directory),
            }
        )
    )
    return 0


def _handle_engine(args: argparse.Namespace) -> int:
    adapter = _adapter(args)
    if args.engine_command == "verify-release":
        identity = adapter.verify_release_identity()
        print(
            canonical_json(
                {
                    "allowed_commands": adapter.allowed_commands,
                    "engine": identity,
                    "valid": True,
                }
            )
        )
        return 0
    if args.engine_command == "execute-and-admit-fixture":
        store = SQLiteCaseStore(args.store)
        result = execute_and_admit_engine_evidence(
            store,
            adapter,
            case_id=args.case_id,
            evidence_id=args.evidence_id,
        )
        safe_write_json(args.bundle_output, result.bundle)
        print(
            canonical_json(
                {
                    "bundle_file": str(args.bundle_output),
                    "bundle_hash": result.bundle.bundle_hash,
                    "case_id": result.durable_case.case.case_id,
                    "evidence_id": result.evidence.evidence_id,
                    "revision": result.durable_case.revision,
                    "state": result.durable_case.case.state.value,
                }
            )
        )
        return 0
    store = SQLiteCaseStore(args.store)
    durable = store.reconstruct(args.case_id, require_complete=False)
    case = durable.case
    if case.state is not WorkflowState.CONSTITUTION_LOCKED or case.constitution is None:
        raise ValueError("approved fixture execution requires a locked constitution")
    run = adapter.execute_approved_fixture()
    admitted_at = datetime.now(UTC)
    bundle_identity = {
        "case": case.case_id,
        "configuration": run.configuration_sha256,
        "revision": durable.revision,
    }
    bundle_id = f"bundle_{canonical_sha256(bundle_identity)[:32]}"
    bundle = run.evidence_bundle(
        bundle_id=bundle_id,
        case_id=case.case_id,
        workflow_revision=durable.revision,
        constitution_id=case.constitution.constitution_id,
        constitution_hash=case.constitution.constitution_hash,
        amendment_chain_hash=amendment_chain_hash(case.amendments),
        previous_bundle_hash=GENESIS_BUNDLE_HASH,
        admitted_at=admitted_at,
    )
    safe_write_json(args.bundle_output, bundle)
    print(
        canonical_json(
            {
                "artifact_root": str(run.output_root),
                "bundle_file": str(args.bundle_output),
                "bundle_hash": bundle.bundle_hash,
                "case_id": case.case_id,
                "output_artifacts": len(bundle.semantic.output_artifacts),
            }
        )
    )
    return 0


def _handle_evidence(args: argparse.Namespace) -> int:
    store = SQLiteCaseStore(args.store)
    bundle = _load_bundle(args.bundle_file)
    context, _ = _admission_context(args, store)
    if args.evidence_command == "verify":
        verify_evidence_bundle(bundle, context, args.artifact_root)
        print(
            canonical_json(
                {"bundle_hash": bundle.bundle_hash, "case_id": context.case_id, "valid": True}
            )
        )
        return 0
    result = admit_engine_evidence(
        store,
        bundle,
        context,
        args.artifact_root,
        evidence_id=args.evidence_id,
    )
    print(
        canonical_json(
            {
                "bundle_hash": bundle.bundle_hash,
                "case_id": result.durable_case.case.case_id,
                "evidence_id": result.evidence.evidence_id,
                "revision": result.durable_case.revision,
                "state": result.durable_case.case.state.value,
            }
        )
    )
    return 0


def _handle_demo(args: argparse.Namespace) -> int:
    if args.demo_command == "verify":
        print(canonical_json(verify_governed_tribunal_demo(args.artifact_dir)))
        return 0
    result = run_governed_tribunal_demo(_adapter(args), args.output_dir)
    print(terminal_summary(result))
    print(f"Artifacts: {args.output_dir.absolute()}")
    print(f"Independent verification: quantforge demo verify {args.output_dir.absolute()}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "store":
            return _handle_store(args)
        if args.command == "case":
            return _handle_case(args)
        if args.command == "engine":
            return _handle_engine(args)
        if args.command == "evidence":
            return _handle_evidence(args)
        if args.command == "demo":
            return _handle_demo(args)
        if args.command == "audit" and args.audit_command == "verify":
            log = AuditLog.read_jsonl(args.audit_file)
            print(canonical_json({"events": len(log.events), "valid": True}))
            return 0
    except (
        OSError,
        PermissionError,
        sqlite3.Error,
        TypeError,
        ValueError,
        ValidationError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2
