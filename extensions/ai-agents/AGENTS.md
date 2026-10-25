# Superset AI Agent extension

This directory follows Apache Superset's native extension layout for packaging
and backend API registration. Superset 6.1 does not expose the newer chat
contribution API, so the frontend adds an "AI Agent" item to Superset's navbar,
between "SQL" and the Semantic Layer menus, for every signed-in user, and
renders its own page below Superset's header at `/ai-agent/`.

## The AI Agent page

The page works like a chatbot: the user's conversations on the left, grouped by
when they were last active, and the open one on the right. A conversation
(`text_to_bi_agent_chat_session`) is about one dashboard, chosen when it starts
and fixed afterwards; a question cannot be asked without one. Opened from a
dashboard, the navbar link is `/ai-agent/?dashboard=<id or slug>` and that
dashboard is preselected; `/ai-agent/?session=<id>` reopens a conversation.
Every turn is a row of the question log with its `session_id` and the
`tool_calls` it ran, so a reopened conversation shows each answer and step
again. Deleting a conversation keeps its questions in the log with no session.

## Asking the user back

What a qualitative concept or an undefined term means is often a personal sense
("gió mạnh", "đông khách"), so the agent asks the user instead of an
administrator. When a term or rule is missing, `propose_missing_items` drafts
one question per concept with two to four options (the likeliest first; a rule
option is a measurable threshold on the found metric). The page shows them as a
card, one question at a time: the user picks an option (keys 1–N, Enter) or
writes their own under "Khác", then sends every answer at once, or skips. The
answers are saved per user and dashboard (`text_to_bi_agent_user_definition`)
and the question is answered again with them. While saving, one model call per
confirmed rule (`modules/definitions/conditions.py`, in parallel) turns its text
into checked filters on one dataset (`conditions`: column, label, operator,
value), so every later question uses that exact threshold, as with an approved
rule; a definition no filter can express keeps `conditions` NULL and is followed
from its text. Editing a definition's text structures it again. Every later
conversation of that user on that dashboard uses them; the "Cách hiểu của bạn"
panel lists, edits and deletes them. An approved term or rule always takes precedence over a
user's definition of the same concept.

Administrators never edit users' definitions. In the Semantic Layer's "Xử lý câu
hỏi" module, the "Cách hiểu của người dùng" tab groups them by concept and
counts the users behind each, as a signal of where a shared definition would
help. "Tạo thuật ngữ chung" / "Tạo expert rule chung" only prefills the name
(and an example question); the shared definition and threshold are the
business experts', not a copy of the users'. Saving it marks the definitions
`promoted`; "Giữ là cách hiểu cá nhân" marks them `ignored`; a user editing a
definition puts it back to `pending`. A missing metric still goes to
administrators, in the "Thiếu metric" tab.

## What the agent does

For each question the agent works out which governed business content it is
about, runs the approved metrics through the Semantic Layer, answers with the
numbers, and logs the question so administrators can fill the gaps:

1. The browser sends the question and its conversation; the server reads the
   conversation's last three answered turns from the log.
2. `load_semantic_catalog` reads the Semantic Layer's consumer endpoints
   (`/semantic-catalog`, `/glossary/discovery`, `/expert-rules/discover`, then
   `/dataset/<id>/dimension-members` for each dataset with approved metrics) in
   parallel over HTTP inside the container, forwarding the user's session
   cookie, so the agent only sees approved content on datasets that user may
   access. The catalog is cached per user for 60 seconds.
3. `understand_question` is one model call that does what used to be four
   steps: it rewrites a follow-up into a standalone question; picks the glossary
   terms, metrics, expert rules and the user's own definitions the question is
   about (IDs it invents are dropped); lists `undefined_concepts` (business
   concepts nothing defines; time, place and aggregation words do not count);
   classifies the question as `qualitative` (worded by perception with a vague
   threshold, so it needs an expert rule) or `quantitative`; and plans the
   metric query. The plan names the dataset, metrics, dimensions and filters
   tagged by source: `time` (dates computed from today in Vietnam's time),
   `place` (key values found through the dataset's labelled values, so "Hà Nội"
   becomes `thanh_pho_key = 1`), `user_definition` (only for a user's definition
   without stored conditions) and `question` (a threshold the asker gave). It
   may also rank (`order_by` a metric and `limit` 1–100 groups) and compare
   (`comparison`: the same query over another period, such as last week). The
   catalog's `time_ranges` (first and last date of each dataset date column, from
   `dimension-members`) let it pick dates the data covers. The model runs with
   `reasoning_effort="low"`.
