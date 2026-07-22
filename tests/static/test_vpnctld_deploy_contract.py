#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "infra" / "ops" / "uap-deploy-vpnctld.sh"
DISPATCH = ROOT / "infra" / "ops" / "uap-deploy-vpnctld-dispatch.sh"
INSTALLER = ROOT / "infra" / "ops" / "uap-install-vpnctld.sh"


class VpnctldDeployContractTests(unittest.TestCase):
    def test_shell_contracts_parse_and_fail_closed_without_arguments(self):
        for path in (WRAPPER, DISPATCH, INSTALLER):
            with self.subTest(path=path.name):
                syntax = subprocess.run(
                    ["wsl", "sh", "-n", path.relative_to(ROOT).as_posix()],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, syntax.returncode, syntax.stderr)
                rejected = subprocess.run(
                    ["wsl", "sh", path.relative_to(ROOT).as_posix()],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(0, rejected.returncode)

    def test_protocol_is_fixed_to_exact_revision_target_and_installed_payload(self):
        wrapper = WRAPPER.read_text(encoding="utf-8")
        dispatch = DISPATCH.read_text(encoding="utf-8")
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("/home/uap/worktrees/vpnctl-registered-v4/verify-*", wrapper)
        self.assertIn("uapdeploy@vpnctld", wrapper)
        self.assertIn("StrictHostKeyChecking=yes", wrapper)
        self.assertIn("set -f", dispatch)
        self.assertIn("INCOMING=/var/lib/uapdeploy/incoming", dispatch)
        self.assertIn("ARCHIVE=$INCOMING/$REVISION.tar", dispatch)
        self.assertIn("/usr/local/sbin/uap-install-vpnctld", dispatch)
        self.assertIn("flock -x 9", installer)
        self.assertIn("installed_artifact_sha", installer)
        self.assertIn("tar --sort=name", installer)
        self.assertIn("rollback", installer)
        self.assertIn("http://127.0.0.1:18402/api/v1/health", installer)


if __name__ == "__main__":
    unittest.main()
