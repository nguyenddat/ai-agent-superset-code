# Text to BI

Text to BI is a local Apache Superset 6.1.0 stack for exploring weather data
with natural-language BI assistance. The repository contains a PostgreSQL
analytics database, a separate PostgreSQL database for Superset metadata, and
two independently packaged Superset extensions:

1. **Superset AI Agent** — turns a dashboard question into a validated BI plan,
   resolves it against the dashboard datasets, builds SQL, and streams the
   result back to a dashboard drawer.
2. **Superset Semantic Layer** — lets administrators maintain dataset and
   column metadata and inspect relationships on a semantic canvas.

The extensions are intentionally separated so either one can be built,
packaged, installed, and evolved independently.

## Architecture

```text
Text to BI
├── data_wh/                     Weather warehouse schema and seed dimensions
├── airflow/                     Open-Meteo warehouse ingestion DAG
├── superset/                    Superset image and local configuration
├── extensions/
│   ├── ai-agents/               Superset AI Agent extension
│   │   ├── backend/             Python REST API and BI agents
│   │   └── frontend/            React dashboard chat drawer
│   └── semantic-layer/          Superset Semantic Layer extension
│       ├── backend/             Python REST API and dictionary models
│       └── frontend/            React dictionary and semantic canvas UI
├── docker-compose.yml
└── README.md
```

At runtime, the two root `.supx` bundles are mounted read-only into the
Superset container at `/app/superset_home/extensions`; extension source code
is not mounted into the runtime container.

## Requirements

- Docker Desktop with Docker Compose
- Conda environment `ai-agent-superset` for extension tooling
- Node.js and npm for frontend development
- An OpenRouter API key if AI planning or Semantic Layer AutoFill is enabled

The Superset image installs the backend dependencies needed by the extensions.
The local Conda environment is used for tests, linting, and
`superset-extensions bundle`.

## Quick start

From the repository root:

```sh
docker compose up --build -d
docker compose ps
```

Superset is available at <http://localhost:8089> by default. Set
`SUPERSET_PORT` to use another host port. The local default login is
`admin` / `admin`.

The Compose stack starts:

- `warehouse-db`: PostgreSQL 16 database named `data_wh` with normalized
  `dm_*` catalog tables, `tb_*` business tables, and dashboard tables also
  named with the `tb_*` convention.
- `airflow`: loads weather data for 12 Vietnamese cities from the Open-Meteo
  Forecast API every hour and refreshes the dashboard tables.
- `superset-db`: PostgreSQL 16 database for Superset metadata.
- `superset-init` and `superset`: Superset database initialization and web app.

On startup, `superset-init` automatically creates the `Weather Warehouse`
connection and registers every table in the warehouse `public` schema as a
dataset. The connection URI used by the bootstrap is:

```text
postgresql+psycopg2://bi:bi_dev_password@warehouse-db:5432/data_wh
```

The generated datasets include the `dm_*`, `tb_*`, `dim_*`, and `fact_*`
tables. If the warehouse schema changes, rerun `docker compose run --rm
superset-init` to synchronize the connection and datasets.

The warehouse is also published on host port `5433` by default for local tools:

```text
postgresql+psycopg2://bi:bi_dev_password@localhost:5433/data_wh
```

Useful operational commands:

```sh
docker compose logs -f superset
docker compose logs -f airflow
docker compose exec airflow airflow dags trigger weather_warehouse_ingest
docker compose down
```

`docker compose down -v` also removes both persistent database volumes.

## Configuration and secrets

Local credentials belong in `extensions/ai-agents/.env` or a root `.env` file;
they are ignored by Git. Before exposing the stack outside a development
machine, set at least:

```dotenv
SUPERSET_SECRET_KEY=replace-me
SUPERSET_ADMIN_PASSWORD=replace-me
POSTGRES_PASSWORD=replace-me
SUPERSET_DB_PASSWORD=replace-me
OPENROUTER_API_KEY=replace-me
SUPERSET_BASE_URL=http://superset:8088
SUPERSET_USERNAME=admin
SUPERSET_PASSWORD=replace-me
```

