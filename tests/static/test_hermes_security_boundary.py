#!/usr/bin/env python3
"""Static security-boundary gate for the hermes-agent deployment (F2/F3/F4).

Locks in the HONEST trust model from SECURITY-REMEDIATION-2026-07-24.md so a future edit cannot
silently regress a boundary or re-introduce a false "tailnet-only" / "scanner protects" claim:

  F4  - the research codex child is the ONLY separately-scrubbed child (untrusted-content boundary):
        its env is allowlisted so NONE of the gateway's co-located app secrets inherit, and the required
        egress proxy vars are proven present. MCP server processes and the brain share the pod trust
        domain and are NOT proven separately scrubbed — that wording is locked, and the false claim that
        MCP-stdio children are env-scrubbed is forbidden.
  F4  - the disposable terminal-snapshot cache (upstream #62336) is shadowed by an emptyDir so a
        future local-terminal snapshot cannot land on the durable PVC -> R2 backup.
  F4  - the gateway env still carries the full co-located secret set BY DESIGN (the brain inherits
        it via os.environ.copy()); the state is asserted so any change is a reviewed diff.
  F4  - the gateway ServiceAccount token is NOT mounted (the k8s-API boundary that holds).
  F3  - the Codex brain runs danger-full-access / approval_policy=never and the config documents
        the pod as the SOLE boundary; Tirith is locked as NOT installed / not scanning the brain path,
        and the unverified upstream tirith_fail_open default is forbidden (no false protection claim).
  F2  - the dashboard/api Services are NodePort (LAN-reachable) and the docs no longer claim
        "tailnet-only".
"""

from __future__ import annotations

