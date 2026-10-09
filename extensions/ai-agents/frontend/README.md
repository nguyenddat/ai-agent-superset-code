# AI Agent frontend

This frontend is the Superset 6.1 compatibility UI for the extension. The
entrypoint mounts an AI Agent button beside the dashboard actions menu and opens
the panel in a right-side drawer. The backend remains a native Superset extension
API, and the frontend bundle uses Module Federation with the host's React 17.

The dashboard header mount uses Superset's current DOM selectors because
Superset 6.1 does not expose the newer chat contribution API. Keep the adapter
small and verify it against the supported dashboard header after Superset
upgrades.

## Build

```sh
npm install
npm run typecheck
npm run build
```

From `extensions/ai-agents/`, run `superset-extensions bundle` to package the
frontend and backend into a `.supx` file. Copy that file to the configured
`EXTENSIONS_PATH` and restart Superset.
