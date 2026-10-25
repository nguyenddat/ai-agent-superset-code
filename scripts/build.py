"""Build the Semantic Layer bundle into extensions/superset-semantic-layer-<version>.supx.

Usage: uv run scripts/build.py

Runs `superset-extensions bundle` in-process. The CLI starts npm with `subprocess.run(["npm", ...])`, which
Windows cannot resolve because npm is `npm.cmd`, so every subprocess executable is resolved through PATH first.
"""

import argparse
import os
import subprocess

from _common import BUNDLE_PATH, EXTENSION_DIR, resolve_command, sha256_file, step


def _bundle() -> None:
    real_run = subprocess.run

    def run_resolved(command, *args, **kwargs):
        if isinstance(command, list) and command:
            command = resolve_command(command)
        return real_run(command, *args, **kwargs)

    subprocess.run = run_resolved
    previous_cwd = os.getcwd()
    try:
        from superset_extensions_cli.cli import app

        os.chdir(EXTENSION_DIR)
        app.main(["bundle", "--output", str(BUNDLE_PATH)], standalone_mode=False)
    finally:
        os.chdir(previous_cwd)
        subprocess.run = real_run


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)

    step(f"Bundling {EXTENSION_DIR.relative_to(EXTENSION_DIR.parents[1])}")
    _bundle()
    print(f"Bundle: {BUNDLE_PATH}")
    print(f"sha256: {sha256_file(BUNDLE_PATH)}")


if __name__ == "__main__":
    main()