import importlib.util
import pathlib

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load_research_module():
    path = ROOT / "clusters/prod/infra/files/hermes_research_session.py"
    spec = importlib.util.spec_from_file_location("hermes_research_session", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    research = _load_research_module()

    # --- F4: research child env allowlist (deterministic negative test + required vars proven) ---
    assert research._CHILD_ENV_ALLOWLIST == frozenset(
        {"PATH", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"}
    )
    gateway_secrets = {
        "API_SERVER_KEY": "api-secret",
        "CLAUDE_CODE_OAUTH_TOKEN": "claude-secret",
        "HERMES_MISSION_OWNER_KEY": "owner-secret",
        "HERMES_MISSION_PRODUCER_KEY": "producer-secret",
        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD": "dashboard-secret",
        "TELEGRAM_BOT_TOKEN": "telegram-secret",
    }
    base = {"PATH": "/usr/bin:/bin"}
    base.update(gateway_secrets)
    env = research._scrubbed_child_env(base, "/tmp/research-home", "/tmp/research-codex")
    # negative: NO gateway secret inherits into the research child
    for secret_key in gateway_secrets:
        assert secret_key not in env, secret_key
    # allowlisted PATH is preserved
    assert env["PATH"] == "/usr/bin:/bin"
    # required egress vars are PROVEN present even though absent from the base environ
    assert env["HTTPS_PROXY"] == research.DEFAULT_PROXY
    assert env["HTTP_PROXY"] == research.DEFAULT_PROXY
    assert env["NO_PROXY"] == research.DEFAULT_NO_PROXY
    # per-request isolation pins
    assert env["HOME"] == "/tmp/research-home"
    assert env["CODEX_HOME"] == "/tmp/research-codex"
    # an explicit proxy in the base environ is preserved (setdefault does not override)
    env2 = research._scrubbed_child_env({"HTTPS_PROXY": "http://custom:1"}, "/h", "/c")
    assert env2["HTTPS_PROXY"] == "http://custom:1"
    assert env2["HTTP_PROXY"] == research.DEFAULT_PROXY

    # --- load the deployment manifest ---
    deployment_text = (ROOT / "clusters/prod/infra/hermes-agent.yaml").read_text(
        encoding="utf-8"
    )
    documents = list(yaml.safe_load_all(deployment_text))
    deployment = next(
        document for document in documents
        if document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("name") == "hermes-agent"
    )
    template = deployment["spec"]["template"]
    gateway = next(
        container for container in template["spec"]["containers"]
        if container["name"] == "gateway"
    )

    # --- F4: terminal-snapshot cache shadowed by an emptyDir (#62336 mitigation) ---
    terminal_mount = next(
        mount for mount in gateway["volumeMounts"] if mount["name"] == "terminal-cache"
    )
    assert terminal_mount == {
        "name": "terminal-cache",
        "mountPath": "/opt/data/cache/terminal",
    }
    terminal_volume = next(
        volume for volume in template["spec"]["volumes"]
        if volume["name"] == "terminal-cache"
    )
    assert terminal_volume == {"name": "terminal-cache", "emptyDir": {}}

    # --- F4: honest co-location — the gateway env STILL carries the full secret set by design ---
    gateway_env = {entry["name"] for entry in gateway["env"]}
    for co_located in (
        "API_SERVER_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "HERMES_MISSION_OWNER_KEY",
        "HERMES_MISSION_PRODUCER_KEY",
        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD",
    ):
        assert co_located in gateway_env, co_located

    # --- F3: Tirith is never lazy-installed => inert ---
    assert "HERMES_DISABLE_LAZY_INSTALLS" in gateway_env

    # --- F4: the gateway ServiceAccount token is NOT mounted (the k8s-API boundary that holds) ---
    assert template["spec"]["automountServiceAccountToken"] is False
    service_account = next(
        document for document in documents
        if document.get("kind") == "ServiceAccount"
        and document.get("metadata", {}).get("name") == "hermes-agent"
    )
    assert service_account["automountServiceAccountToken"] is False

    # --- F2: dashboard + api are NodePort (LAN-reachable; documented, NOT tailnet-only) ---
    dashboard_svc = next(
        document for document in documents
        if document.get("kind") == "Service"
        and document.get("metadata", {}).get("name") == "hermes-agent-dashboard"
    )
    api_svc = next(
        document for document in documents
        if document.get("kind") == "Service"
        and document.get("metadata", {}).get("name") == "hermes-agent-api"
    )
    assert dashboard_svc["spec"]["type"] == "NodePort"
    assert api_svc["spec"]["type"] == "NodePort"
    # the honest exposure note replaced the "over the tailnet" framing
    assert "Web dashboard over the tailnet." not in deployment_text
    assert "It is NOT tailnet-only." in deployment_text

    # --- F3: honest security boundary documented in the codex config (no false protection claim) ---
    config_map = yaml.safe_load(
        (ROOT / "clusters/prod/infra/hermes-agent-config.yaml").read_text(encoding="utf-8")
    )
    codex_toml = config_map["data"]["codex-config.toml"]
    assert 'sandbox_mode = "danger-full-access"' in codex_toml
    assert 'approval_policy = "never"' in codex_toml
    assert "HONEST SECURITY BOUNDARY" in codex_toml
    assert "SOLE boundary" in codex_toml

    # F3 — Tirith: lock the PROVEN statement (not installed; does not scan the brain path) and forbid the
    # unverified upstream fail-open/silent claim, which is not re-checked against the pinned image here.
    assert "Tirith is INERT here" in codex_toml
    assert "does NOT scan the Codex brain path" in codex_toml
    assert "tirith_fail_open" not in codex_toml
    assert "passes\" silently" not in codex_toml

    # F4 — credential boundary: lock the precise trust-domain wording. MCP server processes and the brain
    # share the pod trust domain and are NOT proven separately scrubbed; ONLY the research Codex child
    # (untrusted-content boundary) is scrubbed by _scrubbed_child_env. Forbid the old false claim that
    # MCP-stdio children are env-scrubbed.
    assert "share this pod trust domain and are NOT proven" in codex_toml
    assert "ONLY separately-scrubbed child is the research Codex child" in codex_toml
    assert "_scrubbed_child_env" in codex_toml
    assert "MCP-stdio children" not in codex_toml
    assert "ARE env-scrubbed" not in codex_toml

    # --- F2: the authoritative false claim is gone from DECISIONS.md ---
    decisions = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
    assert "exposed only on the tailnet NodePort" not in decisions
    assert "reachable on the tailnet **AND the home LAN**" in decisions

    # --- F2: the legacy hermes README no longer states the false "tailnet-only" fact ---
    hermes_readme = (ROOT / "hermes/README.md").read_text(encoding="utf-8")
    assert "is tailnet-only and" not in hermes_readme
    assert "and tailnet-only" not in hermes_readme
    assert "NOT tailnet-only" in hermes_readme

    print("hermes-security-boundary-ok")


if __name__ == "__main__":
    main()
