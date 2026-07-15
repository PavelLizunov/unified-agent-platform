#!/usr/bin/env python3
"""Static A6.4 gate for the generated mission runtime deployment."""

from __future__ import annotations

import importlib.util
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "tools/hermes-mission/render_configmap.py"
SPEC = importlib.util.spec_from_file_location("render_mission_configmap", GENERATOR)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def main() -> None:
    generated = ROOT / "clusters/prod/infra/hermes-mission-runtime.yaml"
    assert generated.read_text(encoding="utf-8") == module.render()

    deployment = (ROOT / "clusters/prod/infra/hermes-agent.yaml").read_text(encoding="utf-8")
    for fragment in (
        "name: hermes-mission-runtime",
        "name: mission-runtime",
        "--source-commit 7c1a029553d87c43ecff8a3821336bc95872213b",
        "HERMES_MISSION_PRODUCER_KEY",
        "cp /opt/hermes/hermes_cli/kanban_db.py /mission-runtime/root/hermes_cli/kanban_db.py",
        "cp /mission-runtime/root/hermes_cli/kanban_db.py /mission-runtime/kanban_db.py",
        "mountPath: /opt/hermes/hermes_cli/uap_missions.py",
        "mountPath: /opt/hermes/hermes_cli/commands.py",
        "mountPath: /opt/hermes/hermes_cli/kanban_db.py",
        "mountPath: /opt/hermes/gateway/run.py",
        "mountPath: /opt/hermes/gateway/platforms/api_server.py",
    ):
        assert fragment in deployment, fragment

    resources = (ROOT / "clusters/prod/infra/kustomization.yaml").read_text(encoding="utf-8")
    assert "hermes-mission-runtime.yaml" in resources
    assert "hermes-agent-mission.sops.yaml" in resources
    print("hermes-mission-deployment-ok")


if __name__ == "__main__":
    main()
