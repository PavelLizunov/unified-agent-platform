#!/usr/bin/env python3
"""Tests for the kustomization-orphan check in validate_iac.py.

Run with: python tests/static/test_validate_iac_orphans.py
Exit 0 on pass, 1 on failure. No external dependencies.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import validate_iac


def make_file(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def kust(resources_yaml: str = "") -> str:
    base = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
    return base + resources_yaml


def test_unreferenced_file_is_flagged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        d = root / "clusters" / "prod" / "infra"
        make_file(d / "kustomization.yaml", kust("resources:\n  - foo.yaml\n"))
        make_file(d / "foo.yaml", "")
        make_file(d / "bar.yaml", "")  # not in resources → should be flagged
        orphans = validate_iac._find_kustomization_orphans(root)
        assert "clusters/prod/infra/bar.yaml" in orphans, f"bar.yaml should be orphan, got: {orphans}"
        assert "clusters/prod/infra/foo.yaml" not in orphans, f"foo.yaml should not be orphan"


def test_fully_referenced_dir_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        d = root / "clusters" / "prod" / "flux-system"
        make_file(d / "kustomization.yaml", kust("resources:\n  - a.yaml\n  - b.sops.yaml\n"))
        make_file(d / "a.yaml", "")
        make_file(d / "b.sops.yaml", "")
        orphans = validate_iac._find_kustomization_orphans(root)
        assert not orphans, f"Expected no orphans, got: {orphans}"


def test_no_kustomization_flags_all_yaml() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        d = root / "clusters" / "staging"
        make_file(d / "app.yaml", "")
        make_file(d / "config.sops.yaml", "")
        orphans = validate_iac._find_kustomization_orphans(root)
        assert "clusters/staging/app.yaml" in orphans, f"app.yaml should be orphan"
        assert "clusters/staging/config.sops.yaml" in orphans, f"config.sops.yaml should be orphan"


def test_allowlist_suppresses_known_exception() -> None:
    allowlist_entry = next(iter(validate_iac.KUSTOMIZATION_ORPHAN_ALLOWLIST))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / allowlist_entry
        make_file(target, "")
        make_file(target.parent / "kustomization.yaml", kust("resources: []\n"))
        orphans = validate_iac._find_kustomization_orphans(root)
        assert allowlist_entry not in orphans, f"Allowlisted {allowlist_entry} should not be flagged"


def test_cross_dir_reference_resolves() -> None:
    # Documents intent (the OLD basename code also passed this one); the actual regression guard for
    # the basename bug is test_duplicate_basename_local_not_masked below.
    # A kustomization referencing ../shared/foo.yaml must mark that file referenced from its real
    # location — not leave it looking like an orphan in clusters/shared (which has no kustomization).
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_file(root / "clusters" / "prod" / "kustomization.yaml",
                  kust("resources:\n  - ../shared/foo.yaml\n"))
        make_file(root / "clusters" / "shared" / "foo.yaml", "")
        orphans = validate_iac._find_kustomization_orphans(root)
        assert "clusters/shared/foo.yaml" not in orphans, \
            f"../shared/foo.yaml is referenced cross-dir, should not be orphan; got: {orphans}"


def test_duplicate_basename_local_not_masked() -> None:
    # The basename bug: clusters/prod references ../shared/app.yaml while an UNREFERENCED local
    # clusters/prod/app.yaml exists. A basename compare clears the local app.yaml (same name); the
    # path-resolving check must still flag it, and must NOT flag the referenced ../shared/app.yaml.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_file(root / "clusters" / "prod" / "kustomization.yaml",
                  kust("resources:\n  - ../shared/app.yaml\n"))
        make_file(root / "clusters" / "shared" / "app.yaml", "")
        make_file(root / "clusters" / "prod" / "app.yaml", "")  # local, unreferenced → orphan
        orphans = validate_iac._find_kustomization_orphans(root)
        assert "clusters/prod/app.yaml" in orphans, \
            f"unreferenced local app.yaml must be flagged despite the ../shared/app.yaml basename; got: {orphans}"
        assert "clusters/shared/app.yaml" not in orphans, \
            f"referenced ../shared/app.yaml should not be orphan; got: {orphans}"


if __name__ == "__main__":
    tests = [
        test_unreferenced_file_is_flagged,
        test_fully_referenced_dir_passes,
        test_no_kustomization_flags_all_yaml,
        test_allowlist_suppresses_known_exception,
        test_cross_dir_reference_resolves,
        test_duplicate_basename_local_not_masked,
    ]
    passed = failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {test.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"  ERROR {test.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
