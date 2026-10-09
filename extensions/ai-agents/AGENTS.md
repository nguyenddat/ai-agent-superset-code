# Text to BI AI Agent extension

This directory follows Apache Superset's native extension layout for packaging
and backend API registration. The Superset 6.1 frontend compatibility adapter
mounts the dashboard button beside the actions menu because this host version
does not expose the newer chat contribution API.

## Extension structure

```text
extensions/ai-agents/
├── extension.json
├── backend/
│   ├── pyproject.toml
│   └── src/text_to_bi/text_to_bi_code/
│       ├── entrypoint.py
│       ├── modules/chat/route.py
│       ├── agent_package/
│       ├── core/
│       ├── models/
│       └── repositories/
└── frontend/
    ├── src/index.tsx
    ├── src/integration/installDashboardAI.tsx
    ├── src/features/chat/components/AIChatSidebar.tsx
    └── webpack.config.js
```

## Superset integration

- `extension.json` defines publisher `text-to-bi` and extension name
  `text-to-bi-code`.
- `frontend/src/index.tsx` starts the Superset 6.1 dashboard UI adapter.
- `backend/src/text_to_bi/text_to_bi_code/entrypoint.py` imports the REST API
  class so Superset's extension loader registers it.
- The API is served at
  `/extensions/text-to-bi/text-to-bi-code/chat/stream` and requires the
  `can read on text_to_bi_chat_api` permission plus a valid CSRF token.
- The frontend attaches its button beside the dashboard actions menu and owns
  the drawer state because Superset 6.1 does not provide `chat.registerChat`.

## Build and install

From this directory:

```sh
cd frontend
npm install
cd ..
superset-extensions bundle
```

Copy `text-to-bi-code-0.1.0.supx` into the configured `EXTENSIONS_PATH` and
restart Superset. In the local Compose stack, that path is mounted from the
repository's `extensions/` directory.

Superset dependencies used by the backend are installed in the Superset image.
Frontend React and ReactDOM versions must stay compatible with the host Superset
version and be shared with the host through Module Federation.
