#!/usr/bin/env python3
"""Static regression: Telegram user authorization policy in managed-env.

Proves:
- owner (729937253) remains platform-wide via TELEGRAM_ALLOWED_USERS;
- second user (242206776) is group-only via TELEGRAM_GROUP_ALLOWED_USERS;
- no whole-chat (TELEGRAM_GROUP_ALLOWED_CHATS) or allow-all (*) authorization exists.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

configmap = yaml.safe_load(
    (ROOT / "clusters/prod/infra/hermes-agent-config.yaml").read_text(encoding="utf-8")
)
managed_env: str = configmap["data"]["managed-env"]

env = {}
for line in managed_env.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    key, _, value = line.partition("=")
    env[key.strip()] = value.strip()

# --- owner is platform-wide ---
allowed_users = env.get("TELEGRAM_ALLOWED_USERS", "")
owner_ids = {s.strip() for s in allowed_users.split(",") if s.strip()}
assert "729937253" in owner_ids, "owner 729937253 must remain in TELEGRAM_ALLOWED_USERS"

# --- second user is group-only ---
group_allowed_users = env.get("TELEGRAM_GROUP_ALLOWED_USERS", "")
group_ids = {s.strip() for s in group_allowed_users.split(",") if s.strip()}
assert "242206776" in group_ids, "user 242206776 must be in TELEGRAM_GROUP_ALLOWED_USERS"
assert "242206776" not in owner_ids, "user 242206776 must NOT be in TELEGRAM_ALLOWED_USERS (group-only)"

# --- no whole-chat or allow-all authorization ---
assert "TELEGRAM_GROUP_ALLOWED_CHATS" not in env, "TELEGRAM_GROUP_ALLOWED_CHATS must not be set"
for key, value in env.items():
    if key.startswith("TELEGRAM"):
        assert value.strip() != "*", f"{key} must not be a wildcard allow-all"

print("hermes-telegram-authz-ok")
