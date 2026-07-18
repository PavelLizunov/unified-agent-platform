#!/usr/bin/env python3
"""Static A6.4 gate for the generated mission runtime deployment."""

from __future__ import annotations

import importlib.util
import pathlib

import yaml


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
        "HERMES_MISSION_OWNER_KEY",
        "mountPath: /opt/hermes/hermes_cli/uap_missions.py",
        "mountPath: /opt/hermes/hermes_cli/commands.py",
        "mountPath: /opt/hermes/hermes_cli/kanban.py",
        "mountPath: /opt/hermes/gateway/run.py",
        "mountPath: /opt/hermes/gateway/platforms/api_server.py",
    ):
        assert fragment in deployment, fragment

    manifest = next(
        document for document in yaml.safe_load_all(deployment)
        if document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("name") == "hermes-agent"
    )
    template = manifest["spec"]["template"]
    assert template["metadata"]["annotations"]["hermes-agent/config-rev"] == (
        "v46-ordinary-owner-answer"
    )
    bootstrap = next(
        container for container in template["spec"]["initContainers"]
        if container["name"] == "bootstrap"
    )
    bootstrap_script = "\n".join(bootstrap["args"])
    assert (
        "cp /opt/hermes/hermes_cli/kanban.py "
        "/mission-runtime/root/hermes_cli/kanban.py"
    ) in bootstrap_script
    assert (
        "cp /mission-runtime/root/hermes_cli/kanban.py "
        "/mission-runtime/kanban.py"
    ) in bootstrap_script
    assert (
        "cp /opt/hermes/hermes_cli/kanban_db.py "
        "/mission-runtime/root/hermes_cli/kanban_db.py"
    ) in bootstrap_script
    assert (
        "cp /mission-runtime/root/hermes_cli/kanban_db.py "
        "/mission-runtime/kanban_db.py"
    ) in bootstrap_script
    assert (
        "cp /opt/hermes/hermes_cli/main.py "
        "/mission-runtime/root/hermes_cli/main.py"
    ) in bootstrap_script
    assert (
        "cp /mission-runtime/root/hermes_cli/main.py "
        "/mission-runtime/main.py"
    ) in bootstrap_script
    gateway = next(
        container for container in template["spec"]["containers"]
        if container["name"] == "gateway"
    )
    gateway_env = {entry["name"]: entry for entry in gateway["env"]}
    assert gateway_env["HERMES_MISSION_INTAKE_ROUTES"]["value"] == (
        '{"workspace":{"dispatch_profile":"build1-flow-pilot-registered-v4",'
        '"delivery_mode":"none"},"telegram":{"dispatch_profile":'
        '"build1-flow-pilot-registered-v4","delivery_mode":"none"}}'
    )
    assert {
        "name": "HERMES_MISSION_OWNER_KEY",
        "valueFrom": {
            "secretKeyRef": {"name": "hermes-agent-owner", "key": "owner-key"}
        },
    } in gateway["env"]
    assert {
        "name": "mission-runtime",
        "mountPath": "/opt/hermes/hermes_cli/kanban.py",
        "subPath": "kanban.py",
        "readOnly": True,
    } in gateway["volumeMounts"]
    assert {
        "name": "mission-runtime",
        "mountPath": "/opt/hermes/hermes_cli/kanban_db.py",
        "subPath": "kanban_db.py",
        "readOnly": True,
    } in gateway["volumeMounts"]
    assert {
        "name": "mission-runtime",
        "mountPath": "/opt/hermes/hermes_cli/main.py",
        "subPath": "main.py",
        "readOnly": True,
    } in gateway["volumeMounts"]
    mission_runtime = next(
        volume for volume in template["spec"]["volumes"]
        if volume["name"] == "mission-runtime"
    )
    assert mission_runtime == {"name": "mission-runtime", "emptyDir": {}}

    resources = (ROOT / "clusters/prod/infra/kustomization.yaml").read_text(encoding="utf-8")
    assert "hermes-mission-runtime.yaml" in resources
    assert "hermes-agent-mission.sops.yaml" in resources
    assert "hermes-agent-owner.sops.yaml" in resources

    owner_secret = yaml.safe_load(
        (ROOT / "clusters/prod/infra/hermes-agent-owner.sops.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert owner_secret["apiVersion"] == "v1"
    assert owner_secret["kind"] == "Secret"
    assert owner_secret["metadata"] == {
        "name": "hermes-agent-owner",
        "namespace": "uap-system",
    }
    assert set(owner_secret["data"]) == {"owner-key"}
    assert owner_secret["data"]["owner-key"].startswith("ENC[AES256_GCM")
    assert isinstance(owner_secret.get("sops"), dict)
    print("hermes-mission-deployment-ok")


if __name__ == "__main__":
    main()
