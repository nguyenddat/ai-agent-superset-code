"""Run the Semantic Layer's local checks: Ruff, pytest, and the frontend typecheck.

Usage: uv run scripts/check.py [--no-frontend]
"""

import argparse
import sys

from _common import BACKEND_DIR, FRONTEND_DIR, ROOT, run, step


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-frontend", action="store_true", help="skip the TypeScript typecheck")
    args = parser.parse_args(argv)

    checks = [
        ("Ruff", [sys.executable, "-m", "ruff", "check", str(BACKEND_DIR)], ROOT),
        ("pytest", [sys.executable, "-m", "pytest", str(BACKEND_DIR / "tests"), "-q"], ROOT),
    ]
    if not args.no_frontend:
        checks.append(("TypeScript typecheck", ["npm", "run", "typecheck"], FRONTEND_DIR))

    failed = []
    for name, command, cwd in checks:
        step(name)
        if run(command, cwd=cwd, check=False).returncode != 0:
            failed.append(name)

    step("Summary")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
