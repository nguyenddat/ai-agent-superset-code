#!/usr/bin/env bash

set -euo pipefail

airflow db migrate

airflow users create \
  --username "${AIRFLOW_ADMIN_USERNAME}" \
  --password "${AIRFLOW_ADMIN_PASSWORD}" \
  --firstname Airflow \
  --lastname Admin \
  --role Admin \
  --email "${AIRFLOW_ADMIN_EMAIL}" || true

airflow scheduler &
scheduler_pid=$!

cleanup() {
  kill "${scheduler_pid}" 2>/dev/null || true
  wait "${scheduler_pid}" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

airflow webserver --port 8080
