#!/usr/bin/env python3
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]

configmap = yaml.safe_load(
    (ROOT / "clusters/prod/infra/hermes-agent-config.yaml").read_text(encoding="utf-8")
)
managed = yaml.safe_load(configmap["data"]["managed-config"])
model = managed["model"]

assert model.get("provider"), "managed brain must pin model.provider"
assert model.get("default"), "Hermes v0.18 managed brain must pin model.default"
assert "model" not in model and "name" not in model, "legacy model-id aliases must not be used"

deployment = (ROOT / "clusters/prod/infra/hermes-agent.yaml").read_text(encoding="utf-8")
assert '("provider","default")' in deployment, "bootstrap guard must require provider + default"

print("hermes-managed-model-ok")
