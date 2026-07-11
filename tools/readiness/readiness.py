#!/usr/bin/env python3
"""Read-only Hermes readiness evidence collector. Run on uap-ops-1."""

import argparse
import base64
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


def guardrail_verdict(config: dict) -> tuple[bool, str]:
    expected_warn = {"exact_failure": 2, "same_tool_failure": 3, "idempotent_no_progress": 2}
    expected_stop = {"exact_failure": 5, "same_tool_failure": 8, "idempotent_no_progress": 5}
    ok = (
        config.get("warnings_enabled") is True
        and config.get("hard_stop_enabled") is True
        and config.get("warn_after") == expected_warn
        and config.get("hard_stop_after") == expected_stop
    )
    return ok, (
        f"warnings={config.get('warnings_enabled')!r} hard_stop={config.get('hard_stop_enabled')!r} "
        f"warn_after={config.get('warn_after')!r} hard_stop_after={config.get('hard_stop_after')!r}"
    )


def exec_failure_classifier_verdict(output: str) -> tuple[bool, str]:
    try:
        data = json.loads(output.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return False, "exec_command failure-classifier probe did not return JSON"
    failed = data.get("failed") is True
    return failed, f"exec_command_[exit_1]_classified_failed={failed}"


def dashboard_model_verdict(output: str) -> tuple[bool, str]:
    try:
        data = json.loads(output.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return False, "authenticated dashboard probe did not return JSON"
    ok = (
        data.get("login_ok") is True
        and data.get("model") == data.get("expected_model")
        and data.get("provider") == data.get("expected_provider")
    )
    return ok, (
        f"login_ok={data.get('login_ok')!r} model={data.get('model')!r} "
        f"provider={data.get('provider')!r} expected_model={data.get('expected_model')!r} "
        f"expected_provider={data.get('expected_provider')!r}"
    )


def contract_verdict(paths: set[str]) -> tuple[bool, str]:
    workflows = any(path.startswith(".github/workflows/") for path in paths)
    build_files = {
        "Cargo.toml", "go.mod", "package.json", "pyproject.toml", "Makefile", "justfile",
        "CONTRIBUTING.md", "tests/verify-local.ps1",
    }
    build = sorted(paths & build_files)
    ok = "AGENTS.md" in paths and workflows and bool(build)
    return ok, f"AGENTS={'AGENTS.md' in paths} CI={workflows} build={build}"


def known_contract_conflicts(repo: str, files: dict[str, str]) -> tuple[bool, str]:
    issues = []
    agents = files.get("AGENTS.md", "")
    contributing = files.get("CONTRIBUTING.md", "")
    if repo == "VPNRouter":
        if not agents:
            issues.append("AGENTS.md unavailable")
        direct_main = (
            "git push github HEAD:main && git push origin HEAD:main",
            "git push origin HEAD:main && git push forgejo HEAD:main",
            "**Default = autonomous до stable.**",
        )
        if any(rule in agents for rule in direct_main):
            issues.append("direct-main/autonomous-release policy")
        if "НЕТ remote с именем `github`" in agents and "git push github HEAD:main" in agents:
            issues.append("contradictory remote names")
    elif repo == "suflyor":
        if not contributing:
            issues.append("CONTRIBUTING.md unavailable")
        if "suflyor-tts/" not in contributing:
            issues.append("CONTRIBUTING omits suflyor-tts")
        if "%APPDATA%\\overlay-mvp\\config.json" in contributing:
            issues.append("stale secret-config path")
        if "gh release create" in contributing and "owner" not in contributing.lower():
            issues.append("release authority conflict")
    return not issues, "; ".join(issues) if issues else "no known semantic conflicts"


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
        "print(json.dumps({'managed':{'model':m.get('model',{}),'guardrails':m.get('tool_loop_guardrails',{})},'user':{'model':u.get('model',{})}}))"
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
    try:
        guard_ok, guard_detail = guardrail_verdict(configs["managed"]["guardrails"])
    except (KeyError, UnboundLocalError):
        guard_ok, guard_detail = False, "managed guardrail probe unavailable"
    emit(rows, "M11", "runtime.tool_loop_guardrails", rc == 0 and guard_ok, guard_detail)

    failure_probe = (
        "import json;"
        "from agent.tool_guardrails import classify_tool_failure;"
        "failed,reason=classify_tool_failure('exec_command','[exit 1]\\n');"
        "print(json.dumps({'failed':failed,'reason':reason}))"
    )
    rc3, failure_out = command(
        ["kubectl", "-n", "uap-system", "exec", "deploy/hermes-agent", "--",
         "/opt/hermes/.venv/bin/python", "-c", failure_probe]
    )
    classifier_ok, classifier_detail = exec_failure_classifier_verdict(failure_out)
    emit(rows, "M11", "runtime.exec_failure_classification", rc3 == 0 and classifier_ok, classifier_detail)


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
    emit(rows, "M9", "dashboard.auth_redirect", code == 302 and location.startswith("/login?"), f"{code} {location}")

    try:
        page = urllib.request.urlopen("http://100.94.228.67:30911/login?next=%2Fchat", timeout=8)
        login_code, login_body = page.status, page.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, OSError) as exc:
        login_code, login_body = 0, str(exc)
    emit(
        rows, "M9", "dashboard.password_login_page",
        login_code == 200 and "/auth/password-login" in login_body,
        f"status={login_code} password_form={'/auth/password-login' in login_body}",
    )

    probe = (
        "import http.cookiejar,json,os,urllib.request,yaml;"
        "base='http://127.0.0.1:9119';jar=http.cookiejar.CookieJar();"
        "opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar));"
        "managed=yaml.safe_load(open('/etc/hermes/config.yaml')) or {};"
        "payload=json.dumps({'provider':'basic','username':os.environ['HERMES_DASHBOARD_BASIC_AUTH_USERNAME'],"
        "'password':os.environ['HERMES_DASHBOARD_BASIC_AUTH_PASSWORD'],'next':'/chat'}).encode();"
        "req=urllib.request.Request(base+'/auth/password-login',data=payload,headers={'Content-Type':'application/json'},method='POST');"
        "login=json.loads(opener.open(req,timeout=8).read());"
        "info=json.loads(opener.open(base+'/api/model/info',timeout=8).read());"
        "print(json.dumps({'login_ok':login.get('ok'),'model':info.get('model'),'provider':info.get('provider'),"
        "'expected_model':(managed.get('model') or {}).get('default'),'expected_provider':(managed.get('model') or {}).get('provider')}))"
    )
    rc, out = command(
        ["kubectl", "-n", "uap-system", "exec", "deploy/hermes-agent", "--",
         "/opt/hermes/.venv/bin/python", "-c", probe]
    )
    model_ok, model_detail = dashboard_model_verdict(out)
    emit(rows, "M9", "dashboard.authenticated_model", rc == 0 and model_ok, model_detail)


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

        if repo in {"VPNRouter", "suflyor"}:
            files = {}
            for path in ("AGENTS.md", "CONTRIBUTING.md"):
                rc2, body = command(["gh", "api", f"repos/PavelLizunov/{repo}/contents/{path}"])
                try:
                    obj = json.loads(body)
                    files[path] = base64.b64decode(obj["content"]).decode("utf-8") if rc2 == 0 else ""
                except (json.JSONDecodeError, KeyError, ValueError, UnicodeDecodeError):
                    files[path] = ""
            semantic, detail = known_contract_conflicts(repo, files)
            emit(rows, "M12", f"contract.{repo}.known_conflicts", semantic, detail)

    rc, body = command(["gh", "api", "repos/PavelLizunov/vpnctl/commits/main"])
    try:
        remote_sha = json.loads(body)["sha"]
    except (json.JSONDecodeError, KeyError):
        remote_sha = ""
    rc_head, local_sha = command(
        ["ssh", "-o", "BatchMode=yes", "uap@100.85.56.31", "git", "-C", "/home/uap/vpnctl", "rev-parse", "HEAD"]
    )
    rc_dirty, dirty = command(
        ["ssh", "-o", "BatchMode=yes", "uap@100.85.56.31", "git", "-C", "/home/uap/vpnctl", "status", "--porcelain"]
    )
    rc_just, _ = command(
        ["ssh", "-o", "BatchMode=yes", "uap@100.85.56.31", "command", "-v", "just"]
    )
    local_sha = local_sha.strip()
    ready = rc == rc_head == rc_dirty == 0 and local_sha == remote_sha and not dirty.strip() and rc_just == 0
    emit(
        rows,
        "M12",
        "contract.vpnctl.build1_ready",
        ready,
        f"head_matches={local_sha == remote_sha} clean={not bool(dirty.strip())} just={rc_just == 0}",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="also write JSONL evidence to this path")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        assert model_verdict({"model": {"provider": "x", "default": "m"}}, {"model": {"default": "old"}}, "m")[0]
        assert not model_verdict({"model": {"provider": "x", "model": "m"}}, {"model": {"default": "old"}}, "old")[0]
        assert guardrail_verdict({
            "warnings_enabled": True,
            "hard_stop_enabled": True,
            "warn_after": {"exact_failure": 2, "same_tool_failure": 3, "idempotent_no_progress": 2},
            "hard_stop_after": {"exact_failure": 5, "same_tool_failure": 8, "idempotent_no_progress": 5},
        })[0]
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
