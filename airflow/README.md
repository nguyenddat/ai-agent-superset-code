# Airflow weather warehouse

Airflow runs the weather ingestion workflow only. The DAG requests weather
data from Open-Meteo, writes normalized business data to PostgreSQL `data_wh`,
then rebuilds the dashboard tables.

```text
airflow/
├── dags/
│   └── weather_warehouse_ingest.py
├── logs/                         # Airflow logs
└── plugins/                      # Airflow plugins
```

The DAG runs hourly and loads 12 Vietnamese cities, seven past days and seven
forecast days. It writes to `dm_*` and `tb_*` tables and calls
`lam_moi_du_lieu_dashboard()` after a successful load.
