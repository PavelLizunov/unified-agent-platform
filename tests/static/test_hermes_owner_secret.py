#!/usr/bin/env python3
from __future__ import annotations

import base64
import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "hermes-mission" / "verify_owner_secret.py"
SPEC = importlib.util.spec_from_file_location("verify_owner_secret", TOOL)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def document(value: bytes) -> dict:
    return {
        "apiVersion": "v1",
        "data": {"owner-key": base64.b64encode(value).decode("ascii")},
        "kind": "Secret",
        "metadata": {"name": "hermes-agent-owner", "namespace": "uap-system"},
    }


def main() -> None:
    verifier.validate(document(b"owner-capability-that-is-long-enough-123456"))
    for invalid in (
        {**document(b"valid-owner-capability-that-is-long-enough"), "kind": "ConfigMap"},
        document(b"short"),
        document(b"owner-capability-that-contains-a-newline-123\n"),
    ):
        try:
            verifier.validate(invalid)
            raise AssertionError("invalid owner Secret was accepted")
        except ValueError:
            pass
    print("hermes owner Secret checks passed")


if __name__ == "__main__":
    main()
