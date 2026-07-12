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
guardrails = managed["tool_loop_guardrails"]
user_profile = configmap["data"]["user-profile"]
agents = configmap["data"]["agents-md"]
profile_migration = configmap["data"]["profile-migrate.py"]

assert model.get("provider"), "managed brain must pin model.provider"
assert model.get("default"), "Hermes v0.18 managed brain must pin model.default"
assert "model" not in model and "name" not in model, "legacy model-id aliases must not be used"
assert guardrails["warnings_enabled"] is True
assert guardrails["hard_stop_enabled"] is True
assert guardrails["warn_after"] == {
    "exact_failure": 2,
    "same_tool_failure": 3,
    "idempotent_no_progress": 2,
}
assert guardrails["hard_stop_after"] == {
    "exact_failure": 5,
    "same_tool_failure": 8,
    "idempotent_no_progress": 5,
}

deployment = (ROOT / "clusters/prod/infra/hermes-agent.yaml").read_text(encoding="utf-8")
assert '("provider","default")' in deployment, "bootstrap guard must require provider + default"
assert "мозг = локальный qwen-35b" not in user_profile
assert "лимиты Claude/Codex кончились" not in user_profile
assert "brain = local qwen-35b" not in agents.lower()
assert "qwen-35b" in agents and "do not probe or call it" in agents
assert "approval naming the specific agent and action" in agents
assert "codex_app_server" in agents
assert "gpt-5." not in agents, "model id must have one owner: managed config"
assert "smallest working change" in agents
assert "do not repeat standing safety boundaries" in agents
assert "mm4.local" in agents and "100.116.97.112" in agents
assert 'build1 "ssh slovn@100.116.97.112' in agents
assert "cp /config/agents-md /opt/data/.codex/AGENTS.md" in deployment
assert "[ -f /opt/data/.codex/AGENTS.md ] ||" not in deployment
assert "/config/profile-migrate.py" in deployment
assert "DietrichGebert/ponytail" not in deployment
assert "/plugins/ponytail" not in deployment
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
    migration = profile_migration.replace(
        "/opt/data/memories/USER.md", str(profile).replace("\\", "\\\\")
    )
    exec(compile(migration, "profile-migrate.py", "exec"))
    once = profile.read_text(encoding="utf-8")
    exec(compile(migration, "profile-migrate.py", "exec"))
    assert profile.read_text(encoding="utf-8") == once, "profile migration must be idempotent"
    assert "owner-enriched-sentinel" in once, "profile migration must preserve enriched memory"
    assert "лимиты Claude/Codex кончились" not in once
    assert "claude_code" in once

live_profile = """# owner
## АКТУАЛЬНО 2026-07 (важнее любых старых строк выше)
- Мозг = ЛОКАЛЬНЫЙ qwen-35b (НЕ Codex — платные лимиты кончились). Всё общение/reasoning/FC — им.
- КОДЕР = ornith-9b. Генерацию кода делегируй: `/opt/data/.local/bin/ornith "<что написать + контекст>"`
  -> вернёт готовый код; примени и протестируй сам. claude -p / codex НЕ используй (лимиты).
- ⚠️ ТЯЖЁЛЫЙ COMPUTE — ТОЛЬКО на build-1.
owner-live-sentinel
"""
with tempfile.TemporaryDirectory() as tmp:
    profile = Path(tmp) / "USER.md"
    profile.write_text(live_profile, encoding="utf-8")
    migration = profile_migration.replace(
        "/opt/data/memories/USER.md", str(profile).replace("\\", "\\\\")
    )
    exec(compile(migration, "profile-migrate.py", "exec"))
    once = profile.read_text(encoding="utf-8")
    exec(compile(migration, "profile-migrate.py", "exec"))
    assert profile.read_text(encoding="utf-8") == once, "live profile migration must be idempotent"
    assert "owner-live-sentinel" in once
    assert "Мозг = ЛОКАЛЬНЫЙ qwen-35b" not in once
    assert "КОДЕР = ornith-9b" not in once
    assert "Runtime/model определяются managed config" in once
    assert "claude_code" in once
    assert "Qwen на рабочей" in once and "конкретного агента и действия" in once

print("hermes-managed-model-ok")
