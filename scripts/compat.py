"""Check the Semantic Layer source against the real Superset runtime in the running container.

Usage: uv run scripts/compat.py

The local pytest suite runs on Python 3.12 with stubbed Superset modules, so it cannot see API drift in Superset
6.1 or syntax that Python 3.10 rejects. This script:

1. compares the backend files inside the host bundle with the source tree, to flag a stale bundle;
2. compares the deployed bundle in the extensions volume with the host bundle;
3. copies backend/src into the Superset container, compiles every module with the container's Python 3.10, and
   imports every module inside a Superset app context, so each `from superset... import` resolves against
   the real Superset 6.1 code.
"""

import argparse
import zipfile

from _common import (
    BACKEND_SRC,
    BUNDLE_PATH,
    CONTAINER_BUNDLE_PATH,
    SUPERSET_SERVICE,
    compose,
    container_sha256,
    fail,
    require_superset_running,
    sha256_file,
    step,
)

CONTAINER_SRC = "/tmp/semantic-layer-compat"
PACKAGE = "text_to_bi.superset_semantic_layer"
REPORT_PREFIXES = ("Python ", "Compiled ", "Imported ", "PROBLEM ", "    ")

CONTAINER_SCRIPT = r"""
import importlib
import os
import sys
import traceback
from pathlib import Path

SRC = Path(sys.argv[1])
PACKAGE = sys.argv[2]
problems = []

print(f"Python {sys.version.split()[0]}")
files = sorted(
    path for path in (SRC / Path(*PACKAGE.split("."))).rglob("*.py") if "__pycache__" not in path.parts
)
for path in files:
    try:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    except SyntaxError as exc:
        problems.append(f"syntax {path.relative_to(SRC)}:{exc.lineno}: {exc.msg}")
print(f"Compiled {len(files)} modules")

# Load the stack's real configuration with extensions disabled, so Superset neither imports the deployed bundle
# (its supx:// import hook would shadow the source) nor registers the same API blueprints twice.
config_path = SRC.parent / "superset_config_compat.py"
config_path.write_text(
    "import os\n"
    "exec(open(os.environ['COMPAT_BASE_CONFIG'], encoding='utf-8').read())\n"
    "FEATURE_FLAGS = {**globals().get('FEATURE_FLAGS', {}), 'ENABLE_EXTENSIONS': False}\n",
    encoding="utf-8",
)
os.environ["COMPAT_BASE_CONFIG"] = os.environ.get("SUPERSET_CONFIG_PATH", "/app/pythonpath/superset_config.py")
os.environ["SUPERSET_CONFIG_PATH"] = str(config_path)

from superset.app import create_app

app = create_app()
with app.app_context():
    sys.path.insert(0, str(SRC))

    for path in files:
        parts = path.relative_to(SRC).with_suffix("").parts
        module_name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        try:
            module = importlib.import_module(module_name)
        except Exception:
            lines = traceback.format_exc().strip().splitlines()
            problems.append(f"import {module_name}:\n    " + "\n    ".join(lines[-3:]))
            continue
        module_file = getattr(module, "__file__", None)
        if module_file and not Path(module_file).is_relative_to(SRC):
            problems.append(f"import {module_name}: resolved to {module_file}, not the copied source")
    print(f"Imported {len(files)} modules")

for problem in problems:
    print(f"PROBLEM {problem}")
sys.exit(1 if problems else 0)
"""


def _bundle_drift() -> list[str]:
    """Return backend source files that differ from, or are missing in, the host bundle."""
    prefix = "backend/src/"
    with zipfile.ZipFile(BUNDLE_PATH) as bundle:
        bundled = {
            name.removeprefix(prefix): bundle.read(name) for name in bundle.namelist() if name.startswith(prefix)
        }
    source = {
        path.relative_to(BACKEND_SRC).as_posix(): path.read_bytes()
        for path in BACKEND_SRC.rglob("*")
        if path.is_file() and path.suffix in {".py", ".json", ".md"} and "__pycache__" not in path.parts
    }
    drift = [f"changed  {name}" for name in sorted(source.keys() & bundled.keys()) if source[name] != bundled[name]]
    drift += [f"missing  {name}" for name in sorted(source.keys() - bundled.keys())]
    drift += [f"extra    {name}" for name in sorted(bundled.keys() - source.keys())]
    return drift


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    require_superset_running()
    warnings = []

    step("Comparing the host bundle with the backend source")
    if not BUNDLE_PATH.exists():
        warnings.append(f"{BUNDLE_PATH.name} does not exist")
    elif drift := _bundle_drift():
        print("\n".join(drift))
        warnings.append("the host bundle is stale; run `uv run scripts/ship.py`")
    else:
        print("The host bundle matches the backend source.")

    step("Comparing the deployed bundle with the host bundle")
    if BUNDLE_PATH.exists() and container_sha256(CONTAINER_BUNDLE_PATH) != sha256_file(BUNDLE_PATH):
        warnings.append("the deployed bundle differs from the host bundle; run `uv run scripts/deploy.py`")
    else:
        print("The deployed bundle matches the host bundle.")

    step("Compiling and importing the source inside the Superset container")
    compose("exec", "-T", "-u", "root", SUPERSET_SERVICE, "rm", "-rf", CONTAINER_SRC)
    compose("cp", str(BACKEND_SRC), f"{SUPERSET_SERVICE}:{CONTAINER_SRC}")
    result = compose(
        "exec",
        "-T",
        SUPERSET_SERVICE,
        "python",
        "-",
        CONTAINER_SRC,
        PACKAGE,
        stdin=CONTAINER_SCRIPT,
        check=False,
        capture=True,
    )
    # Superset logs every startup step; keep only this script's report lines.
    report = [line for line in result.stdout.splitlines() if line.startswith(REPORT_PREFIXES)]
    print("\n".join(report))
    if result.returncode != 0 and not any(line.startswith("PROBLEM") for line in report):
        print("\n".join((result.stdout + result.stderr).splitlines()[-30:]))

    step("Summary")
    for warning in warnings:
        print(f"WARNING: {warning}")
    if result.returncode != 0:
        fail("the source is not compatible with the Superset runtime (see PROBLEM lines above)")
    print("The source compiles and imports against the Superset runtime.")


if __name__ == "__main__":
    main()
