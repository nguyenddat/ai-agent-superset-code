import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Windows pipes default to cp1252, which cannot encode the emoji that superset-extensions prints.
for _stream in (sys.stdout, sys.stderr):
    _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = ROOT / "extensions" / "semantic-layer"
BACKEND_DIR = EXTENSION_DIR / "backend"
BACKEND_SRC = BACKEND_DIR / "src"
FRONTEND_DIR = EXTENSION_DIR / "frontend"

_MANIFEST = json.loads((EXTENSION_DIR / "extension.json").read_text(encoding="utf-8"))
EXTENSION_ID = f"{_MANIFEST['publisher']}.{_MANIFEST['name']}"
BUNDLE_PATH = ROOT / "extensions" / f"{_MANIFEST['name']}-{_MANIFEST['version']}.supx"

SUPERSET_SERVICE = "superset"
CONTAINER_EXTENSIONS_DIR = "/app/superset_home/extensions"
CONTAINER_BUNDLE_PATH = f"{CONTAINER_EXTENSIONS_DIR}/{BUNDLE_PATH.name}"
SUPERSET_URL = os.getenv("SUPERSET_URL", f"http://localhost:{os.getenv('SUPERSET_PORT', '8089')}")
API_PREFIX = f"/extensions/{_MANIFEST['publisher']}/{_MANIFEST['name']}"


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def resolve_command(command: list[str]) -> list[str]:
    """Resolve the executable through PATH and PATHEXT, so `npm` finds `npm.cmd` on Windows."""
    executable = shutil.which(command[0])
    return [executable, *command[1:]] if executable else command


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    capture: bool = False,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(
        resolve_command(command),
        check=False,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin,
        capture_output=capture,
    )
    if check and result.returncode != 0:
        if capture:
            print(result.stdout, result.stderr, sep="\n", file=sys.stderr)
        fail(f"command exited with {result.returncode}: {' '.join(command)}")
    return result


def compose(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    return run(["docker", "compose", *args], **kwargs)


def require_superset_running() -> None:
    result = compose("ps", "--status", "running", "--services", capture=True)
    if SUPERSET_SERVICE not in result.stdout.split():
        fail("the superset service is not running; start it with `docker compose up -d`")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def container_sha256(path: str) -> str | None:
    result = compose("exec", "-T", SUPERSET_SERVICE, "sha256sum", path, capture=True, check=False)
    return result.stdout.split()[0] if result.returncode == 0 and result.stdout else None


def wait_for_health(timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{SUPERSET_URL}/health", timeout=5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(3)
    fail(f"Superset did not report healthy at {SUPERSET_URL}/health within {timeout:.0f}s")
