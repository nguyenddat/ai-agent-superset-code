"""Show Superset log lines about the Semantic Layer, extension loading, and errors.

Usage: uv run scripts/logs.py [--since 10m] [--follow] [--all]
"""

import argparse
import re
import subprocess

from _common import SUPERSET_SERVICE, resolve_command

PATTERN = re.compile(
    r"semantic|text_to_bi|text-to-bi|extension|Traceback|Error|Exception|^\S+\s+\|\s+(File|\s)", re.IGNORECASE
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", default="30m", help="how far back to read, for example 10m or 2h (default 30m)")
    parser.add_argument("--follow", "-f", action="store_true", help="keep streaming new lines")
    parser.add_argument("--all", action="store_true", help="print every line instead of filtering")
    args = parser.parse_args(argv)

    command = ["docker", "compose", "logs", "--no-color", "--since", args.since]
    if args.follow:
        command.append("--follow")
    command.append(SUPERSET_SERVICE)

    with subprocess.Popen(
        resolve_command(command), stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace"
    ) as process:
        try:
            for line in process.stdout:
                if args.all or PATTERN.search(line):
                    print(line, end="", flush=True)
        except KeyboardInterrupt:
            process.terminate()


if __name__ == "__main__":
    main()
