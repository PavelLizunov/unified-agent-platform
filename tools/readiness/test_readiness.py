#!/usr/bin/env python3
import importlib.util
from pathlib import Path


MODULE = Path(__file__).with_name("readiness.py")
spec = importlib.util.spec_from_file_location("readiness", MODULE)
readiness = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(readiness)

assert readiness.model_verdict(
    {"model": {"provider": "openai-codex", "default": "gpt-5.5"}},
    {"model": {"default": "stale"}},
    "gpt-5.5",
)[0]
assert not readiness.model_verdict(
    {"model": {"provider": "openai-codex", "model": "gpt-5.5"}},
    {"model": {"default": "gpt-5.6-luna"}},
    "gpt-5.6-luna",
)[0]
assert "value" not in readiness.safe("Authorization: value")
assert readiness.contract_verdict({"AGENTS.md", "Cargo.toml", ".github/workflows/ci.yml"})[0]
assert not readiness.contract_verdict({"README.md", "Cargo.toml", ".github/workflows/ci.yml"})[0]

print("readiness-test-ok")
