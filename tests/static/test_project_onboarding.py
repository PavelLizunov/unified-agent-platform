"""Hermetic ADR-035 project onboarding driver checks."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
DRIVER_PATH = ROOT / "tools/swarm/project_onboarding.py"
COORDINATOR_PATH = ROOT / "tools/swarm/delivery_coordinator.py"
sys.path.insert(0, str(COORDINATOR_PATH.parent))


def load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = load(DRIVER_PATH, "project_onboarding")
coordinator = load(COORDINATOR_PATH, "project_onboarding_coordinator")


def request(preset: str = "rust", checkpoint: str = "requested") -> dict:
    return {
        "request_id": "project-onboarding-0123456789abcdef0123456789abcdef",
        "project_id": "mac-ledger",
        "repository": "PavelLizunov/mac-ledger",
        "name": "mac-ledger",
        "description": "Dependency-free starter",
        "preset": preset,
        "checkpoint": checkpoint,
        "invocations": None,
        "created_at": "2026-07-20T12:00:00.000Z",
        "updated_at": "2026-07-20T12:00:00.000Z",
        "progress_percent": 0,
        "error_code": None,
    }


class ProjectOnboardingTests(unittest.TestCase):
    def test_rendered_profile_hash_matches_coordinator_runtime_profile(self):
        value = request()
        rendered = driver.render_profile(value)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "profile.json"
            path.write_text(json.dumps(rendered), encoding="utf-8")
            loaded = coordinator.load_profile(path)
        self.assertEqual(
            driver.flow_contract.canonical_sha256(rendered),
            driver.flow_contract.canonical_sha256(loaded),
        )

    def test_presets_are_dependency_free_and_require_macos_ci(self):
        expected = {
            "rust": "cargo test --all-targets",
            "go": "go test ./...",
            "python": "python3 -m unittest discover -s tests",
            "web": "node --test",
        }
        expected_paths = {
            "rust": ["README.md", "src"],
            "go": ["README.md", "project.go", "project_test.go"],
            "python": ["README.md", "main.py", "project.py", "tests"],
            "web": ["README.md", "app.js", "index.html", "tests"],
        }
        for preset, command in expected.items():
            value = request(preset)
            files = driver.bootstrap_files(value)
            workflow = files[".github/workflows/ci.yml"]
            self.assertIn("runs-on: macos-latest", workflow)
            self.assertIn(command, workflow)
            self.assertNotIn("npm install", workflow)
            self.assertNotIn("pip install", workflow)
            self.assertNotIn("cargo install", workflow)
            profile = driver.render_profile(value)
            self.assertEqual(["test-macos"], profile["required_ci_checks"])
            self.assertEqual(expected_paths[preset], profile["allowed_path_prefixes"])
            self.assertEqual("none", profile["delivery_mode"])
            self.assertEqual(["multi_platform"], profile["route_flags"])
            with tempfile.TemporaryDirectory() as directory:
                path = pathlib.Path(directory) / driver.profile_name(value)
                path.write_text(json.dumps(profile), encoding="utf-8")
                loaded = coordinator.load_profile(path)
                self.assertEqual(profile["repo"], loaded["repo"])
                self.assertEqual(profile["required_ci_checks"], loaded["required_ci_checks"])
                self.assertEqual(profile["author_checks"], loaded["author_checks"])

    def test_generated_starters_run_with_available_standard_toolchains(self):
        commands = {
            "rust": ["cargo", "test", "--all-targets"],
            "go": ["go", "test", "./..."],
            "python": [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            "web": ["node", "--test"],
        }
        for preset, command in commands.items():
            if shutil.which(command[0]) is None:
                continue
            with self.subTest(preset=preset), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                files = driver.bootstrap_files(request(preset))
                for relative, content in files.items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8", newline="\n")
                result = subprocess.run(
                    command, cwd=root, text=True, capture_output=True, timeout=120,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                if preset == "rust":
                    self.assertEqual(
                        files["Cargo.lock"],
                        (root / "Cargo.lock").read_text(encoding="utf-8"),
                    )

    def test_bootstrap_commit_is_deterministic_after_total_local_loss(self):
        value = request("rust")
        shas = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                instance = driver.Driver(None, home=pathlib.Path(directory))
                _, sha = instance._bootstrap_checkout(value)
                shas.append(sha)
        self.assertEqual(shas[0], shas[1])

    def test_catalog_moves_only_setup_required_to_ready(self):
        original = {
            "project_id": "existing",
            "label": "Existing",
            "repository": "PavelLizunov/existing",
            "summary": "Existing project",
            "aliases": ["existing"],
            "dispatch_profile": "build1-existing-registered-v4",
            "delivery_mode": "none",
            "platforms": ["workspace", "telegram"],
            "category": "registered",
            "status": "ready",
            "test_targets": ["github-macos"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "catalog.yaml"
            path.write_text(
                "apiVersion: v1\nkind: ConfigMap\ndata:\n  projects.json: |-\n"
                "    {\"schema_version\":2,\"projects\":[\n"
                f"      {json.dumps(original, ensure_ascii=False, separators=(',', ':'))}\n"
                "    ]}\n",
                encoding="utf-8",
            )
            value = request()
            driver.update_catalog(path, value, ready=False)
            text = path.read_text(encoding="utf-8")
            payload = json.loads(
                "\n".join(line[4:] for line in text.split("  projects.json: |-\n", 1)[1].splitlines())
            )
            self.assertEqual(original, payload["projects"][0])
            self.assertEqual("setup_required", payload["projects"][1]["status"])
            driver.update_catalog(path, value, ready=True)
            payload = json.loads(
                "\n".join(line[4:] for line in path.read_text(encoding="utf-8").split(
                    "  projects.json: |-\n", 1
                )[1].splitlines())
            )
            self.assertEqual("ready", payload["projects"][1]["status"])
            self.assertEqual(
                "build1-mac-ledger-registered-v4",
                payload["projects"][1]["dispatch_profile"],
            )
            with self.assertRaisesRegex(driver.PermanentError, "catalog-collision"):
                driver.update_catalog(path, value, ready=False)

    def test_real_catalog_shape_is_preserved_when_project_is_appended(self):
        source = ROOT / "clusters/prod/infra/hermes-project-catalog.yaml"
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / source.name
            shutil.copyfile(source, path)
            before = path.read_text(encoding="utf-8")
            driver.update_catalog(path, request(), ready=False)
            after = path.read_text(encoding="utf-8")
            self.assertIn(before.split('  projects.json: |-\n', 1)[0], after)
            payload = json.loads(
                "\n".join(line[4:] for line in after.split(
                    "  projects.json: |-\n", 1
                )[1].splitlines())
            )
            self.assertEqual("mac-ledger", payload["projects"][-1]["project_id"])
            self.assertEqual("setup_required", payload["projects"][-1]["status"])

    def test_runtime_revision_and_golden_test_move_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            manifest = root / "clusters/prod/infra/hermes-agent.yaml"
            test = root / "tests/static/test_hermes_mission_deployment.py"
            manifest.parent.mkdir(parents=True)
            test.parent.mkdir(parents=True)
            manifest.write_text(
                'annotations:\n  hermes-agent/config-rev: "old"\n', encoding="utf-8"
            )
            test.write_text(
                'assert template["metadata"]["annotations"]["hermes-agent/config-rev"] == (\n'
                '    "old"\n)\n',
                encoding="utf-8",
            )
            driver.bump_runtime_revision(root, request(), ready=False)
            revision = "onboard-0123456789abcdef-setup"
            self.assertIn(revision, manifest.read_text(encoding="utf-8"))
            self.assertIn(revision, test.read_text(encoding="utf-8"))

    def test_tick_advances_one_checkpoint_and_permanent_failure_is_terminal(self):
        class Central:
            def __init__(self, value):
                self.value = value
                self.transitions = []
                self.invocations = []

            def pending(self):
                return self.value

            def advance(self, value, checkpoint, error_code=None):
                self.transitions.append((value["checkpoint"], checkpoint, error_code))
                return {**value, "checkpoint": checkpoint, "error_code": error_code}

            def record_invocation(self, value, invocation):
                self.invocations.append(invocation)
                history = {
                    "count": 1,
                    "first": invocation,
                    "last": invocation,
                    "chain_sha256": driver.flow_contract.canonical_sha256({
                        "previous": None, **invocation,
                    }),
                }
                return {**value, "invocations": history}

        class Successful(driver.Driver):
            def _systemd_invocation(self):
                return {
                    "unit": "hermes-project-onboarding.service",
                    "invocation_id": "1" * 32,
                }

            def ensure_repository(self, _request):
                return None

        central = Central(request())
        self.assertTrue(Successful(central, home=pathlib.Path.cwd()).tick())
        self.assertEqual([("requested", "repository_ready", None)], central.transitions)

        class Failed(driver.Driver):
            def _systemd_invocation(self):
                return {
                    "unit": "hermes-project-onboarding.service",
                    "invocation_id": "1" * 32,
                }

            def ensure_repository(self, _request):
                raise driver.PermanentError("repository-collision")

        central = Central(request())
        self.assertTrue(Failed(central, home=pathlib.Path.cwd()).tick())
        self.assertEqual([("requested", "failed", "repository-collision")], central.transitions)

    def test_manual_tick_stops_before_recording_or_external_work(self):
        class Central:
            def pending(self):
                return request()

            def record_invocation(self, *_args):
                raise AssertionError("manual tick reached Central mutation")

        with mock.patch.dict(
            os.environ,
            {"UAP_ONBOARDING_UNIT": "", "XDG_RUNTIME_DIR": ""},
        ):
            with self.assertRaisesRegex(
                driver.PermanentError, "onboarding-evidence-requires-systemd"
            ):
                driver.Driver(Central(), home=pathlib.Path.cwd()).tick()

    def test_disposable_uap_checkout_recovers_from_total_local_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            origin = temporary / "origin.git"
            seed = temporary / "seed"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "master", str(seed)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=seed, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=seed, check=True)
            (seed / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=seed, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=seed, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=seed, check=True)
            subprocess.run(["git", "push", "origin", "master"], cwd=seed, check=True, capture_output=True)
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=seed, check=True,
                text=True, capture_output=True,
            ).stdout.strip()
            original_remote = driver.UAP_REMOTE
            driver.UAP_REMOTE = str(origin)
            try:
                instance = driver.Driver(None, home=temporary / "home")
                checkout = temporary / "checkout"
                instance._checkout_merged_uap(checkout, sha)
                def remove_readonly(function, path, _error):
                    os.chmod(path, stat.S_IWRITE)
                    function(path)

                shutil.rmtree(checkout, onerror=remove_readonly)
                instance._checkout_merged_uap(checkout, sha)
                actual = subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=checkout, check=True,
                    text=True, capture_output=True,
                ).stdout.strip()
                self.assertEqual(sha, actual)
            finally:
                driver.UAP_REMOTE = original_remote

    def test_canary_requires_exact_identity_and_authoritative_completion(self):
        value = request(checkpoint="runtime_ready")

        class RecordingCentral(driver.CentralClient):
            def __init__(self):
                self.body = None

            def request(self, method, path, body=None):
                self.body = body
                return {"mission": body}

        recording = RecordingCentral()
        self.assertEqual("none", recording.accept_canary(value)["delivery_mode"])
        self.assertEqual("none", recording.body["delivery_mode"])

        class Central:
            def __init__(self, mission):
                self.value = mission

            def mission(self, _mission_id):
                return self.value

        complete = {
            "mission_id": driver.canary_mission_id(value),
            "goal": driver.canary_goal(value),
            "dispatch_profile": driver.dispatch_profile(value),
            "delivery_mode": "none",
            "status": "completed",
            "progress_percent": 100,
            "result": "merged and verified",
        }
        self.assertTrue(driver.Driver(Central(complete), home=pathlib.Path.cwd()).ensure_canary(value))
        with self.assertRaisesRegex(driver.PermanentError, "canary-mission-collision"):
            driver.Driver(
                Central({**complete, "dispatch_profile": "unexpected"}),
                home=pathlib.Path.cwd(),
            ).ensure_canary(value)
        with self.assertRaisesRegex(driver.PermanentError, "canary-mission-collision"):
            driver.Driver(
                Central({**complete, "delivery_mode": None}),
                home=pathlib.Path.cwd(),
            ).ensure_canary(value)

    def test_ready_checkpoint_writes_closed_onboarding_evidence(self):
        value = request(checkpoint="canary_passed")
        value["request_id"] = "project-onboarding-" + driver.hashlib.sha256(
            f"pavellizunov\0{value['project_id']}".encode("utf-8")
        ).hexdigest()[:32]
        invocation = {
            "unit": "hermes-project-onboarding.service",
            "invocation_id": "1" * 32,
        }
        value["invocations"] = {
            "count": 1,
            "first": invocation,
            "last": invocation,
            "chain_sha256": driver.flow_contract.canonical_sha256({
                "previous": None, **invocation,
            }),
        }

        class EvidenceDriver(driver.Driver):
            def _github_repository(self, _repository):
                return {"private": True, "default_branch": "main"}

            def _bootstrap_checkout(self, _request):
                return self.home / "bootstrap", "a" * 40

            def _uap_pr(self, branch):
                ready = branch.endswith("-ready")
                return {
                    "number": 20 if ready else 10,
                    "state": "MERGED",
                    "mergeCommit": {"oid": ("d" if ready else "c") * 40},
                    "mergeStateStatus": "CLEAN",
                    "headRefName": branch,
                    "commits": [{"oid": ("f" if ready else "e") * 40}],
                }

            def _live_project(self, _request):
                return {
                    key: item
                    for key, item in driver.catalog_entry(value, ready=True).items()
                    if key not in {"aliases", "dispatch_profile", "platforms"}
                }

            def _completion_evidence(self, _request):
                return {"sha256": "2" * 64}, "3" * 64

            def run(self, command, **_kwargs):
                if command[:3] == ["systemctl", "--user", "is-enabled"]:
                    return subprocess.CompletedProcess(command, 0, "enabled\n", "")
                if command[:3] == ["systemctl", "--user", "is-active"]:
                    return subprocess.CompletedProcess(command, 0, "active\n", "")
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            home = pathlib.Path(directory)
            profile = home / ".config/uap" / driver.profile_name(value)
            profile.parent.mkdir(parents=True)
            profile.write_text(
                json.dumps(driver.render_profile(value)), encoding="utf-8"
            )
            instance = EvidenceDriver(None, home=home)
            instance._write_onboarding_evidence(value)
            path = instance._request_root(value) / "onboarding-evidence.json"
            evidence = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                evidence,
                driver.flow_contract.validate_project_onboarding_evidence(evidence),
            )
            self.assertEqual(value["invocations"], evidence["driver"]["invocations"])
            self.assertEqual("2" * 64, evidence["canary"]["completion_evidence_sha256"])

    def test_uap_pr_query_uses_fields_supported_by_installed_gh(self):
        commands = []

        def runner(command, **_kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "[]\n", "")

        instance = driver.Driver(None, home=pathlib.Path.cwd(), runner=runner)
        self.assertIsNone(instance._uap_pr("codex/onboard-example-setup"))
        fields = commands[0][commands[0].index("--json") + 1]
        self.assertIn("commits", fields.split(","))
        self.assertNotIn("headRefOid", fields.split(","))

    def test_uap_pr_creation_reconciles_ambiguous_api_result(self):
        value = request(checkpoint="repository_ready")

        class RecordingDriver(driver.Driver):
            def __init__(self, home):
                super().__init__(None, home=home)
                self.commands = []
                self.pr_reads = 0

            def _uap_pr(self, _branch):
                self.pr_reads += 1
                if self.pr_reads == 1:
                    return None
                return {
                    "number": 42,
                    "state": "OPEN",
                    "mergeCommit": None,
                    "mergeStateStatus": "BLOCKED",
                    "headRefName": self._uap_branch(value, ready=False),
                }

            def _render_uap_change(self, _root, _request, *, ready):
                if ready:
                    raise AssertionError("unexpected ready path")
                return []

            def run(self, command, **_kwargs):
                self.commands.append(command)
                if command[:2] == ["git", "ls-remote"]:
                    return subprocess.CompletedProcess(command, 0, "a" * 40 + "\tref\n", "")
                if command[:4] == ["git", "remote", "get-url", "origin"]:
                    return subprocess.CompletedProcess(command, 0, driver.UAP_REMOTE + "\n", "")
                if command[:3] == ["git", "branch", "--show-current"]:
                    return subprocess.CompletedProcess(
                        command, 0, self._uap_branch(value, ready=False) + "\n", ""
                    )
                if command[:3] == ["git", "status", "--porcelain"]:
                    return subprocess.CompletedProcess(command, 0, "", "")
                if command[:3] == ["gh", "api", "--method"]:
                    return subprocess.CompletedProcess(command, 1, "", "transport failed")
                if command[:3] == ["gh", "pr", "merge"]:
                    return subprocess.CompletedProcess(command, 0, "", "")
                raise AssertionError(command)

        with tempfile.TemporaryDirectory() as directory:
            instance = RecordingDriver(pathlib.Path(directory))
            root = instance._request_root(value) / "uap-setup"
            root.mkdir(parents=True)
            self.assertIsNone(instance._ensure_uap_pr(value, ready=False))
        api = next(command for command in instance.commands if command[:2] == ["gh", "api"])
        self.assertIn(f"repos/{driver.UAP_REPOSITORY}/pulls", api)
        self.assertIn(f"head={instance._uap_branch(value, ready=False)}", api)
        self.assertFalse(any(command[:3] == ["gh", "pr", "create"] for command in instance.commands))

    def test_behind_uap_pr_updates_base_without_operator(self):
        value = request(checkpoint="repository_ready")

        class BehindDriver(driver.Driver):
            def __init__(self):
                super().__init__(None, home=pathlib.Path.cwd())
                self.commands = []

            def _uap_pr(self, branch):
                return {
                    "number": 42,
                    "state": "OPEN",
                    "mergeCommit": None,
                    "mergeStateStatus": "BEHIND",
                    "headRefName": branch,
                }

            def run(self, command, **_kwargs):
                self.commands.append(command)
                return subprocess.CompletedProcess(command, 0, "", "")

        instance = BehindDriver()
        self.assertIsNone(instance._ensure_uap_pr(value, ready=False))
        self.assertEqual(
            [
                "gh", "api", "--method", "PUT",
                f"repos/{driver.UAP_REPOSITORY}/pulls/42/update-branch",
            ],
            instance.commands[0],
        )
        self.assertFalse(any(command[:3] == ["gh", "pr", "merge"] for command in instance.commands))

    def test_standing_unit_is_bounded_and_receives_no_owner_key(self):
        service = (ROOT / "tools/swarm/systemd/hermes-project-onboarding.service").read_text(
            encoding="utf-8"
        )
        timer = (ROOT / "tools/swarm/systemd/hermes-project-onboarding.timer").read_text(
            encoding="utf-8"
        )
        self.assertIn("SuccessExitStatus=75", service)
        self.assertIn(
            "Environment=UAP_ONBOARDING_UNIT=hermes-project-onboarding.service",
            service,
        )
        self.assertIn("UnsetEnvironment=HERMES_MISSION_OWNER_KEY", service)
        self.assertIn("UMask=0077", service)
        self.assertIn("OnUnitActiveSec=1min", timer)
        self.assertIn("Persistent=true", timer)


if __name__ == "__main__":
    unittest.main()
