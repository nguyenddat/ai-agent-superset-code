"""Copy the Semantic Layer bundle into the running Superset container and restart it.

Usage: uv run scripts/deploy.py

Copies the bundle into the `superset_extensions` volume with `docker compose cp`, checks that the volume holds
the same bytes as the host file, restarts Superset, waits for /health, and checks the startup log for the
extension load message.
"""

import argparse
from datetime import UTC, datetime

from _common import (
    BUNDLE_PATH,
    CONTAINER_BUNDLE_PATH,
    CONTAINER_EXTENSIONS_DIR,
    EXTENSION_ID,
    SUPERSET_SERVICE,
    compose,
    container_sha256,
    fail,
    require_superset_running,
    sha256_file,
    step,
    wait_for_health,
)

LOG_ERROR_MARKERS = ("Traceback", "not a valid zip", "Failed to load extension")


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)

    if not BUNDLE_PATH.exists():
        fail(f"{BUNDLE_PATH} does not exist; run `uv run scripts/build.py` first")
    require_superset_running()

    step("Copying the bundle into the extensions volume")
    compose("cp", str(BUNDLE_PATH), f"{SUPERSET_SERVICE}:{CONTAINER_EXTENSIONS_DIR}/")
    host_hash = sha256_file(BUNDLE_PATH)
    volume_hash = container_sha256(CONTAINER_BUNDLE_PATH)
    print(f"host   sha256: {host_hash}\nvolume sha256: {volume_hash}")
    if host_hash != volume_hash:
        fail("the bundle in the volume differs from the host bundle")

    step("Restarting Superset")
    restarted_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    compose("restart", SUPERSET_SERVICE)
    wait_for_health()

    step("Checking the startup log")
    log = compose("logs", "--no-color", "--since", restarted_at, SUPERSET_SERVICE, capture=True).stdout
    errors = [line for line in log.splitlines() if any(marker in line for marker in LOG_ERROR_MARKERS)]
    for line in errors:
        print(line)
    if f"Loaded extension '{EXTENSION_ID}'" not in log:
        fail(f"the startup log has no 'Loaded extension {EXTENSION_ID}' line")
    if errors:
        fail("the startup log contains errors (see above)")
    print(f"Superset loaded {EXTENSION_ID}.")


if __name__ == "__main__":
    main()
