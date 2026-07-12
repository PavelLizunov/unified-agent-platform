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


def _unencrypted_leaves(prefix: str, node: object, bad: list[str]) -> None:
    """Recurse dicts + lists; append the dotted path of any non-empty string leaf not ENC[...]."""
    if isinstance(node, dict):
        for key, value in node.items():
            _unencrypted_leaves(f"{prefix}.{key}", value, bad)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            _unencrypted_leaves(f"{prefix}[{idx}]", value, bad)
    elif isinstance(node, str):
        if node.strip() and not node.startswith("ENC["):
            bad.append(prefix)


def _sops_unencrypted_values(path: Path) -> list[str]:
    """Return dotted paths of any non-empty data/stringData string leaf in a SOPS file that is NOT
    SOPS-encrypted (does not start with 'ENC['). Empty strings (e.g. optional config keys) are
    allowed. Recurses into nested dicts/lists so a token can't hide in a sub-structure. Scoped to
    data/stringData to mirror the .sops.yaml `encrypted_regex: ^(data|stringData)$`."""
    bad: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        docs = list(yaml.safe_load_all(handle))
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        for section in ("data", "stringData"):
            if section in doc:
                _unencrypted_leaves(section, doc[section], bad)
    return bad


def validate_sops_encrypted(root: Path) -> None:
    """Every committed *.sops.yaml must have its Secret data/stringData values SOPS-encrypted.
    Closes the hole where a plaintext secret in a .sops.yaml (whose whole path is allowlisted by
    gitleaks) would otherwise reach the repo. Deterministic: no reliance on entropy heuristics."""
    for path in git_files(root):
        name = path.name.lower()
        if not (name.endswith(".sops.yaml") or name.endswith(".sops.yml")):
            continue
        try:
            bad = _sops_unencrypted_values(path)
        except Exception as exc:  # noqa: BLE001 - any parse error on a secret file must fail loudly.
            fail(f"SOPS file failed to parse: {path.relative_to(root)}: {exc}")
        if bad:
            fail(
                f"SOPS file {path.relative_to(root)} has UNENCRYPTED value(s) {sorted(bad)} "
                "(each must be 'ENC[...]'); run `sops -e -i` before committing."
            )


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


def _kustomization_referenced(rootr: Path, clusters_dir: Path) -> set[str]:
    """Repo-root-relative paths referenced by ANY kustomization under clusters/, with each
    `resources:` entry resolved relative to its OWN kustomization's directory.

    Resolving relative to the kustomization directory (instead of comparing basenames) is what makes
    `../shared/foo.yaml`, sibling references, and same-name files in different directories
    distinguishable — a basename compare conflates them (a `../shared/foo.yaml` reference would mask a
    local unreferenced `foo.yaml`, and a duplicate basename in another dir would be wrongly cleared)."""
    referenced: set[str] = set()
    for kust in clusters_dir.rglob("*"):
        if not kust.is_file() or kust.name.lower() not in {"kustomization.yaml", "kustomization.yml"}:
            continue
        with kust.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        # resources + the other file/dir-list fields kustomize applies, so a manifest pulled in via
        # components/bases/crds is not falsely flagged as an unapplied orphan.
        entries: list[str] = []
        for field in ("resources", "components", "bases", "crds"):
            entries.extend(data.get(field) or [])
        for entry in entries:
            if not isinstance(entry, str):
                continue
            resolved = (kust.parent / entry).resolve()
            try:
                referenced.add(resolved.relative_to(rootr).as_posix())
            except ValueError:
                continue  # resolves outside the repo root — not a local orphan candidate
    return referenced


def _find_kustomization_orphans(root: Path) -> list[str]:
    """Return sorted repo-root-relative paths of cluster yaml files not referenced by ANY kustomization
    (resources resolved relative to each kustomization's directory, not by basename)."""
    rootr = root.resolve()
    clusters_dir = rootr / "clusters"
    if not clusters_dir.is_dir():
        return []

    referenced = _kustomization_referenced(rootr, clusters_dir)

    orphans: list[str] = []
    for yaml_file in sorted(clusters_dir.rglob("*")):
        if not yaml_file.is_file() or yaml_file.suffix.lower() not in {".yaml", ".yml"}:
            continue
        if yaml_file.name.lower() in {"kustomization.yaml", "kustomization.yml"}:
            continue
        rel = yaml_file.resolve().relative_to(rootr).as_posix()
        if rel in KUSTOMIZATION_ORPHAN_ALLOWLIST:
            continue
        if rel not in referenced:
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


def validate_kubeconfig_mode(root: Path) -> None:
    config_path = root / "infra" / "k3s" / "uap-home-1.config.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if config.get("write-kubeconfig-mode") != "0600":
        fail("uap-home-1 kubeconfig mode must be the quoted string \"0600\"")

    template = (root / "infra" / "ansible" / "templates" / "k3s-server.config.yaml.j2").read_text()
    if 'write-kubeconfig-mode: "0600"' not in template:
        fail("Ansible k3s server template must render quoted kubeconfig mode \"0600\"")


def validate_k3s_host_firewall(root: Path) -> None:
    unit = (root / "infra" / "k3s" / "uap-k3s-lan-firewall.service").read_text()
    required = (
        "-i eth0 -p tcp -m multiport --dports 6443,10250 -j DROP",
        "-i eth0 -p udp --dport 8472 -j DROP",
        "ExecStop=-/usr/sbin/iptables -D INPUT -j UAP-LAN-INPUT",
    )
    missing = [line for line in required if line not in unit]
    if missing:
        fail(f"k3s host firewall unit missing safeguards: {missing}")


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    validate_required_paths(root)
    validate_yaml(root)
    validate_no_plaintext_secrets(root)
    validate_sops_encrypted(root)
    validate_tofu(root)
    validate_ansible_inventory(root)
    validate_smoke_scripts(root)
    validate_flux_examples_not_enabled(root)
    validate_k3s_s3_template(root)
    validate_kubeconfig_mode(root)
    validate_k3s_host_firewall(root)
    validate_kustomization_orphans(root)
    print("iac-static-ok")


if __name__ == "__main__":
    main()
