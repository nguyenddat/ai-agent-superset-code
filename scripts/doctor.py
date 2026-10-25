"""Check the local tools and Docker setup the Semantic Layer workflow depends on.

Usage: uv run scripts/doctor.py
"""

import argparse
import sys
import urllib.error
import urllib.request

from _common import FRONTEND_DIR, SUPERSET_URL, run, step


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    problems = []

    def report(ok: bool, label: str, detail: str = "", hint: str = "") -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {label}{f': {detail}' if detail else ''}")
        if not ok:
            problems.append(f"{label}: {hint or detail}")

    step("Local tools")
    for tool in ("uv", "node", "npm", "docker"):
        result = run([tool, "--version"], check=False, capture=True)
        version = (result.stdout or result.stderr).strip().splitlines()
        report(
            result.returncode == 0, tool, version[0] if version else "not found", f"install {tool} or add it to PATH"
        )
    report((FRONTEND_DIR / "node_modules").is_dir(), "frontend node_modules", hint=f"run `npm ci` in {FRONTEND_DIR}")

    step("Docker engine")
    kernel = run(["docker", "info", "--format", "{{.KernelVersion}}"], check=False, capture=True).stdout.strip()
    report(
        bool(kernel) and "microsoft-standard-WSL2" not in kernel,
        "Docker Desktop engine",
        kernel or "Docker is not running",
        "the repo lives on removable drive F:, which only the Hyper-V engine can share; "
        'set "WslEngineEnabled": false in %APPDATA%\\Docker\\settings-store.json',
    )

    step("Stack")
    services = run(["docker", "compose", "ps", "--status", "running", "--services"], check=False, capture=True)
    running = services.stdout.split()
    for service in ("superset-db", "warehouse-db", "superset"):
        report(
            service in running,
            f"service {service}",
            "running" if service in running else "not running",
            "run `docker compose up -d`",
        )
    try:
        with urllib.request.urlopen(f"{SUPERSET_URL}/health", timeout=5) as response:
            report(response.status == 200, "Superset /health", f"{SUPERSET_URL} -> {response.status}")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
        report(False, "Superset /health", f"{SUPERSET_URL} -> {error}", "check `uv run scripts/logs.py`")

    step("Summary")
    if problems:
        print("\n".join(f"- {problem}" for problem in problems))
        sys.exit(1)
    print("Environment looks good.")


if __name__ == "__main__":
    main()