4. When something is missing, `propose_missing_items` drafts the questions back
   to the user for a missing term or rule (`clarifications`) and a metric
   proposal for administrators (`suggestions`), and no query runs. A failure here
   is reported but does not stop the answer.
5. Otherwise `query_metrics` checks the plan against the catalog
   (`modules/chat/query.py`): only listed columns, filterable or groupable as
   used, and the supported operators. An approved expert rule's filters come
   from the rule's own conditions, never from the model's copy of them, and a
   rule with a condition no filter can express stops the query. A user's
   definition with stored `conditions` is applied the same way and replaces the
   model's filters on its columns. Ranking, the row limit and the comparison run
   on the agent side, because the execute endpoint takes only dimensions and
   filters: a comparison needs time filters and no date dimension, and runs every
   metric again over the other period, adding `<metric>__compare` columns. The
   requested dates are checked against `time_ranges` (`coverage`: `full`,
   `partial` or `none`), so a period outside the data is told apart from one
   where nothing matched. Each metric then
   runs through the Semantic Layer's governed
   `.../metrics/<id>/semantic-query/execute` endpoint as the user (cookie and
   CSRF token forwarded), in parallel, and the answers merge into one table: a
   row per dimension value, a column per metric, key values shown by their
   labels. A `result` event carries it to the browser before the answer
   streams. A plan the catalog does not allow, or a query the Semantic Layer
   refuses, becomes `query_error` for the answer instead.
6. The final answer streams as tokens, written for a business user from the
   numbers in the result: the direct answer first, then the criterion and
   whether it is the business's shared definition or the user's own, "theo dự
   báo" for dates after today.

The stream opens with a `session` event naming the conversation (new or
existing). Each step then reaches the browser as a tool call (`tool_start`,
`tool_end`), then `result` when a query ran, `token` events, and a closing
`done` event. A question is `resolved` when it found at least one metric, has no
`undefined_concepts`, and has an approved or user's expert rule if it is
qualitative; otherwise it is `needs_review` with `missing` listing what was not
found. `done` also carries `clarifications`, the `user_definitions` used,
`result` and `query_error`. The log stores `requires_expert_rule` (NULL on older
questions), `suggestions`, `clarifications` with `clarification_state`
(`pending`, `confirmed`, `dismissed`), `retry_of` on the answer given again after
a confirmation, and `query_result`. A metric proposal opens on the Metrics page,
because metrics are created in the Superset dataset editor.

The page shows a result as one number per metric, a line or columns over time
(a line per group, with a legend, for up to eight groups), ranked horizontal
bars across groups (in the asked order when ranked), or a table; the chart and
table views switch in place. A comparison shows each number with the other
period's value and the change, and the table gains "kỳ so sánh" and "Thay đổi"
columns. The heading names the ranking, the comparison and any gap in the data's
date range. The conditions used appear as chips naming their source, and "Xem
truy vấn" opens the request sent for each metric and period with the SQL the
Semantic Layer ran, which it returns to administrators only. The "Cách hiểu của
bạn" panel shows a definition's stored conditions as chips.

## Extension structure

