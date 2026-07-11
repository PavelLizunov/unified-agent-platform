#!/usr/bin/env python3
"""Read-only Hermes readiness evidence collector. Run on uap-ops-1."""

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
PILOTS = {
    "unified-agent-platform": "master",
    "VPNRouter": "main",
    "vpnctl": "main",
    "vpnrouter-gateway": "main",
    "suflyor": "master",
}
TOKEN = re.compile(r"(?i)(authorization|password|secret|token)(\s*[:=]\s*)\S+")


def safe(text: str, limit: int = 1200) -> str:
    return TOKEN.sub(r"\1\2[REDACTED]", text.replace("\x00", ""))[:limit]


def command(args: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        done = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return done.returncode, done.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, safe(str(exc))


def model_verdict(managed: dict, user: dict, status_model: str) -> tuple[bool, str]:
    model = managed.get("model") or {}
    expected = model.get("default")
    aliases = sorted(set(model) & {"model", "name"})
    ok = bool(expected) and not aliases and status_model == expected
    return ok, f"managed_default={expected!r} user_default={(user.get('model') or {}).get('default')!r} status={status_model!r} aliases={aliases}"


def contract_verdict(paths: set[str]) -> tuple[bool, str]:
    workflows = any(path.startswith(".github/workflows/") for path in paths)
    build_files = {
        "Cargo.toml", "go.mod", "package.json", "pyproject.toml", "Makefile", "justfile",
        "CONTRIBUTING.md", "tests/verify-local.ps1",
    }
    build = sorted(paths & build_files)
    ok = "AGENTS.md" in paths and workflows and bool(build)
    return ok, f"AGENTS={'AGENTS.md' in paths} CI={workflows} build={build}"


def emit(rows: list[dict], gate: str, check: str, passed: bool, evidence: str) -> None:
    rows.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "gate": gate,
            "check": check,
            "status": "PASS" if passed else "FAIL",
            "evidence": safe(evidence),
        }
    )


def check_git_flux(rows: list[dict]) -> None:
    rc, sha = command(["git", "rev-parse", "origin/master"])
    sha = sha.strip()
    emit(rows, "M2", "git.origin_master", rc == 0 and len(sha) == 40, sha)
    for kind in ("gitrepository", "kustomization"):
        rc, out = command(["kubectl", "-n", "flux-system", "get", kind, "uap-platform", "-o", "json"])
        try:
            obj = json.loads(out)
            status = obj.get("status", {})
            revision = json.dumps(status)
            ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions", []))
            concise = status.get("artifact", {}).get("revision") or status.get("lastAppliedRevision") or status.get("conditions", [{}])[0].get("message", "")
        except json.JSONDecodeError:
            revision, ready, concise = out, False, out
        emit(rows, "M2", f"flux.{kind}", rc == 0 and sha in revision and ready, concise)


def check_runtime(rows: list[dict]) -> None:
    rc, out = command(["kubectl", "-n", "uap-system", "get", "deployment", "hermes-agent", "-o", "json"])
    try:
        deploy = json.loads(out)
        available = deploy["status"].get("availableReplicas") == 1
        image = deploy["spec"]["template"]["spec"]["containers"][0]["image"]
    except (json.JSONDecodeError, KeyError, IndexError):
        available, image = False, out
    emit(rows, "M1", "runtime.deployment", rc == 0 and available, image)

    probe = (
        "import json,yaml;"
        "m=yaml.safe_load(open('/etc/hermes/config.yaml')) or {};"
        "u=yaml.safe_load(open('/opt/data/config.yaml')) or {};"
        "print(json.dumps({'managed':{'model':m.get('model',{})},'user':{'model':u.get('model',{})}}))"
    )
    rc, out = command(
        ["kubectl", "-n", "uap-system", "exec", "deploy/hermes-agent", "--", "/opt/hermes/.venv/bin/python", "-c", probe]
    )
    rc2, status = command(
        ["kubectl", "-n", "uap-system", "exec", "deploy/hermes-agent", "--", "env", "HOME=/opt/data", "HERMES_HOME=/opt/data", "hermes", "status"]
    )
    match = re.search(r"Model:\s+([^\s]+)", status)
    try:
        configs = json.loads(out.splitlines()[-1])
        ok, detail = model_verdict(configs["managed"], configs["user"], match.group(1) if match else "")
    except (json.JSONDecodeError, KeyError, IndexError):
        ok, detail = False, f"model probe parse failed; status_model={match.group(1) if match else ''!r}"
    emit(rows, "M1", "runtime.effective_model", rc == 0 and rc2 == 0 and ok, detail)


def check_dashboard(rows: list[dict]) -> None:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        urllib.request.build_opener(NoRedirect).open("http://100.94.228.67:30911/chat", timeout=8)
        code, location = 200, ""
    except urllib.error.HTTPError as exc:
        code, location = exc.code, exc.headers.get("Location", "")
    except OSError as exc:
        code, location = 0, str(exc)
    emit(rows, "M9", "dashboard.auth_redirect", code == 302 and location.startswith("/auth/login"), f"{code} {location}")


def check_fleet(rows: list[dict]) -> None:
    paths = {
        "home1": ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "uap@100.106.223.120", "hostname"],
        "home2": ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "uap@100.94.228.67", "hostname"],
        "build1": ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "uap@100.85.56.31", "hostname"],
        "debian_via_build1": ["ssh", "uap@100.85.56.31", "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "tester@100.81.162.66", "hostname"],
        "mac_via_build1": ["ssh", "uap@100.85.56.31", "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "slovn@100.116.97.112", "hostname"],
    }
    for name, args in paths.items():
        rc, out = command(args, timeout=12)
        emit(rows, "M3", f"fleet.{name}", rc == 0, out)


def check_github(rows: list[dict]) -> None:
    for repo, branch in PILOTS.items():
        rc, out = command(["gh", "api", f"repos/PavelLizunov/{repo}/rulesets"])
        try:
            rules = json.loads(out)
            active = [r.get("name") for r in rules if r.get("enforcement") == "active" and r.get("target") == "branch"]
        except json.JSONDecodeError:
            active = []
        emit(rows, "M6", f"github.{repo}.ruleset", rc == 0 and bool(active), f"branch={branch} active={active}")

        rc, out = command(["gh", "api", f"repos/PavelLizunov/{repo}/git/trees/{branch}?recursive=1"])
        try:
            paths = {x["path"] for x in json.loads(out).get("tree", []) if x.get("type") == "blob"}
        except (json.JSONDecodeError, KeyError):
            paths = set()
        passed, detail = contract_verdict(paths)
        emit(rows, "M12", f"contract.{repo}.structure", rc == 0 and passed, detail)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="also write JSONL evidence to this path")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        assert model_verdict({"model": {"provider": "x", "default": "m"}}, {"model": {"default": "old"}}, "m")[0]
        assert not model_verdict({"model": {"provider": "x", "model": "m"}}, {"model": {"default": "old"}}, "old")[0]
        assert "topsecret" not in safe("token=topsecret")
        print("readiness-self-check-ok")
        return 0

    rows: list[dict] = []
    for check in (check_git_flux, check_runtime, check_dashboard, check_fleet, check_github):
        try:
            check(rows)
        except Exception as exc:  # keep later checks observable; the row is still a hard failure
            emit(rows, "HARNESS", check.__name__, False, f"{type(exc).__name__}: {exc}")
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    sys.stdout.write(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 1 if any(row["status"] != "PASS" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
