# Text to BI local stack

Start the local demo stack from this directory:

```sh
docker compose up --build -d
```

This starts:

- Apache Superset 6.1.0 at <http://localhost:8089> (`SUPERSET_PORT` can override this).
- `primary-db`, a PostgreSQL database named `weather` for analytics data.
- A one-shot seed job that creates the weather tables and fetches a current observation for five Vietnamese cities from Open-Meteo.
- A weather ingester that refreshes the current observation every 15 minutes after seeding completes.
- A separate PostgreSQL database and volume for Superset metadata.

The seed job can be run again with `docker compose run --rm seed-data`; it refreshes the current observation for each city. The ingester continues collecting observations every 15 minutes, updating an existing timestamp if the source has not advanced yet.

Default local Superset login: `admin` / `admin`. These defaults are for local development only. Set `SUPERSET_ADMIN_PASSWORD`, `SUPERSET_SECRET_KEY`, `POSTGRES_PASSWORD`, and `SUPERSET_DB_PASSWORD` in a `.env` file before exposing the stack beyond your machine.

In Superset, add a database using this SQLAlchemy URI:

```text
postgresql+psycopg2://bi:bi_dev_password@primary-db:5432/weather
```

The primary database is only reachable by other Compose services; it is not published on the host. Superset's extension support is enabled, and `.supx` bundles can be placed in `extensions/` for loading at startup.

Useful commands:

```sh
docker compose logs -f ingest
docker compose logs -f seed-data
docker compose down
```

`docker compose down -v` also deletes both persisted database volumes.
