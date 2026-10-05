# AI Agent frontend

Local integration for Superset 6.1.0. Adds **AI Agent** immediately before the
dashboard action menu, for both viewers and editors. The chat sidebar is a UI
prototype; messages stay in memory and no AI request is sent yet. Its message
rows and scroll behavior use shadcn/ui `Message`, `Bubble`, and
`MessageScroller` components, styled with Tailwind CSS v4. React 19 is bundled
with this extension because the current shadcn message scroller requires it.

## Build

```sh
cd extensions/ai-agents/frontend
npm ci --no-bin-links
npm run typecheck
npm run build
```

`components.json` configures the shadcn CLI. Add components from the official
registry with `node node_modules/shadcn/dist/index.js add <component>`. `build.mjs` compiles the
Tailwind stylesheet to `dist/ai-agent.css` before bundling the React entry point
to `dist/ai-agent.js`.

`dist/ai-agent.js` and `dist/ai-agent.css` are served by the Flask blueprint in
`superset/superset_config.py`. The template `tail_js_custom_extra.html` loads them
through Superset's custom template hook. This is a local DOM integration, not a
packaged `.supx` extension. It does not modify Superset's installed source.

After changing the Python configuration, run `docker compose restart superset`
from the workspace root. After frontend changes, rebuild and reload the browser.

The adapter uses `button[data-test="actions-trigger"]` only on dashboard routes.
When upgrading Superset, verify that selector, editor/viewer placement, SPA
navigation, repeated reloads, keyboard focus, and both light/dark themes.
