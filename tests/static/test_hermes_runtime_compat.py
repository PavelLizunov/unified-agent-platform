"""Mechanism test for ADR-027's pinned Hermes compatibility patch."""

import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "clusters/prod/infra/hermes-agent-config.yaml"


def main() -> None:
    import yaml

    script = yaml.safe_load(PATCH.read_text(encoding="utf-8"))["data"]["runtime-compat.py"]
    failure = '    if file_mutation_result_landed(tool_name, result):\n        return False, ""\n'
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        (target / "display.py").write_text(failure + "\n    data = safe_json_loads(result)\n")
        (target / "tool_guardrails.py").write_text(failure + '\n    if tool_name == "terminal":\n')
        (target / "dashboard_auth_middleware.py").write_text(
            "    provider = providers[0]\n    prefix = prefix_from_request(request)\n"
        )
        script_path = target / "patch.py"
        script_path.write_text(script)

        subprocess.run([sys.executable, str(script_path), str(target)], check=True)
        subprocess.run([sys.executable, str(script_path), str(target)], check=True)

        assert 'tool_name == "exec_command"' in (target / "display.py").read_text()
        assert 'tool_name == "exec_command"' in (target / "tool_guardrails.py").read_text()
        assert 'getattr(provider, "supports_password", False)' in (
            target / "dashboard_auth_middleware.py"
        ).read_text()


if __name__ == "__main__":
    import sys

    main()
