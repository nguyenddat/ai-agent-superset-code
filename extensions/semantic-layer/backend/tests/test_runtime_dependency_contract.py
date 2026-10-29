import json
import shlex
from pathlib import Path

import tomllib

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPOSITORY_ROOT / "extensions" / "semantic-layer" / "backend"


def _docker_run_command_arguments(dockerfile: str, command_prefix: str) -> list[str]:
    """Return shell arguments for the uniquely targeted continued Docker RUN command."""
    lines = dockerfile.splitlines()
    command_lines: list[str] = []

    for index, line in enumerate(lines):
        if not line.startswith(command_prefix):
            continue

        command_lines = [line.removeprefix("RUN ").rstrip().removesuffix("\\")]
        current_index = index
        while lines[current_index].rstrip().endswith("\\"):
            current_index += 1
            command_lines.append(lines[current_index].strip().removesuffix("\\"))
        break

    assert command_lines, f"Dockerfile is missing {command_prefix!r}"
    return shlex.split(" ".join(command_lines))


def test_sqlglot_runtime_dependency_contract() -> None:
    project = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads((BACKEND_ROOT / "uv.lock").read_text(encoding="utf-8"))
    dockerfile = (REPOSITORY_ROOT / "simulation" / "superset" / "Dockerfile").read_text(encoding="utf-8")

    assert project["requires-python"] == ">=3.10,<3.11"
    assert "sqlglot==28.10.1" in project["dependencies"]
    # uv canonicalizes the project's Python-3.10-only range in the lockfile.
    assert lock["requires-python"] == "==3.10.*"
    assert any(package["name"] == "sqlglot" and package["version"] == "28.10.1" for package in lock["package"])
    runtime_install = _docker_run_command_arguments(
        dockerfile, "RUN uv pip install --python /app/.venv/bin/python"
    )
    assert runtime_install[:4] == ["uv", "pip", "install", "--python"]
    assert runtime_install[4] == "/app/.venv/bin/python"
    sqlglot_argument_index = runtime_install.index("sqlglot==28.10.1")
    assert not {"&&", "||", ";", "|"}.intersection(runtime_install[5:sqlglot_argument_index])


def test_extension_manifest_does_not_vendor_sqlglot() -> None:
    manifest_path = REPOSITORY_ROOT / "extensions" / "semantic-layer" / "extension.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "sqlglot" not in manifest.get("dependencies", [])
