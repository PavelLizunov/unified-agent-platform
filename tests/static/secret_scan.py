#!/usr/bin/env python3
import re
import subprocess
import sys
from pathlib import Path


PATTERNS = [
    ("age private key", re.compile(r"AGE-SECRET-KEY", re.IGNORECASE)),
    ("private key block", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY", re.IGNORECASE)),
    ("Proxmox auth cookie", re.compile(r"PVEAuthCookie", re.IGNORECASE)),
    ("Proxmox csrf token", re.compile(r"CSRFPreventionToken", re.IGNORECASE)),
    ("kubeconfig client key", re.compile(r"client-key-data", re.IGNORECASE)),
    ("kubeconfig client certificate", re.compile(r"client-certificate-data", re.IGNORECASE)),
    ("known Proxmox password from bootstrap chat", re.compile(r"768954")),
    ("Tailscale auth key", re.compile(r"tskey-(?:auth|client|api)-[A-Za-z0-9_-]+")),
    ("plain tfvars password", re.compile(r"(?m)^\s*proxmox_password\s*=\s*\"(?!REPLACE_)")),
    ("plain tfvars api token", re.compile(r"(?m)^\s*proxmox_api_token\s*=\s*\"(?!REPLACE_)")),
    # Provider tokens (plaintext) — these must only ever appear SOPS-encrypted (ENC[...]).
    ("Anthropic API/OAuth token", re.compile(r"\bsk-ant-[a-z0-9]{2,8}-[A-Za-z0-9_-]{24,}")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}|\bsk-[A-Za-z0-9_-]{40,}")),
    ("OpenRouter key", re.compile(r"\bsk-or-v1-[A-Za-z0-9]{24,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("AWS/R2 access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Telegram bot token", re.compile(r"\b[0-9]{8,10}:[A-Za-z0-9_-]{35}\b")),
]

SKIP_FILES = {
    "tests/static/secret_scan.py",
    "tests/static/validate_iac.py",
}


def repo_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [root / line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    findings: list[str] = []

    for path in repo_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in SKIP_FILES or rel.startswith(".git/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for label, pattern in PATTERNS:
            if pattern.search(text):
                findings.append(f"{rel}: matched {label}")

    if findings:
        print("Secret scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        raise SystemExit(1)

    print("secret-scan-ok")


if __name__ == "__main__":
    main()
