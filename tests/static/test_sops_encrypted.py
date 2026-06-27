#!/usr/bin/env python3
"""Regression test for validate_iac's SOPS structural check.

It must flag a PLAINTEXT secret value in a .sops.yaml (the hole the gitleaks whole-file path
allowlist leaves open) and pass a properly ENC[...]-encrypted one. Runnable directly:
    python tests/static/test_sops_encrypted.py   # exit 0 on pass
The secret-shaped string is built at runtime so this test file contains no literal token.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_iac import _sops_unencrypted_values  # noqa: E402


def _write(text: str) -> Path:
    path = Path(tempfile.mkdtemp()) / "x.sops.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def main() -> None:
    failures: list[str] = []

    # built at runtime so the source has no literal secret-shaped string
    plaintext = "sk-" + "ant-" + "oat01-" + "Z" * 40
    bad = _sops_unencrypted_values(_write(
        f"apiVersion: v1\nkind: Secret\nstringData:\n  token: {plaintext}\n"
    ))
    if bad != ["stringData.token"]:
        failures.append(f"plaintext stringData not flagged: {bad}")

    bad = _sops_unencrypted_values(_write(
        "kind: Secret\ndata:\n  k: " + ("ABCD" * 12) + "\n"
    ))
    if "data.k" not in bad:
        failures.append(f"plaintext data not flagged: {bad}")

    # a token must not hide in a nested dict/list under data/stringData (recursion)
    bad = _sops_unencrypted_values(_write(
        "kind: Secret\ndata:\n  outer:\n    inner: " + ("WXYZ" * 12) + "\n"
    ))
    if "data.outer.inner" not in bad:
        failures.append(f"nested plaintext not flagged: {bad}")

    ok = _sops_unencrypted_values(_write(
        "kind: Secret\ndata:\n  token: ENC[AES256_GCM,data:ab,iv:cd,tag:ef,type:str]\n"
        '  optional: ""\n'
    ))
    if ok:
        failures.append(f"encrypted/empty value wrongly flagged: {ok}")

    ok = _sops_unencrypted_values(_write("kind: ConfigMap\nmetadata:\n  name: x\n"))
    if ok:
        failures.append(f"non-secret doc wrongly flagged: {ok}")

    names = [
        "test_plaintext_stringData_flagged",
        "test_plaintext_data_flagged",
        "test_nested_dict_recursed",
        "test_encrypted_and_empty_pass",
        "test_non_secret_doc_passes",
    ]
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"\n{len(failures)}/{len(names)} failed")
        raise SystemExit(1)
    for n in names:
        print(f"  PASS  {n}")
    print(f"\n{len(names)} passed, 0 failed")


if __name__ == "__main__":
    main()
