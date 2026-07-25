#!/usr/bin/env python3
"""Static A6.4 gate for the generated mission runtime deployment."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "tools/hermes-mission/render_configmap.py"
SPEC = importlib.util.spec_from_file_location("render_mission_configmap", GENERATOR)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def check(condition: bool, message: str = "mission-deployment check failed") -> None:
    """Raise AssertionError when *condition* is false.  Unlike bare ``assert``,
    this is never stripped by ``python -O``."""
    if not condition:
        raise AssertionError(message)


def main() -> None:
    generated = ROOT / "clusters/prod/infra/hermes-mission-runtime.yaml"
    check(generated.read_text(encoding="utf-8") == module.render())

    deployment = (ROOT / "clusters/prod/infra/hermes-agent.yaml").read_text(encoding="utf-8")
    for fragment in (
        "name: hermes-mission-runtime",
        "name: mission-runtime",
        "--source-commit 3ef6bbd201263d354fd83ec55b3c306ded2eb72a",
        "HERMES_MISSION_PRODUCER_KEY",
        "HERMES_MISSION_OWNER_KEY",
        "mountPath: /opt/hermes/hermes_cli/uap_missions.py",
        "mountPath: /opt/hermes/hermes_cli/commands.py",
        "mountPath: /opt/hermes/hermes_cli/kanban.py",
        "mountPath: /opt/hermes/gateway/run.py",
        "mountPath: /opt/hermes/gateway/platforms/api_server.py",
        "mountPath: /opt/hermes/plugins/platforms/telegram/adapter.py",
    ):
        check(fragment in deployment, fragment)

    manifest = next(
        document for document in yaml.safe_load_all(deployment)
        if document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("name") == "hermes-agent"
    )
    template = manifest["spec"]["template"]
    check(template["metadata"]["annotations"]["hermes-agent/config-rev"] == (
        "v99-final-audit-guards"
    ))
    research_mount = next(
        mount for mount in template["spec"]["containers"][0]["volumeMounts"]
        if mount["name"] == "research-session"
    )
    web_mounts = [
        m for m in template["spec"]["containers"][0]["volumeMounts"]
        if "index-DE8KfxAS" in m.get("mountPath", "")
    ]
    check(len(web_mounts) == 1, "web bundle volumeMount missing")
    web_mount = web_mounts[0]
    check(research_mount == {
        "name": "research-session",
        "mountPath": "/opt/data/mcp/research_session.py",
        "subPath": "research_session.py",
        "readOnly": True,
    })
    bootstrap = next(
        container for container in template["spec"]["initContainers"]
        if container["name"] == "bootstrap"
    )
    bootstrap_script = "\n".join(bootstrap["args"])
    # Couple the bootstrap cp that patches the v0.19 web asset to the subPath
    # mount that serves it: exactly one cp writes the asset, its source must be
    # the mounted asset path, and its destination basename must equal the mount
    # subPath (one occurrence each, exact equality).
    web_cp = [
        line.split()
        for line in bootstrap_script.splitlines()
        if line.strip().startswith("cp ") and "index-DE8KfxAS.js" in line
    ]
    check(len(web_cp) == 1, "expected exactly one web asset cp in bootstrap")
    cp_src, cp_dst = web_cp[0][1], web_cp[0][2]
    cp_dst_basename = cp_dst.rsplit("/", 1)[-1]
    check(
        web_mount["mountPath"] == cp_src,
        f"web mount mountPath {web_mount['mountPath']} != bootstrap cp source {cp_src}",
    )
    check(
        web_mount["subPath"] == cp_dst_basename,
        f"web mount subPath {web_mount['subPath']} != cp destination basename "
        f"{cp_dst_basename} (bootstrap cp -> {cp_dst})",
    )
    managed_config = (ROOT / "clusters/prod/infra/hermes-agent-config.yaml").read_text(
        encoding="utf-8"
    )
    check("UAP_STT_REMOTE_URL=http://192.168.0.203:8090/v1/audio/transcriptions"
        in managed_config)
    check("HERMES_MISSION_TELEGRAM_CHAT_ID=-1004377555987" in managed_config)
    check("HERMES_MISSION_TELEGRAM_THREAD_ID=2" in managed_config)
    check("HERMES_MISSION_WORKSPACE_URL=http://100.85.56.31:3000" in managed_config)
    check((
        "cp /opt/hermes/hermes_cli/kanban.py "
        "/mission-runtime/root/hermes_cli/kanban.py"
    ) in bootstrap_script)
    check((
        "cp /mission-runtime/root/hermes_cli/kanban.py "
        "/mission-runtime/kanban.py"
    ) in bootstrap_script)
    check((
        "cp /mission-runtime/root/hermes_cli/uap_media.py "
        "/mission-runtime/uap_media.py"
    ) in bootstrap_script)
    check((
        "cp /opt/hermes/plugins/platforms/telegram/adapter.py "
        "/mission-runtime/root/plugins/platforms/telegram/adapter.py"
    ) in bootstrap_script)
    check((
        "cp /opt/hermes/gateway/delivery_ledger.py "
        "/mission-runtime/root/gateway/delivery_ledger.py"
    ) in bootstrap_script)
    check((
        "cp /mission-runtime/root/plugins/platforms/telegram/adapter.py "
        "/mission-runtime/telegram_adapter.py"
    ) in bootstrap_script)
    check((
        "cp /opt/hermes/hermes_cli/kanban_db.py "
        "/mission-runtime/root/hermes_cli/kanban_db.py"
    ) in bootstrap_script)
    check((
        "cp /mission-runtime/root/hermes_cli/kanban_db.py "
        "/mission-runtime/kanban_db.py"
    ) in bootstrap_script)
    check((
        "cp /opt/hermes/hermes_cli/main.py "
        "/mission-runtime/root/hermes_cli/main.py"
    ) in bootstrap_script)
    check((
        "cp /mission-runtime/root/hermes_cli/main.py "
        "/mission-runtime/main.py"
    ) in bootstrap_script)
    for pinned in (
        "f719d70812344f4d0fb8c11c0887b190501a7465",
        "7d69952fb431a8d7800ed9910dc61fea37d8406bfe96d10bf24c8bd4b7c68623",
        "5e150c7862748d33dc2f559a38274bcb46d06ba63f8f5d1247f8196569e02797",
        "736f366beb8093eebd1a2ea694de48b6f87a34c6e5eb332384ba96fe3f4fceb3",
        "cp /mission-overlay/local_stt.py /stt-runtime/local_stt.py",
    ):
        check(pinned in bootstrap_script, pinned)
    gateway = next(
        container for container in template["spec"]["containers"]
        if container["name"] == "gateway"
    )
    gateway_env = {entry["name"]: entry for entry in gateway["env"]}
    check("HERMES_MISSION_INTAKE_ROUTES" not in gateway_env)
    check(gateway_env["HERMES_OWNER_COMMANDS"]["value"] == (
        "projects,mission,status,help,stop"
    ))
    check(gateway_env["HERMES_MISSION_PROJECTS"] == {
        "name": "HERMES_MISSION_PROJECTS",
        "valueFrom": {
            "configMapKeyRef": {
                "name": "hermes-project-catalog",
                "key": "projects.json",
            }
        },
    })
    check(gateway_env["HERMES_MISSION_MEDIA_TOPICS"] == {
        "name": "HERMES_MISSION_MEDIA_TOPICS",
        "value": '[{"chat_id":"-1004377555987","thread_id":"3"}]',
    })
    check(gateway_env["TELEGRAM_REQUIRE_MENTION"] == {
        "name": "TELEGRAM_REQUIRE_MENTION",
        "value": "true",
    })
    check(gateway_env["TELEGRAM_FREE_RESPONSE_TOPICS"] == {
        "name": "TELEGRAM_FREE_RESPONSE_TOPICS",
        "value": "-1004377555987:2,-1004377555987:3",
    })
    check(gateway_env["TELEGRAM_HOME_CHANNEL"] == {
        "name": "TELEGRAM_HOME_CHANNEL",
        "value": "-1004377555987",
    })
    check(gateway_env["TELEGRAM_HOME_CHANNEL_THREAD_ID"] == {
        "name": "TELEGRAM_HOME_CHANNEL_THREAD_ID",
        "value": "2",
    })
    catalog_manifest = yaml.safe_load(
        (ROOT / "clusters/prod/infra/hermes-project-catalog.yaml").read_text(
            encoding="utf-8"
        )
    )
    check(catalog_manifest["kind"] == "ConfigMap")
    projects = json.loads(catalog_manifest["data"]["projects.json"])
    check(projects["schema_version"] == 2)
    check(len({project["project_id"] for project in projects["projects"]}) == len(
        projects["projects"]
    ))
    ready = {
        project["project_id"]: (
            project["repository"],
            project["dispatch_profile"],
            project["delivery_mode"],
            set(project["platforms"]),
        )
        for project in projects["projects"] if project["status"] == "ready"
    }
    expected_ready = {
        "uap": (
            "PavelLizunov/unified-agent-platform",
            "build1-uap-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
        "gs-ninitux": (
            "PavelLizunov/gs-ninitux",
            "build1-gs-ninitux-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
        "flow-ledger": (
            "PavelLizunov/hermes-flow-v2-pilot",
            "build1-flow-pilot-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
        "spark-runner": (
            "PavelLizunov/spark-runner",
            "build1-spark-runner-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
        "suflyor": (
            "PavelLizunov/suflyor",
            "build1-suflyor-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
        "subfleet": (
            "PavelLizunov/subfleet",
            "build1-subfleet-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
        "slipstream-rust": (
            "PavelLizunov/slipstream-rust",
            "build1-slipstream-rust-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
        "ninitux-landing": (
            "PavelLizunov/ninitux-landing",
            "build1-ninitux-landing-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
        "vpnctl": (
            "PavelLizunov/vpnctl",
            "build1-vpnctl-registered-v4",
            "deploy",
            {"workspace", "telegram"},
        ),
        "vpnrouter": (
            "PavelLizunov/VPNRouter",
            "build1-vpnrouter-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
        "vpnrouter-gateway": (
            "PavelLizunov/vpnrouter-gateway",
            "build1-vpnrouter-gateway-registered-v4",
            "none",
            {"workspace", "telegram"},
        ),
    }
    for project_id, expected in expected_ready.items():
        check(ready[project_id] == expected)
    installed_profiles = {}
    for path in (ROOT / "tools/swarm/profiles").glob("delivery-*-registered-v4.json"):
        profile = json.loads(path.read_text(encoding="utf-8"))
        installed_profiles[profile["dispatch_profile"]] = profile
    for project in projects["projects"]:
        if project["status"] != "ready":
            continue
        profile = installed_profiles[project["dispatch_profile"]]
        check(profile["repo"] == project["repository"])
        check(profile["delivery_mode"] == project["delivery_mode"])
    check(sum(project["status"] == "setup_required" for project in projects["projects"]) >= 12)
    check(sum(project["status"] == "read_only" for project in projects["projects"]) == 3)
    check(sum(project["status"] == "archived" for project in projects["projects"]) == 7)
    check(next(
        project for project in projects["projects"] if project["project_id"] == "vpnrouter"
    )["test_targets"] == [
        "uap-build-1", "github-linux", "github-windows", "windows-brat"
    ])
    boosty = next(
        project for project in projects["projects"] if project["project_id"] == "boosty-api-rs"
    )
    check(boosty["status"] == "read_only")
    check(boosty["dispatch_profile"] is None)
    check("boosty" not in boosty["aliases"])
    check("boosty" in next(
        project for project in projects["projects"] if project["project_id"] == "vpnctl"
    )["aliases"])
    check(all(
        next(project for project in projects["projects"] if project["project_id"] == project_id)[
            "category"
        ] == "active-maintained"
        for project_id in ("vpnrouter", "suflyor")
    ))
    check(next(
        project for project in projects["projects"] if project["project_id"] == "wgturn-core"
    )["status"] == "setup_required")
    local_llm_lab = next(
        project for project in projects["projects"]
        if project["project_id"] == "local-llm-lab"
    )
    check(local_llm_lab == {
        "project_id": "local-llm-lab",
        "label": "Local LLM Evaluation Lab",
        "repository": "PavelLizunov/local-llm-evaluation-lab",
        "summary": (
            "Каталог тестов LLM, исследовательских сценариев и результатов "
            "для конкретных моделей."
        ),
        "aliases": ["llm lab", "model lab", "лаборатория моделей"],
        "dispatch_profile": None,
        "delivery_mode": "none",
        "platforms": ["workspace", "telegram"],
        "category": "research",
        "status": "setup_required",
        "test_targets": ["desktop-m922ij2", "pavels-mac-mini"],
    })
    staged_profile = installed_profiles["build1-local-llm-lab-registered-v4"]
    check(staged_profile["repo"] == local_llm_lab["repository"])
    check(staged_profile["delivery_mode"] == local_llm_lab["delivery_mode"])
    check(local_llm_lab["dispatch_profile"] is None)
    runtime_spec = importlib.util.spec_from_file_location(
        "uap_mission_catalog_runtime", ROOT / "tools/hermes-mission/runtime.py"
    )
    check(runtime_spec and runtime_spec.loader)
    runtime = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(runtime)
    previous_catalog = os.environ.get("HERMES_MISSION_PROJECTS")
    try:
        os.environ["HERMES_MISSION_PROJECTS"] = catalog_manifest["data"]["projects.json"]
        check(len(runtime.public_intake_projects("workspace")) == len([
            project for project in projects["projects"]
            if "workspace" in project["platforms"]
        ]))
        check(len([
            project for project in runtime.public_intake_projects("telegram")
            if project["status"] == "ready"
        ]) == len([
            project for project in projects["projects"]
            if "telegram" in project["platforms"] and project["status"] == "ready"
        ]))
    finally:
        if previous_catalog is None:
            os.environ.pop("HERMES_MISSION_PROJECTS", None)
        else:
            os.environ["HERMES_MISSION_PROJECTS"] = previous_catalog
    check({
        "name": "HERMES_MISSION_OWNER_KEY",
        "valueFrom": {
            "secretKeyRef": {"name": "hermes-agent-owner", "key": "owner-key"}
        },
    } in gateway["env"])
    check({
        "name": "mission-runtime",
        "mountPath": "/opt/hermes/hermes_cli/kanban.py",
        "subPath": "kanban.py",
        "readOnly": True,
    } in gateway["volumeMounts"])
    check({
        "name": "mission-runtime",
        "mountPath": "/opt/hermes/hermes_cli/kanban_db.py",
        "subPath": "kanban_db.py",
        "readOnly": True,
    } in gateway["volumeMounts"])
    check({
        "name": "mission-runtime",
        "mountPath": "/opt/hermes/hermes_cli/main.py",
        "subPath": "main.py",
        "readOnly": True,
    } in gateway["volumeMounts"])
    check({
        "name": "mission-runtime",
        "mountPath": "/opt/hermes/plugins/platforms/telegram/adapter.py",
        "subPath": "telegram_adapter.py",
        "readOnly": True,
    } in gateway["volumeMounts"])
    mission_runtime = next(
        volume for volume in template["spec"]["volumes"]
        if volume["name"] == "mission-runtime"
    )
    check(mission_runtime == {"name": "mission-runtime", "emptyDir": {}})
    check({
        "name": "stt-runtime",
        "mountPath": "/opt/uap-stt",
        "readOnly": True,
    } in gateway["volumeMounts"])
    check(next(
        volume for volume in template["spec"]["volumes"]
        if volume["name"] == "stt-runtime"
    ) == {"name": "stt-runtime", "emptyDir": {}})

    config_map = yaml.safe_load(
        (ROOT / "clusters/prod/infra/hermes-agent-config.yaml").read_text(encoding="utf-8")
    )
    managed = yaml.safe_load(config_map["data"]["managed-config"])
    check(managed["stt"] == {
        "enabled": True,
        "provider": "uap_local",
        "providers": {
            "uap_local": {
                "type": "command",
                "command": (
                    "env UAP_STT_REMOTE_URL=http://192.168.0.203:8090/v1/audio/transcriptions "
                    "PYTHONPATH=/opt/uap-stt/python "
                    "TRANSCRIBE_LIBRARY=/opt/uap-stt/native/libtranscribe.so "
                    "LD_LIBRARY_PATH=/opt/uap-stt/native "
                    "/opt/hermes/.venv/bin/python /opt/uap-stt/local_stt.py "
                    "{input_path} {output_path} --model {model}"
                ),
                "model": "/opt/data/.cache/uap-stt/gigaam-v3-e2e-rnnt-Q4_K_M.gguf",
                "language": "ru",
                "format": "txt",
                "timeout": 90,
            }
        },
    })

    resources = (ROOT / "clusters/prod/infra/kustomization.yaml").read_text(encoding="utf-8")
    check("hermes-mission-runtime.yaml" in resources)
    check("hermes-project-catalog.yaml" in resources)
    check("hermes-agent-mission.sops.yaml" in resources)
    check("hermes-agent-owner.sops.yaml" in resources)

    owner_secret = yaml.safe_load(
        (ROOT / "clusters/prod/infra/hermes-agent-owner.sops.yaml").read_text(
            encoding="utf-8"
        )
    )
    check(owner_secret["apiVersion"] == "v1")
    check(owner_secret["kind"] == "Secret")
    check(owner_secret["metadata"] == {
        "name": "hermes-agent-owner",
        "namespace": "uap-system",
    })
    check(set(owner_secret["data"]) == {"owner-key"})
    check(owner_secret["data"]["owner-key"].startswith("ENC[AES256_GCM"))
    check(isinstance(owner_secret.get("sops"), dict))
    print("hermes-mission-deployment-ok")


if __name__ == "__main__":
    main()
