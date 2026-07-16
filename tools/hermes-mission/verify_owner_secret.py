#!/usr/bin/env python3
"""Validate one decrypted owner-capability Secret without printing its value."""

from __future__ import annotations

import base64
import binascii
import json
import sys


def validate(document: object) -> None:
    if not isinstance(document, dict) or set(document) != {
        "apiVersion", "data", "kind", "metadata"
    }:
        raise ValueError("owner Secret has an invalid top-level schema")
    if document["apiVersion"] != "v1" or document["kind"] != "Secret":
        raise ValueError("owner Secret is not a Kubernetes v1 Secret")
    if document["metadata"] != {
        "name": "hermes-agent-owner", "namespace": "uap-system"
    }:
        raise ValueError("owner Secret identity is invalid")
    data = document["data"]
    if not isinstance(data, dict) or set(data) != {"owner-key"}:
        raise ValueError("owner Secret data contract is invalid")
    encoded = data["owner-key"]
    if not isinstance(encoded, str):
        raise ValueError("owner Secret value is not base64 text")
    try:
        value = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("owner Secret value is not valid base64") from error
    if not 32 <= len(value) <= 512 or any(byte in value for byte in b"\x00\r\n"):
        raise ValueError("owner Secret value is invalid")


def main() -> int:
    try:
        validate(json.load(sys.stdin))
        print("hermes-owner-secret-decrypted-ok")
        return 0
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"hermes-owner-secret-error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
