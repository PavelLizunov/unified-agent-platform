#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "infra" / "ops" / "uap-deploy-vpnctld.sh"
DISPATCH = ROOT / "infra" / "ops" / "uap-deploy-vpnctld-dispatch.sh"
INSTALLER = ROOT / "infra" / "ops" / "uap-install-vpnctld.sh"


class VpnctldDeployContractTests(unittest.TestCase):
    def test_shell_contracts_parse_and_fail_closed_without_arguments(self):
        shell = ["wsl", "sh"] if os.name == "nt" else ["sh"]
        for path in (WRAPPER, DISPATCH, INSTALLER):
            with self.subTest(path=path.name):
                syntax = subprocess.run(
                    [*shell, "-n", path.relative_to(ROOT).as_posix()],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, syntax.returncode, syntax.stderr)
                rejected = subprocess.run(
                    [*shell, path.relative_to(ROOT).as_posix()],
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
        self.assertIn("restore_backup", installer)
        self.assertIn("systemctl stop vpnctld", installer)
        self.assertIn("mv -f \"$TEMP_BINARY\" /opt/vpnctl/vpnctld", installer)
        self.assertIn("--retry-connrefused", installer)
        self.assertIn("rollback verification failed", installer)
        self.assertIn("http://127.0.0.1:18402/api/v1/health", installer)
        activation = installer.index('install_binary "$NEW_BIN"')
        self.assertLess(installer.rindex("systemctl stop vpnctld", 0, activation), activation)
        restore = installer.index("restore_backup()")
        self.assertLess(
            installer.index("systemctl stop vpnctld", restore),
            installer.index('install_binary "$BACKUP/vpnctld"', restore),
        )


if __name__ == "__main__":
    unittest.main()
