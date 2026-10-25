# Text To BI project guide

## Project overview

This repository runs a local Text to BI stack around Apache Superset 6.1.0. It
contains a PostgreSQL analytics database with sample weather data, a Superset
metadata database, and two Superset extensions: an AI Agent and a Semantic Layer.

## Main directories

- `data_wh/` defines the warehouse schema. `001_init_bang_co_so.sql` creates
  the `dm_*` and normalized `tb_*` tables; `002_init_bang_dashboard.sql`
  creates dashboard tables from that business layer.
- `airflow/` contains the Open-Meteo ingestion DAG and its runtime files.
- `superset/` contains the Superset image definition, local configuration, and
  admin, warehouse and governance bootstrap scripts. `bootstrap_governance.py`
  builds the "Tổng quan AI Agent" dashboard on read-only views of the AI Agent
  question log.
- `extensions/ai-agents/` contains the AI Agent frontend and backend. Its
  `/ai-agent/` chat page keeps each user's conversations and streams each step
  as a tool call; see its own `AGENTS.md`.
- `extensions/semantic-layer/` contains the admin-only semantic metadata UI and
  backend. Its metadata tables live in Superset's metadata database.
- `extensions/*.supx` contains the bundles copied into the running Superset
  container. Keep one current bundle per extension here.

## Python environment

Use the uv-managed virtual environment `.venv` at the repository root for local
Python commands and extension tooling. The root `pyproject.toml` and `uv.lock`
define it: Python 3.12, the extension backend dependencies, and the `dev` group
with `apache-superset-extensions-cli` (`superset-extensions`), `pytest`, and
`ruff`.

```sh
uv sync
uv run python --version
```

Run Python tools through `uv run` (for example `uv run pytest` or
`uv run ruff check`); it finds the root project from any subdirectory. Add or
change dependencies with `uv add` / `uv add --dev` so `uv.lock` stays current.

Superset's application runtime runs inside the Docker image. The local uv
environment is for development commands and extension packaging.

## Stack commands

Run these commands from the repository root:

```sh
docker compose up --build -d
docker compose ps
docker compose logs -f superset
```

Superset is available at `http://localhost:8089` by default. The analytics
database is `warehouse-db` (`data_wh`); Superset metadata is stored separately
in `superset-db`. Both databases use persistent Compose volumes.

## Build, install, and restart extensions

After changing extension source or extension build configuration, rebuild both
bundles, copy them into the `superset_extensions` volume, and restart the
Superset service:

```sh
uv sync

cd extensions/ai-agents
uv run superset-extensions bundle
cp superset-ai-agent-0.1.0.supx ..
rm -f superset-ai-agent-0.1.0.supx

cd ../semantic-layer
uv run superset-extensions bundle
cp superset-semantic-layer-0.1.0.supx ..
rm -f superset-semantic-layer-0.1.0.supx

cd ../..
docker compose up -d --build superset
docker compose cp extensions/superset-ai-agent-0.1.0.supx superset:/app/superset_home/extensions/
docker compose cp extensions/superset-semantic-layer-0.1.0.supx superset:/app/superset_home/extensions/
docker compose restart superset
docker compose ps
```

The source directories hold editable code. The two root `.supx` files are the
current bundles; Superset reads them from the `superset_extensions` named
volume at `/app/superset_home/extensions`, shared by `superset-init` and
`superset`. The bundles are copied in with `docker compose cp` instead of
bind-mounted, because bind mounts from the host drive served stale `.supx`
content under Docker Desktop's Hyper-V file sharing. A fresh volume is empty, so
run the two `docker compose cp` commands after the first `docker compose up`.
Bundle output created inside an extension source directory is temporary and can
be regenerated with the build command.

## Semantic Layer development scripts

`scripts/` holds the day-to-day workflow for the Semantic Layer. Run each script
from the repository root with `uv run`; `--help` prints its options.

