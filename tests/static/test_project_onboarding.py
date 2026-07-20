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
        "created_at": "2026-07-20T12:00:00.000Z",
        "updated_at": "2026-07-20T12:00:00.000Z",
        "progress_percent": 0,
        "error_code": None,
    }


class ProjectOnboardingTests(unittest.TestCase):
    def test_presets_are_dependency_free_and_require_macos_ci(self):
        expected = {
            "rust": "cargo test --all-targets",
            "go": "go test ./...",
            "python": "python3 -m unittest discover -s tests",
            "web": "node --test",
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
                for relative, content in driver.bootstrap_files(request(preset)).items():
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8", newline="\n")
                result = subprocess.run(
                    command, cwd=root, text=True, capture_output=True, timeout=120,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

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

            def pending(self):
                return self.value

            def advance(self, value, checkpoint, error_code=None):
                self.transitions.append((value["checkpoint"], checkpoint, error_code))
                return {**value, "checkpoint": checkpoint, "error_code": error_code}

        class Successful(driver.Driver):
            def ensure_repository(self, _request):
                return None

        central = Central(request())
        self.assertTrue(Successful(central, home=pathlib.Path.cwd()).tick())
        self.assertEqual([("requested", "repository_ready", None)], central.transitions)

        class Failed(driver.Driver):
            def ensure_repository(self, _request):
                raise driver.PermanentError("repository-collision")

        central = Central(request())
        self.assertTrue(Failed(central, home=pathlib.Path.cwd()).tick())
        self.assertEqual([("requested", "failed", "repository-collision")], central.transitions)

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

        class Central:
            def __init__(self, mission):
                self.value = mission

            def mission(self, _mission_id):
                return self.value

        complete = {
            "mission_id": driver.canary_mission_id(value),
            "goal": driver.canary_goal(value),
            "dispatch_profile": driver.dispatch_profile(value),
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

    def test_standing_unit_is_bounded_and_receives_no_owner_key(self):
        service = (ROOT / "tools/swarm/systemd/hermes-project-onboarding.service").read_text(
            encoding="utf-8"
        )
        timer = (ROOT / "tools/swarm/systemd/hermes-project-onboarding.timer").read_text(
            encoding="utf-8"
        )
        self.assertIn("SuccessExitStatus=75", service)
        self.assertIn("UnsetEnvironment=HERMES_MISSION_OWNER_KEY", service)
        self.assertIn("UMask=0077", service)
        self.assertIn("OnUnitActiveSec=1min", timer)
        self.assertIn("Persistent=true", timer)


if __name__ == "__main__":
    unittest.main()
