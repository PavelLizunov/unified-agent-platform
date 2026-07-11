#!/usr/bin/env python3
from pathlib import Path
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[2]

configmap = yaml.safe_load(
    (ROOT / "clusters/prod/infra/hermes-agent-config.yaml").read_text(encoding="utf-8")
)
managed = yaml.safe_load(configmap["data"]["managed-config"])
model = managed["model"]
user_profile = configmap["data"]["user-profile"]
agents = configmap["data"]["agents-md"]
profile_migration = configmap["data"]["profile-migrate.py"]

assert model.get("provider"), "managed brain must pin model.provider"
assert model.get("default"), "Hermes v0.18 managed brain must pin model.default"
assert "model" not in model and "name" not in model, "legacy model-id aliases must not be used"

deployment = (ROOT / "clusters/prod/infra/hermes-agent.yaml").read_text(encoding="utf-8")
assert '("provider","default")' in deployment, "bootstrap guard must require provider + default"
assert "мозг = локальный qwen-35b" not in user_profile
assert "лимиты Claude/Codex кончились" not in user_profile
assert "brain = local qwen-35b" not in agents.lower()
assert "codex_app_server" in agents
assert "gpt-5.5" not in agents, "model id must have one owner: managed config"
assert "cp /config/agents-md /opt/data/.codex/AGENTS.md" in deployment
assert "[ -f /opt/data/.codex/AGENTS.md ] ||" not in deployment
assert "/config/profile-migrate.py" in deployment
assert "мозг = локальный qwen-35b" in profile_migration
assert "КОДЕР = ornith-9b" in profile_migration

old_profile = """# owner
- Инфраструктура: k3s (Flux GitOps + SOPS); мозг = локальный qwen-35b (llama.cpp на десктопе
  через ops-1 роутер; лимиты Claude/Codex кончились), fallback = ornith-9b (мак, always-on).
      **КОДЕР = ornith-9b. ТЫ САМ РАБОЧИЙ КОД НЕ ПИШЕШЬ.** stale details
      (`claude -p` / `codex` НЕ используй — лимиты кончились.)
owner-enriched-sentinel
"""
with tempfile.TemporaryDirectory() as tmp:
    profile = Path(tmp) / "USER.md"
    profile.write_text(old_profile, encoding="utf-8")
    migration = profile_migration.replace("/opt/data/memories/USER.md", str(profile))
    exec(compile(migration, "profile-migrate.py", "exec"))
    once = profile.read_text(encoding="utf-8")
    exec(compile(migration, "profile-migrate.py", "exec"))
    assert profile.read_text(encoding="utf-8") == once, "profile migration must be idempotent"
    assert "owner-enriched-sentinel" in once, "profile migration must preserve enriched memory"
    assert "лимиты Claude/Codex кончились" not in once
    assert "claude_code" in once

print("hermes-managed-model-ok")
