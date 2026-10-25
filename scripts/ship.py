"""Build the Semantic Layer bundle, then deploy it to the running Superset container.

Usage: uv run scripts/ship.py [--check] [--smoke]
"""

import argparse

import build
import check
import deploy
import smoke


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="run scripts/check.py before building")
    parser.add_argument("--smoke", action="store_true", help="run scripts/smoke.py after deploying")
    args = parser.parse_args(argv)

    if args.check:
        check.main([])
    build.main([])
    deploy.main([])
    if args.smoke:
        smoke.main([])


if __name__ == "__main__":
    main()
