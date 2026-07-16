from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from scripts import release_candidate

STABLE_BOUNDARY_KEYS = (
    "head",
    "staged_diff",
    "tracked_diff",
    "tracked_tree",
    "untracked_inventory",
    "v1.0.0_annotated_tag_object",
    "v1.0.0_peeled_target",
)


def git(repo: Path, *args: str) -> None:
    release_candidate._run(["git", *args], repo)


def protected_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, dict[str, Any]]:
    root = tmp_path / "quantforge-ai"
    engine = tmp_path / "cpp-event-driven-backtester"
    root.mkdir()
    engine.mkdir()
    git(engine, "init", "-b", "main")
    git(engine, "config", "user.name", "Boundary Test")
    git(engine, "config", "user.email", "boundary@example.invalid")
    git(engine, "config", "commit.gpgsign", "false")
    git(engine, "config", "tag.gpgsign", "false")
    (engine / ".gitignore").write_text(
        "build/\nresults/\ntest_results/\nforbidden/\n__pycache__/\n",
        encoding="utf-8",
    )
    (engine / "README.md").write_text("protected source\n", encoding="utf-8")
    git(engine, "add", ".gitignore", "README.md")
    git(engine, "commit", "-m", "Protected baseline")
    git(engine, "tag", "-a", "v1.0.0", "-m", "Protected v1.0.0")

    clean = release_candidate.engine_snapshot(engine)
    expected = {key: clean[key] for key in STABLE_BOUNDARY_KEYS}
    monkeypatch.setattr(release_candidate, "expected_engine_boundary", lambda _root: expected)
    return root, engine, expected


def test_clean_protected_engine_boundary_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _engine, _expected = protected_engine(tmp_path, monkeypatch)
    observed = release_candidate.verify_engine_boundary(root)
    assert observed["verification"] == "live classified read-only comparison"


def test_tracked_modification_still_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    (engine / "README.md").write_text("changed source\n", encoding="utf-8")
    with pytest.raises(release_candidate.ReleaseValidationError, match="tracked_diff"):
        release_candidate.verify_engine_boundary(root)


def test_staged_modification_still_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    (engine / "README.md").write_text("staged source\n", encoding="utf-8")
    git(engine, "add", "README.md")
    with pytest.raises(release_candidate.ReleaseValidationError, match="staged_diff"):
        release_candidate.verify_engine_boundary(root)


def test_untracked_nonignored_file_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    (engine / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(release_candidate.ReleaseValidationError, match="untracked_inventory"):
        release_candidate.verify_engine_boundary(root)


def test_head_change_still_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    (engine / "tracked.txt").write_text("new commit\n", encoding="utf-8")
    git(engine, "add", "tracked.txt")
    git(engine, "commit", "-m", "Unauthorized descendant")
    with pytest.raises(release_candidate.ReleaseValidationError, match="head"):
        release_candidate.verify_engine_boundary(root)


def test_annotated_tag_change_still_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    git(engine, "tag", "-f", "-a", "v1.0.0", "-m", "Replacement object")
    with pytest.raises(
        release_candidate.ReleaseValidationError, match=r"v1\.0\.0_annotated_tag_object"
    ):
        release_candidate.verify_engine_boundary(root)


def test_forbidden_ignored_path_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    forbidden = engine / "forbidden" / "payload.bin"
    forbidden.parent.mkdir()
    forbidden.write_bytes(b"not an approved output")
    with pytest.raises(release_candidate.ReleaseValidationError, match="unapproved ignored path"):
        release_candidate.verify_engine_boundary(root)


def test_secret_in_allowed_ignored_path_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    secret = engine / "build" / "cache.txt"
    secret.parent.mkdir()
    secret.write_text("AKIA" + "A" * 16, encoding="utf-8")
    with pytest.raises(release_candidate.ReleaseValidationError, match="secret indicator"):
        release_candidate.verify_engine_boundary(root)


def test_allowed_build_result_and_cache_drift_is_reported_not_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    build = engine / "build" / "CMakeFiles" / "cache.txt"
    result = engine / "results" / "demo" / "summary.json"
    bytecode = engine / "scripts" / "__pycache__" / "validator.pyc"
    build.parent.mkdir(parents=True)
    result.parent.mkdir(parents=True)
    bytecode.parent.mkdir(parents=True)
    build.write_text("generated\n", encoding="utf-8")
    result.write_text("{}\n", encoding="utf-8")
    bytecode.write_bytes(b"generated bytecode fixture")

    first = release_candidate.verify_engine_boundary(root)
    assert first["ignored_inventory_count"] == 3
    assert first["ignored_forbidden_count"] == 0
    assert first["ignored_inventory_status"] == "reported_not_frozen"

    (engine / "results" / "demo" / "details.csv").write_text("value\n1\n", encoding="utf-8")
    second = release_candidate.verify_engine_boundary(root)
    assert second["ignored_inventory_count"] == 4
    assert second["ignored_inventory_sha256"] != first["ignored_inventory_sha256"]


def test_symlink_and_traversal_attacks_remain_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    with pytest.raises(release_candidate.ReleaseValidationError, match="traversal"):
        release_candidate._ignored_path_parts(b"build/../src/hidden.cpp")

    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    link = engine / "build" / "outside-link"
    link.parent.mkdir()
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(release_candidate.ReleaseValidationError, match="contains a symlink"):
        release_candidate.verify_engine_boundary(root)


@pytest.mark.parametrize(
    ("relative_path", "message"),
    [
        ("build/credentials.txt", "sensitive name"),
        ("build/hidden.cpp", "unapproved source"),
        ("results/.github/workflows/hidden.yml", "sensitive name"),
    ],
)
def test_allowlisted_parent_cannot_hide_sensitive_or_source_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    message: str,
) -> None:
    root, engine, _expected = protected_engine(tmp_path, monkeypatch)
    hidden = engine / relative_path
    hidden.parent.mkdir(parents=True, exist_ok=True)
    hidden.write_text("hidden\n", encoding="utf-8")
    with pytest.raises(release_candidate.ReleaseValidationError, match=message):
        release_candidate.verify_engine_boundary(root)