```text
extensions/ai-agents/
├── extension.json
├── backend/
│   ├── src/text_to_bi/superset_ai_agent/
│   │   ├── entrypoint.py
│   │   ├── core/chat_models.py           # OpenRouter model, key from .env
│   │   ├── models/question_log.py        # question log, handling, chat session and user definition tables
│   │   └── modules/
│   │       ├── chat/                     # pipeline, prompts, catalog reader, query planner, /chat/stream
│   │       ├── definitions/              # users' definitions: their own, and the admin review
│   │       ├── questions/                # /questions/review, /questions/<id>/handling
│   │       └── sessions/                 # /sessions API and the /ai-agent/ page view
│   └── tests/
└── frontend/
    ├── src/index.tsx
    ├── src/integration/installAIAgent.tsx         # navbar item, page mount
    ├── src/features/chat/AgentPage.tsx            # conversations and the open conversation
    ├── src/features/chat/components/ChatTurn.tsx  # one turn: tool calls, answer, outcome, question card
    ├── src/features/chat/components/DefinitionsPanel.tsx  # "Cách hiểu của bạn"
    ├── src/features/chat/components/QueryResultView.tsx   # number, chart or table, conditions, queries
    ├── src/shared/api/chat.ts
    └── webpack.config.js
```

## API

- `POST /extensions/text-to-bi/superset-ai-agent/chat/stream` takes
  `{question, session_id}` to continue a conversation, or
  `{question, dashboard_id}` to start one about a dashboard the user may open,
  and answers with Server-Sent Events. It needs `can read on
  text_to_bi_chat_api` and a CSRF token.
- `GET .../sessions/` lists the user's conversations; `GET .../sessions/<id>`
  returns one with its turns; `PUT .../sessions/<id>` takes `{title}`;
  `DELETE .../sessions/<id>` deletes it (CSRF for both). A user only sees their
  own conversations. `GET .../sessions/<id>` also returns the user's
  definitions on its dashboard.
- `PUT .../sessions/<id>/questions/<question_id>/clarification` takes
  `{state: "confirmed", definitions: [{kind, concept, name, definition}]}` or
  `{state: "dismissed"}` (CSRF); confirming a concept again replaces the user's
  earlier definition of it on that dashboard.
- `GET .../definitions/?dashboard_id=` lists the user's definitions;
  `PUT .../definitions/<id>` takes `{name, definition}` and structures the
  conditions again when the text changed; `DELETE
  .../definitions/<id>` forgets one (CSRF, own definitions only).
- `GET .../definitions/review` lists every user's definitions; `PUT
  .../definitions/review` takes `{ids, status}` with `pending`, `promoted` or
  `ignored` (admin only, CSRF).
- `GET /ai-agent/` serves the page to users with `can read on
  text_to_bi_chat_api`.
- `GET /extensions/text-to-bi/superset-ai-agent/questions/review?handling=&missing=`
  lists `needs_review` questions with their handling (admin only).
- `PUT /extensions/text-to-bi/superset-ai-agent/questions/<id>/handling` takes
  `{status, note}`, where status is `pending`, `to_create`, `created` or
  `ignored` (admin only, CSRF).

The Semantic Layer's "Xử lý câu hỏi" module uses the question and definition review endpoints.

## Question log and the overview dashboard

`text_to_bi_agent_question`, `text_to_bi_agent_question_handling`,
`text_to_bi_agent_chat_session` and `text_to_bi_agent_user_definition` live in
Superset's metadata database and are created on first use.
`superset/bootstrap_governance.py` (run by `superset-init`) publishes read-only
views of them in the `text_to_bi_reporting` schema, a login role that may read
only that schema, the "Text to BI Governance" connection, and the
"Tổng quan AI Agent" dashboard that the Semantic Layer's "Tổng quan" module
embeds. That connection is flagged `text_to_bi_internal`, so the Semantic Layer
leaves it out of its database and dataset pickers. Rerun the script after
changing the views or charts:

```sh
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps superset-init python /app/pythonpath/bootstrap_governance.py
```

## Build and install

There is no build script for this extension yet. Bundle it the same way
`scripts/build.py` bundles the Semantic Layer (run `superset-extensions bundle`
in this directory, resolving `npm` to `npm.cmd` on Windows), write the bundle to
`extensions/superset-ai-agent-0.1.0.supx`, then copy it into the
`superset_extensions` volume and restart Superset as the root `AGENTS.md`
describes.

`OPENROUTER_API_KEY` comes from `extensions/ai-agents/.env`, which Compose loads
into the Superset containers. Keep that file out of commits and bundles.
