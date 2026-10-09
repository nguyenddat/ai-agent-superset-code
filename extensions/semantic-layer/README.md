# Text to BI Semantic Layer extension

This extension adds an admin-only Semantic Layer item to the dashboard actions
menu. It reads the dashboard's registered Superset datasets and displays their
columns, descriptions, and metrics. The UI and API are a first increment toward
visualizing semantic models and metric dependencies.

## Structure

```text
semantic-layer/
├── extension.json
├── backend/
│   ├── pyproject.toml
│   └── src/text_to_bi/text_to_bi_semantic_layer/
│       ├── entrypoint.py
│       ├── modules/catalog/route.py
│       └── services/
└── frontend/
    ├── src/integration/installDashboardSemanticLayer.tsx
    ├── src/features/semantic-layer/
    ├── src/index.tsx
    ├── package.json
    ├── tsconfig.json
    └── webpack.config.js
```

The backend access endpoint checks the authenticated user's `Admin` role before the
frontend adds the dashboard menu item. Non-admin users receive a forbidden
response and do not see the entry point. Dataset details are fetched using
Superset's dashboard datasets API, which continues to enforce Superset access.

This first increment shows the Superset dataset-level semantic metadata. It does
not yet read a MetricFlow project or infer metric-to-metric dependencies from
SQL expressions.

The backend owns `text_to_bi_dataset_dictionary` and
`text_to_bi_column_dictionary` tables. A dataset dictionary row uses the matching
Superset dataset ID as its `id` (`id -> tables.id`). Column dictionary rows point
to the dataset dictionary through `dataset_id -> text_to_bi_dataset_dictionary.id`,
and `referenced_column` points to another column dictionary row. Audit timestamps
follow Superset's nullable audit mixin. The tables are created idempotently the
first time an administrator opens the extension, after Superset's core schema is
available. Existing column dictionary installations are upgraded from `table_id`
to `dataset_id` in place, with a dataset dictionary row backfilled for each
existing dataset reference.

## Build

Install frontend dependencies in `frontend/`, then bundle the extension from
this directory with `superset-extensions bundle`.
