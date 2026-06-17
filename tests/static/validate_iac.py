#!/usr/bin/env python3
import re
import subprocess
import sys
from pathlib import Path

import yaml


REQUIRED_PATHS = [
    "infra/tofu/README.md",
    "infra/tofu/modules/proxmox-vm/main.tf",
    "infra/tofu/environments/local-proxmox/main.tf",
    "infra/ansible/ansible.cfg",
    "infra/ansible/inventories/local.yml",
    "infra/ansible/inventories/prod.example.yml",
    "infra/ansible/playbooks/site.yml",
    "tests/smoke/uap-smoke-config.ps1",
    "tests/smoke/run-all.ps1",
]

SECRET_PATTERNS = [
    re.compile(r"AGE-SECRET-KEY", re.IGNORECASE),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY", re.IGNORECASE),
    re.compile(r"PVEAuthCookie", re.IGNORECASE),
    re.compile(r"CSRFPreventionToken", re.IGNORECASE),
    re.compile(r"client-key-data", re.IGNORECASE),
    re.compile(r"client-certificate-data", re.IGNORECASE),
    re.compile(r"768954"),
]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def git_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [root / line.strip() for line in result.stdout.splitlines() if line.strip()]


def validate_required_paths(root: Path) -> None:
    for path in REQUIRED_PATHS:
      if not (root / path).exists():
          fail(f"required path is missing: {path}")


def validate_yaml(root: Path) -> None:
    for path in git_files(root):
        if path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        if ".git" in path.parts:
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                list(yaml.safe_load_all(handle))
        except Exception as exc:  # noqa: BLE001 - static validation should report any YAML parser error.
            fail(f"YAML parse failed for {path.relative_to(root)}: {exc}")


def validate_no_plaintext_secrets(root: Path) -> None:
    for path in git_files(root):
        if path.relative_to(root).as_posix() == "tests/static/validate_iac.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                fail(f"secret-like pattern {pattern.pattern!r} found in {path.relative_to(root)}")


def validate_tofu(root: Path) -> None:
    committed_tfvars = [
        path.relative_to(root).as_posix()
        for path in git_files(root)
        if path.name.endswith(".tfvars") and not path.name.endswith(".tfvars.example")
    ]
    if committed_tfvars:
        fail(f"plain tfvars files must not be committed: {committed_tfvars}")

    for path in (root / "infra" / "tofu").rglob("*.tf"):
        text = path.read_text(encoding="utf-8")
        if "remote-exec" in text or re.search(r"\bprovisioner\b", text):
            fail(f"OpenTofu must not use provisioners or remote-exec: {path.relative_to(root)}")


def inventory_hosts(group: dict) -> set[str]:
    hosts = set((group.get("hosts") or {}).keys())
    for child in (group.get("children") or {}).values():
        if child:
            hosts |= inventory_hosts(child)
    return hosts


def validate_ansible_inventory(root: Path) -> None:
    for rel in ["infra/ansible/inventories/local.yml", "infra/ansible/inventories/prod.example.yml"]:
        with (root / rel).open("r", encoding="utf-8") as handle:
            inventory = yaml.safe_load(handle)
        children = inventory.get("all", {}).get("children", {})
        if "k3s_servers" not in children:
            fail(f"{rel} must define k3s_servers")
        if "k3s_agents" not in children:
            fail(f"{rel} must define k3s_agents")
        server_hosts = inventory_hosts(children["k3s_servers"])
        if not server_hosts:
            fail(f"{rel} must have at least one k3s server")


def validate_smoke_scripts(root: Path) -> None:
    config_line = '. "$PSScriptRoot\\uap-smoke-config.ps1"'
    for path in (root / "tests" / "smoke").glob("*.ps1"):
        if path.name in {"uap-smoke-config.ps1", "run-all.ps1"}:
            continue
        text = path.read_text(encoding="utf-8")
        if config_line not in text:
            fail(f"{path.relative_to(root)} must import uap-smoke-config.ps1")


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    validate_required_paths(root)
    validate_yaml(root)
    validate_no_plaintext_secrets(root)
    validate_tofu(root)
    validate_ansible_inventory(root)
    validate_smoke_scripts(root)
    print("iac-static-ok")


if __name__ == "__main__":
    main()
