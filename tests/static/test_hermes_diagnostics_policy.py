#!/usr/bin/env python3
"""Static gate: read-only diagnostics policy in the managed Hermes prompt."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
cm = yaml.safe_load(
    (ROOT / "clusters/prod/infra/hermes-agent-config.yaml").read_text(encoding="utf-8")
)
profile = cm["data"]["user-profile"]
agents = cm["data"]["agents-md"]

# Automatic read-only diagnostics + evidence
assert "READ-ONLY ДИАГНОСТИКА" in profile
assert "АВТОМАТИЧЕСКИ, БЕЗ ПОДТВЕРЖДЕНИЯ" in profile
assert "Резюмируй доказательства" in profile
assert "Read-only diagnostics are automatic" in agents
assert "summarize evidence" in agents

# Exact three owner-gate categories
for token in ("недоступные credentials/новые полномочия",
              "неоднозначный продуктовый",
              "destructive/write действие"):
    assert token in profile, token
for token in ("unavailable credentials or new authority",
              "ambiguous product intent",
              "destructive/write action"):
    assert token in agents, token

# Ordinary configured subscription/API spend needs no confirmation
assert "Обычные расходы уже настроенных" in profile
assert "subscription/API" in profile
assert "Ordinary already-configured subscription/API spend" in agents

# Spending is NOT in the external-side-effects approval list
g2_block = profile[profile.index("ПОБОЧКИ НАРУЖУ"):profile.index("КОНТЕКСТ-ГИГИЕНА")]
assert "трата денег" not in g2_block, "spending must not require approval"

# Destructive / external-write boundary preserved
assert "РАЗРУШИТЕЛЬНОЕ" in profile and "без явного согласования" in profile
assert "ПОБОЧКИ НАРУЖУ" in profile
assert "только с ЯВНОГО подтверждения владельца" in profile

# Migration wiring: profile-migrate.py must propagate guardrail changes to live USER.md
migration = cm["data"]["profile-migrate.py"]
assert "трата денег" in migration, "migration must remove spending from approval list"
assert "READ-ONLY ДИАГНОСТИКА" in migration, "migration must insert guardrail 8"

# AGENTS.md is always-copied (not seed-if-absent) — verify bootstrap wiring
deployment = (ROOT / "clusters/prod/infra/hermes-agent.yaml").read_text(encoding="utf-8")
assert "cp /config/agents-md /opt/data/.codex/AGENTS.md" in deployment
assert "[ -f /opt/data/.codex/AGENTS.md ] ||" not in deployment

print("hermes-diagnostics-policy-ok")
