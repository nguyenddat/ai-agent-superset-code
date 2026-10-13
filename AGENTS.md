# Text To BI project guide

## Project overview

This repository runs a local Text to BI stack around Apache Superset 6.1.0. It
contains a PostgreSQL analytics database with sample weather data, a Superset
metadata database, and two Superset extensions: an AI Agent and a Semantic Layer.

## Main directories

- `primary_db/` builds the analytics database image. `seed_data.py` creates the
  demo data, and `ingest_data.py` refreshes weather observations.
- `superset/` contains the Superset image definition, local configuration, and
  admin initialization script.
- `extensions/ai-agents/` contains the AI Agent frontend and backend. Its
  dashboard panel streams chat requests through the Superset extension API.
- `extensions/semantic-layer/` contains the admin-only semantic metadata UI and
  backend. Its metadata tables live in Superset's metadata database.
- `extensions/*.supx` contains the bundles mounted into the running Superset
  container. Keep one current bundle per extension here.

## Python environment

Use the Conda environment `ai-agent-superset` for local Python commands and
extension tooling. It currently provides Python 3.12 and
`superset-extensions`.

```sh
conda activate ai-agent-superset
python --version
```

When running commands without an activated shell, use
`conda run -n ai-agent-superset python ...`.

Superset's application runtime runs inside the Docker image. The local Conda
environment is for development commands and extension packaging.

## Stack commands

Run these commands from the repository root:

```sh
docker compose up --build -d
docker compose ps
docker compose logs -f superset
```

Superset is available at `http://localhost:8089` by default. The analytics
database is `primary-db`; Superset metadata is stored separately in
`superset-db`. Both databases use persistent Compose volumes.

## Build, mount, and restart extensions

After changing extension source or extension build configuration, rebuild both
bundles, copy them into the mounted `extensions/` directory, and recreate the
Superset service:

```sh
conda activate ai-agent-superset

cd extensions/ai-agents
superset-extensions bundle
cp superset-ai-agent-0.1.0.supx ..
rm -f superset-ai-agent-0.1.0.supx

cd ../semantic-layer
superset-extensions bundle
cp superset-semantic-layer-0.1.0.supx ..
rm -f superset-semantic-layer-0.1.0.supx

cd ../..
docker compose up -d --build superset
docker compose ps
```

The source directories hold editable code. The root `extensions/` directory is
mounted read-only at `/app/superset_home/extensions` and should contain the
runtime `.supx` bundles. Bundle output created inside an extension source
directory is temporary and can be regenerated with the build command.

## Semantic metadata

The Semantic Layer owns `text_to_bi_dataset_dictionary` and
`text_to_bi_column_dictionary` in Superset's metadata database. A dataset
dictionary `id` shares the corresponding Superset dataset ID through
`tables.id`; each column dictionary row references its dataset dictionary with
`dataset_id`. Opening the Semantic Layer as an administrator creates these
tables and seeds dictionary rows from the existing Superset datasets.

## Python style

Ruff configuration is in the root `pyproject.toml` and each extension backend's
`pyproject.toml`. Keep the configured 120-character line length to avoid
unnecessary wrapping. Ruff rule `D100` is ignored, so Python modules do not need
a module-level docstring solely to satisfy that rule.

## Local configuration and secrets

Local environment files such as `extensions/ai-agents/.env` are not source code.
Keep credentials and API keys out of commits, bundles, and documentation. The
Compose defaults are for local development; configure secrets through local
environment files before exposing the stack outside the development machine.
