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
    "tests/static/secret-scan.ps1",
    "tests/verify-local.ps1",
    "tests/git/check-git-remote.ps1",
    "tests/ops/check-ops-node.ps1",
    "tests/s3/check-s3-env.ps1",
    "infra/ops/bootstrap-ops-node.sh",
    "runbooks/validation-matrix.md",
    "runbooks/restore-drill.md",
    "runbooks/flux-remote-git.md",
    "runbooks/cloudflare-r2-k3s-snapshots.md",
    "runbooks/uap-ops-node.md",
]

# Intentional exceptions: repo-root-relative paths that are deliberately NOT listed
# as resources in a same-directory kustomization.yaml.
KUSTOMIZATION_ORPHAN_ALLOWLIST = {
    # Flux example/template files; validate_flux_examples_not_enabled already ensures
    # they can never be referenced in a live kustomization.
    "clusters/prod/flux-system/gotk-sync.example.yaml",
    "clusters/prod/flux-system/gotk-sync.https-token.example.yaml",
    "clusters/prod/flux-system/gotk-sync.ssh.example.yaml",
    # SOPS smoke fixture for restore-drill testing — intentionally not a live Flux resource.
    "clusters/prod/infra/sops-smoke.sops.yaml",
    # staging-stage2: REVIEW-ONLY manifests, no kustomization.yaml yet (do not apply to cluster).
    "clusters/staging-stage2/cnpg-cluster.yaml",
    "clusters/staging-stage2/cnpg-operator.helmrelease.yaml",
    "clusters/staging-stage2/garage.yaml",
    # staging-stage3: REVIEW-ONLY manifests, no kustomization.yaml yet (do not apply to cluster).
    "clusters/staging-stage3/litellm.yaml",
    "clusters/staging-stage3/singbox-egress.yaml",
    "clusters/staging-stage3/subfleet-helmrelease.yaml",
}

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
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
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
        if path.relative_to(root).as_posix() in {
            "tests/static/validate_iac.py",
            "tests/static/secret_scan.py",
        }:
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


def validate_flux_examples_not_enabled(root: Path) -> None:
    kustomization_path = root / "clusters" / "prod" / "flux-system" / "kustomization.yaml"
    text = kustomization_path.read_text(encoding="utf-8")
    forbidden = [
        "gotk-sync.example.yaml",
        "gotk-sync.ssh.example.yaml",
        "gotk-sync.https-token.example.yaml",
    ]
    for name in forbidden:
        if name in text:
            fail(f"{name} must not be referenced until a real remote Git URL exists")


def _find_kustomization_orphans(root: Path) -> list[str]:
    """Return sorted repo-root-relative paths of cluster yaml files not in a same-dir kustomization."""
    clusters_dir = root / "clusters"
    if not clusters_dir.is_dir():
        return []

    orphans: list[str] = []
    dirs = [clusters_dir] + sorted(p for p in clusters_dir.rglob("*") if p.is_dir())

    for directory in dirs:
        yaml_files = sorted(
            f for f in directory.iterdir()
            if f.is_file()
            and f.suffix.lower() in {".yaml", ".yml"}
            and f.name.lower() not in {"kustomization.yaml", "kustomization.yml"}
        )
        if not yaml_files:
            continue

        kustomization = directory / "kustomization.yaml"
        if kustomization.exists():
            with kustomization.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            resources = data.get("resources") or []
            referenced = {Path(r).name for r in resources}
        else:
            referenced = set()

        for yaml_file in yaml_files:
            rel = yaml_file.relative_to(root).as_posix()
            if rel in KUSTOMIZATION_ORPHAN_ALLOWLIST:
                continue
            if yaml_file.name not in referenced:
                orphans.append(rel)

    return sorted(orphans)


def validate_kustomization_orphans(root: Path) -> None:
    orphans = _find_kustomization_orphans(root)
    if orphans:
        for orphan in orphans:
            print(f"ERROR: clusters orphan not in kustomization.yaml resources: {orphan}", file=sys.stderr)
        raise SystemExit(1)
    print("kustomization-orphans-ok")


def validate_k3s_s3_template(root: Path) -> None:
    template_path = root / "infra" / "sops" / "templates" / "k3s-etcd-snapshot-s3-config.plaintext.template.yaml"
    with template_path.open("r", encoding="utf-8") as handle:
        docs = list(yaml.safe_load_all(handle))
    secret = docs[0]
    if secret.get("type") != "etcd.k3s.cattle.io/s3-config-secret":
        fail("k3s S3 config template must use type etcd.k3s.cattle.io/s3-config-secret")
    string_data = secret.get("stringData") or {}
    required_keys = {
        "etcd-s3-endpoint",
        "etcd-s3-access-key",
        "etcd-s3-secret-key",
        "etcd-s3-bucket",
        "etcd-s3-folder",
        "etcd-s3-region",
        "etcd-s3-insecure",
        "etcd-s3-timeout",
    }
    missing = sorted(required_keys - set(string_data))
    if missing:
        fail(f"k3s S3 config template missing keys: {missing}")


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    validate_required_paths(root)
    validate_yaml(root)
    validate_no_plaintext_secrets(root)
    validate_tofu(root)
    validate_ansible_inventory(root)
    validate_smoke_scripts(root)
    validate_flux_examples_not_enabled(root)
    validate_k3s_s3_template(root)
    validate_kustomization_orphans(root)
    print("iac-static-ok")


if __name__ == "__main__":
    main()