The AI Agent backend reads its Superset and model settings from the extension
environment. Do not commit API keys, passwords, or generated local `.env`
files.

## Extension 1: Superset AI Agent

Path: `extensions/ai-agents/`

The AI Agent adds an **AI Agent** button beside the dashboard actions menu. Its
streaming workflow is:

```text
Question
  → dashboard context and authorized datasets
  → BI Planner
  → Metadata Resolution
  → Data Builder
  → SQL / summary / chart link streamed to the drawer
```

The backend is organized into agents, prompts, tools, Superset client helpers,
models, and repositories. The frontend is a React 17-compatible dashboard
drawer that consumes Server-Sent Events (SSE).

Streaming endpoint:

```text
POST /extensions/text-to-bi/superset-ai-agent/chat/stream
```

The request must include a valid Superset CSRF token and a `dashboard_id` plus
the natural-language `query`. Access is checked against the dashboard and its
datasets. Grant `can read on text_to_bi_chat_api` to roles that should use the
assistant.

Build the extension from its directory:

```sh
conda activate ai-agent-superset
cd extensions/ai-agents/frontend
npm install
npm run typecheck
npm run build
cd ..
superset-extensions bundle
```

The bundle is `superset-ai-agent-0.1.0.supx`. Copy it to the repository
`extensions/` directory and recreate Superset:

```sh
cp superset-ai-agent-0.1.0.supx ..
cd ../..
docker compose up -d --build superset
```

On PowerShell, use `Copy-Item` instead of `cp` if needed.

## Extension 2: Superset Semantic Layer

Path: `extensions/semantic-layer/`

The Semantic Layer is admin-only. It adds a dashboard action that opens a
workspace with:

- dashboard dataset selection;
- dataset metadata: display name, description, grain, type, and create column;
- column metadata: display name, data type, business term, unit, format,
  nullability, keys, and references;
- AI AutoFill for unfilled dictionary fields;
- a semantic canvas for exploring columns, metrics, and dataset relationships.

The backend owns these Superset metadata database tables:

- `text_to_bi_dataset_dictionary`
- `text_to_bi_column_dictionary`

The dataset dictionary ID matches the Superset dataset ID. Column dictionary
rows reference their dataset through `dataset_id`, and column relationships use
`referenced_column`.

The extension API is mounted below:

```text
/extensions/text-to-bi/superset-semantic-layer/
```

Important routes include `/access`, dashboard dataset GET/POST, dictionary
GET/PUT, reference options, and dictionary suggestion streaming. The backend
checks the authenticated user's admin role before exposing the UI or allowing
dictionary writes. Opening the extension initializes or upgrades its metadata
tables idempotently.

Build the extension from its directory:

```sh
conda activate ai-agent-superset
cd extensions/semantic-layer/frontend
npm install
npm run typecheck
npm run build
cd ..
superset-extensions bundle
```

The bundle is `superset-semantic-layer-0.1.0.supx`. Copy it to the repository
`extensions/` directory and recreate Superset:

```sh
cp superset-semantic-layer-0.1.0.supx ..
cd ../..
docker compose up -d --build superset
```

## Development and validation

Run backend tests with the project Conda environment:

```sh
conda run -n ai-agent-superset python -m pytest extensions/ai-agents/backend/tests
```

Run Ruff against the extension backend sources when available:

```sh
conda run -n ai-agent-superset ruff check extensions/ai-agents/backend/src extensions/semantic-layer/backend/src
```

After changing either extension, rebuild its bundle and recreate the Superset
service. Check both the bundle name and service status before testing the UI:

```sh
docker compose ps
docker compose logs --tail=200 superset
```

## Project conventions

- Keep the AI Agent and Semantic Layer source trees independent.
- Keep one current `.supx` bundle per extension in `extensions/`.
- Do not commit `.env` files, credentials, node modules, build output, or local
  database files.
- Keep Python formatting consistent with the repository Ruff configuration and
  its 120-character line length.