| Script | What it does |
| --- | --- |
| `scripts/doctor.py` | Checks uv, node, npm, docker, frontend `node_modules`, the Docker engine (must be Hyper-V `linuxkit`, not WSL2), the running services, and Superset `/health`. |
| `scripts/check.py` | Runs Ruff and pytest on the backend and `npm run typecheck` on the frontend. `--no-frontend` skips the typecheck. |
| `scripts/build.py` | Bundles `extensions/superset-semantic-layer-<version>.supx` with `superset-extensions bundle`. |
| `scripts/deploy.py` | Copies the bundle into the `superset_extensions` volume, verifies its sha256 against the host file, restarts Superset, waits for `/health`, and checks the startup log for the extension load line. |
| `scripts/ship.py` | Runs `build.py` then `deploy.py`. `--check` runs `check.py` first; `--smoke` runs `smoke.py` last. |
| `scripts/compat.py` | Checks the source against the real Superset 6.1 runtime: flags a stale host or deployed bundle, then compiles every backend module with the container's Python 3.10 and imports it inside a Superset app context. |
| `scripts/smoke.py` | Logs in through the Superset login form as the admin and calls the read-only Semantic Layer endpoints, expecting 200 with JSON. It changes no data. |
| `scripts/logs.py` | Prints Superset log lines about the extension, the Semantic Layer, and errors. `--since 10m`, `--follow`, and `--all` adjust it. |

Typical loop after changing Semantic Layer code:

```sh
uv run scripts/check.py
uv run scripts/compat.py
uv run scripts/ship.py --smoke
```

The local pytest suite runs on Python 3.12 against stubbed `superset` modules,
so it cannot catch Superset API drift or Python 3.10 syntax; `compat.py` and
`smoke.py` cover that against the running container. `compat.py` and
`smoke.py` need the stack up (`docker compose up -d`).

The scripts work around two Windows issues. `superset-extensions` starts npm
with `subprocess.run(["npm", ...])`, which Windows cannot resolve because npm
is `npm.cmd`, so `build.py` resolves each executable through `PATH` first. The
scripts also force UTF-8 output, because the CLI's emoji messages fail on the
cp1252 console encoding when output is redirected.

`smoke.py` logs in through `/login/` rather than the JWT API because the
extension reads the admin role from the flask-login session; with a JWT it
answers `Admin access required.`. Set `SUPERSET_URL` or `SUPERSET_PORT` when
Superset is not on `http://localhost:8089`, and `SUPERSET_ADMIN_USERNAME` /
`SUPERSET_ADMIN_PASSWORD` when the admin is not `admin`/`admin`.

## Semantic metadata

The Semantic Layer owns `text_to_bi_dataset_dictionary` and
`text_to_bi_column_dictionary` in Superset's metadata database. A dataset
dictionary `id` shares the corresponding Superset dataset ID through
`tables.id`; each column dictionary row references its dataset dictionary with
`dataset_id`. `text_to_bi_dataset_proposal` holds the virtual datasets the AI
Agent drafts over base (`dm_*`, `tb_*`) datasets when no aggregate dataset can
answer a question; an administrator creates or rejects them in "Xử lý câu hỏi" →
"Đề xuất dataset". Opening the Semantic Layer as an administrator creates these
tables and seeds dictionary rows from the existing Superset datasets.

## Code style

These rules apply to Python and TypeScript alike:

- Lines may be up to 120 characters. Wrap only past that limit; keep a short
  call, import, object or JSX element on one line instead of splitting it.
- Name variables, functions and components for what they mean in the domain,
  such as `metricContract`, `selectedDataset` or `approvedAt`. Do not abbreviate
  (`ds`, `col`, `m`, `tmp`, `res`); single letters are only for short loop
  indexes.

Ruff configuration is in the root `pyproject.toml` and each extension backend's
`pyproject.toml`, with the 120-character line length. Ruff rule `D100` is
ignored, so Python modules do not need a module-level docstring solely to
satisfy that rule. The frontends have no formatter; follow the same limit by
hand.

## Local configuration and secrets

Local environment files such as `extensions/ai-agents/.env` are not source code.
Keep credentials and API keys out of commits, bundles, and documentation. The
Compose defaults are for local development; configure secrets through local
environment files before exposing the stack outside the development machine.
