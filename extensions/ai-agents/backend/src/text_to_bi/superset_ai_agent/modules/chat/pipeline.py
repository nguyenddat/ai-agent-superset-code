"""The agent flow: understand the question against the governed catalog, query the approved metrics, answer.

One model call (`understand_question`) rewrites a follow-up into a standalone question, names the glossary terms,
metrics and expert rules it is about, and plans the metric query: its dimensions, and filters for time, place, the
user's own definitions and thresholds the asker gave. The plan is checked against the catalog and an approved rule's
filters are taken from the rule itself before the Semantic Layer runs each metric (`query_metrics`).

Expert rules are only required for a qualitative question: one worded by perception with a vague threshold (lớn,
nhỏ, đông, vắng), which someone has to pin down; a quantitative question needs defined concepts and metrics only.
What a concept means is often the asker's own sense, so a missing glossary term or expert rule becomes a question to
the user (`clarifications`) instead of a query; what the user confirms is kept for them on that dashboard and is used
in their later questions, unless an approved business term or rule covers the concept. A missing metric is proposed
to an administrator instead (`suggestions`).

`run_agent` is a generator of `(event_name, data)` pairs that the route streams as Server-Sent Events. Each step is
reported as a tool call (`tool_start`, then `tool_end` with its result), the final answer streams as `token`
events, and the generator returns an `AgentOutcome` for the question log.
"""

import json
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import prompts
from .query import QueryPlanError, combined_result, plan_query, result_for_answer
from .semantic_source import MetricQueryError, SemanticCatalog

MAX_HISTORY_TURNS = 3
MAX_HISTORY_MESSAGE_LENGTH = 2000
MISSING_KINDS = ("glossary", "metric", "expert_rule")
WEEKDAYS = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")

Event = tuple[str, dict[str, Any]]
# Runs one approved metric: (dataset_id, metric_id, {dimensions, filters}) -> the Semantic Layer's answer.
MetricRunner = Callable[[int, int, dict[str, Any]], dict[str, Any]]


class MetricReference(BaseModel):
    dataset_id: int
    metric_id: int


class QueryFilter(BaseModel):
    column: str
    operator: Literal["==", "!=", "<", "<=", ">", ">=", "IN", "NOT IN"]
    value: int | float | str | list[int | float | str]
    source: Literal["time", "place", "user_definition", "question", "expert_rule"]


class QueryPlan(BaseModel):
    dataset_id: int
    metric_ids: list[int]
    dimensions: list[str] = Field(default_factory=list)
    filters: list[QueryFilter] = Field(default_factory=list)
    presentation: Literal["number", "table", "bar", "line"] = "table"
    scope: str = Field(default="", description="Phạm vi bằng lời, ví dụ \"Hà Nội, 19/10–25/10/2026\".")


class Understanding(BaseModel):
    standalone_question: str = Field(description="Câu hỏi đầy đủ, tự đứng được một mình.")
    term_ids: list[int] = Field(default_factory=list)
    user_definition_ids: list[int] = Field(default_factory=list)
    undefined_concepts: list[str] = Field(default_factory=list)
    metrics: list[MetricReference] = Field(default_factory=list)
    question_kind: Literal["qualitative", "quantitative"]
    qualitative_concepts: list[str] = Field(default_factory=list)
    rule_ids: list[int] = Field(default_factory=list)
    user_rule_ids: list[int] = Field(default_factory=list)
    query: QueryPlan | None = None
    reason: str = ""


class DefinitionOption(BaseModel):
    label: str = Field(description="Nhãn ngắn của lựa chọn, ví dụ \"Từ 39 km/h (cấp 6)\".")
    definition: str = Field(description="Định nghĩa đầy đủ nếu người dùng chọn lựa chọn này.")


class DefinitionDraft(BaseModel):
    kind: Literal["glossary", "expert_rule"]
    concept: str = Field(description="Khái niệm trong câu hỏi.")
    name: str
    question: str = Field(description="Câu hỏi ngắn gửi người dùng.")
    options: list[DefinitionOption] = Field(description="2 đến 4 cách hiểu, cách phổ biến nhất đứng đầu.")


class MetricProposal(BaseModel):
    name: str
    definition: str
    unit: str = ""


class MissingProposals(BaseModel):
    definitions: list[DefinitionDraft] = Field(default_factory=list)
    metric: MetricProposal | None = None


@dataclass
class AgentOutcome:
    rewritten_question: str | None = None
    glossary_terms: list[dict[str, Any]] = field(default_factory=list)
    # Business concepts the question uses that no approved term, metric or rule defines; only these make a term missing.
    undefined_concepts: list[str] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    expert_rules: list[dict[str, Any]] = field(default_factory=list)
    # The user's own definitions on this dashboard that the question used.
    user_definitions: list[dict[str, Any]] = field(default_factory=list)
    requires_expert_rule: bool = True
    suggestions: dict[str, dict[str, Any]] = field(default_factory=dict)
    clarifications: list[dict[str, Any]] = field(default_factory=list)
    # The table the metric query answered with, or why it could not run.
    result: dict[str, Any] | None = None
    query_error: str | None = None
    answer: str = ""

    @property
    def missing(self) -> list[str]:
        """What the semantic layer lacks for this question.

        A glossary term is missing only for a concept nothing defines: a question fully described by an approved
        metric, such as "nhiệt độ trung bình tháng này", needs no term of its own. A concept the user confirmed on this
        dashboard counts as the question's expert rule.
        """
        has_user_rule = any(item["kind"] == "expert_rule" for item in self.user_definitions)
        gaps = {
            "glossary": bool(self.undefined_concepts),
            "metric": not self.metrics,
            "expert_rule": self.requires_expert_rule and not self.expert_rules and not has_user_rule,
        }
        return [kind for kind in MISSING_KINDS if gaps[kind]]

    @property
    def status(self) -> str:
        return "needs_review" if self.missing else "resolved"


def recent_history(history: Any) -> list[dict[str, str]]:
    """The last few user and assistant turns, trimmed; anything malformed from the browser is dropped."""
    if not isinstance(history, list):
        return []
    messages = [
        {"role": item["role"], "content": item["content"].strip()[:MAX_HISTORY_MESSAGE_LENGTH]}
        for item in history
        if isinstance(item, dict) and item.get("role") in ("user", "assistant")
        and isinstance(item.get("content"), str) and item["content"].strip()
    ]
    return messages[-MAX_HISTORY_TURNS * 2:]


def _data_block(label: str, value: Any) -> str:
    return f"{label}:\n```json\n{json.dumps(value, ensure_ascii=False, indent=1, default=str)}\n```"


def _described(items: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Catalog items reduced to the fields a step needs to judge them."""
    return [{key: item.get(key) for key in fields if item.get(key) not in (None, "", [])} for item in items]


TERM_FIELDS = ("id", "name", "synonyms", "definition")
USER_DEFINITION_FIELDS = ("id", "kind", "name", "concept", "definition")
METRIC_FIELDS = ("dataset_id", "metric_id", "name", "definition", "unit", "glossary_term_ids")
RULE_FIELDS = ("id", "name", "dataset_id", "conditions", "exceptions", "metric_ids", "glossary_term_ids")


def _known(ids: list[int], items_by_id: dict[int, dict[str, Any]]) -> list[int]:
    """The IDs the model returned that are real candidates, de-duplicated in the model's order."""
    return [item_id for item_id in dict.fromkeys(ids) if item_id in items_by_id]


def _tool_call(
    index: int, name: str, arguments: dict[str, Any], action: Callable[[], Any], shown: Callable[[Any], Any]
):
    """Run one step as a reported tool call; `shown` turns the step's return value into the result the UI displays."""
    call_id = f"call_{index}"
    yield "tool_start", {"id": call_id, "name": name, "arguments": arguments}
    started = time.monotonic()
    try:
        value = action()
    except Exception as ex:
        yield "tool_end", {
            "id": call_id, "name": name, "status": "error", "error": str(ex) or type(ex).__name__,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
        raise
    yield "tool_end", {
        "id": call_id, "name": name, "status": "ok", "result": shown(value),
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
    return value


def _ask(model: Any, schema: type[BaseModel], system_prompt: str, user_content: str) -> Any:
    return model.with_structured_output(schema).invoke([("system", system_prompt), ("human", user_content)])


MAX_OPTIONS = 4


def _clarifications(proposals: MissingProposals, missing: list[str]) -> list[dict[str, Any]]:
    """The questions the user is asked: only for a missing term or rule, named, with at least one usable option."""
    drafts: dict[tuple[str, str], dict[str, Any]] = {}
    for draft in proposals.definitions:
        name = draft.name.strip()
        options = [
            {"label": option.label.strip(), "definition": option.definition.strip()}
            for option in draft.options if option.label.strip() and option.definition.strip()
        ][:MAX_OPTIONS]
        if draft.kind in missing and name and options:
            drafts.setdefault((draft.kind, name.casefold()), {
                "kind": draft.kind, "concept": draft.concept.strip(), "name": name,
                "question": draft.question.strip() or f"Bạn hiểu “{draft.concept.strip() or name}” là gì?",
                "options": options,
            })
    return list(drafts.values())


def _suggestions(proposals: MissingProposals, missing: list[str]) -> dict[str, dict[str, Any]]:
    """The metric proposed to administrators, when a metric is missing and the model named one."""
    metric = proposals.metric
    return {"metric": metric.model_dump()} if "metric" in missing and metric and metric.name.strip() else {}


def _proposals_shown(proposals: MissingProposals, missing: list[str]) -> dict[str, Any]:
    return {"clarifications": _clarifications(proposals, missing), **_suggestions(proposals, missing)}


def _today_block(today: date) -> str:
    return _data_block("Hôm nay", {"today": today.isoformat(), "weekday": WEEKDAYS[today.weekday()]})


def _understanding_shown(
    value: Understanding,
    terms_by_id: dict[int, dict[str, Any]],
    metrics_by_key: dict[tuple[int, int], dict[str, Any]],
    rules_by_id: dict[int, dict[str, Any]],
    definitions_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    qualitative = value.question_kind == "qualitative"
    rule_ids, user_rule_ids = (value.rule_ids, value.user_rule_ids) if qualitative else ([], [])
    return {
        "standalone_question": value.standalone_question,
        "glossary_terms": [terms_by_id[term_id]["name"] for term_id in _known(value.term_ids, terms_by_id)],
        "undefined_concepts": value.undefined_concepts,
        "metrics": [
            metrics_by_key[(item.dataset_id, item.metric_id)]["name"]
            for item in value.metrics if (item.dataset_id, item.metric_id) in metrics_by_key
        ],
        "question_kind": value.question_kind,
        "qualitative_concepts": value.qualitative_concepts,
        "expert_rules": [rules_by_id[rule_id]["name"] for rule_id in _known(rule_ids, rules_by_id)],
        "user_definitions": [
            definitions_by_id[item_id]["name"]
            for item_id in _known(value.user_definition_ids + user_rule_ids, definitions_by_id)
        ],
        "query": value.query.model_dump() if value.query else None,
        "reason": value.reason,
    }


def _run_metrics(planned: Any, run_metric: MetricRunner) -> dict[str, Any]:
    """Each metric is its own governed query; they share dimensions and filters, so they run side by side."""
    body = planned.request_body()
    with ThreadPoolExecutor(max_workers=len(planned.metrics)) as pool:
        answers = list(pool.map(
            lambda metric: run_metric(planned.dataset_id, metric["metric_id"], body), planned.metrics,
        ))
    return combined_result(planned, answers)


def _query_shown(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": result["scope"],
        "filters": [
            {key: item[key] for key in ("column", "operator", "shown_value", "source")} for item in result["filters"]
        ],
        "dimensions": [dimension["name"] for dimension in result["dimensions"]],
        "metrics": [metric["label"] for metric in result["metrics"]],
        "row_count": result["row_count"],
        "rows": result["rows"][:5],
    }


def run_agent(
    question: str,
    history: list[dict[str, str]],
    model: Any,
    load_catalog: Callable[[], SemanticCatalog],
    user_definitions: Sequence[dict[str, Any]] = (),
    run_metric: MetricRunner | None = None,
    today: date | None = None,
) -> Iterator[Event]:
    """Run one question; `user_definitions` are what the user confirmed on this dashboard."""
    today = today or date.today()
    outcome = AgentOutcome()
    definitions_by_id = {item["id"]: item for item in user_definitions}
    user_rules_by_id = {item_id: item for item_id, item in definitions_by_id.items() if item["kind"] == "expert_rule"}

    catalog = yield from _tool_call(1, "load_semantic_catalog", {}, load_catalog, SemanticCatalog.summary)
    terms_by_id = {term["id"]: term for term in catalog.glossary_terms}
    metrics_by_key = {(metric["dataset_id"], metric["metric_id"]): metric for metric in catalog.metrics}
    rules_by_id = {rule["id"]: rule for rule in catalog.expert_rules}

    conversation = "\n".join(f"{item['role']}: {item['content']}" for item in history) or "(chưa có)"
    understanding_input = "\n\n".join((
        _today_block(today),
        f"Lịch sử hội thoại:\n{conversation}",
        f"Câu hỏi mới nhất: {question}",
        _data_block("Thuật ngữ đã duyệt", _described(catalog.glossary_terms, TERM_FIELDS)),
        _data_block("Metric đã duyệt", _described(catalog.metrics, METRIC_FIELDS)),
        _data_block("Expert rule đã duyệt", _described(catalog.expert_rules, RULE_FIELDS)),
        _data_block("Cách hiểu người dùng đã xác nhận", _described(list(user_definitions), USER_DEFINITION_FIELDS)),
        _data_block("Dataset: cột và giá trị có nhãn", catalog.datasets),
    ))
    understanding = yield from _tool_call(
        2, "understand_question", {"question": question, "history_turns": len(history) // 2},
        lambda: _ask(model, Understanding, prompts.UNDERSTAND_QUESTION, understanding_input),
        lambda value: _understanding_shown(value, terms_by_id, metrics_by_key, rules_by_id, definitions_by_id),
    )
    outcome.rewritten_question = understanding.standalone_question.strip() or question
    asked = outcome.rewritten_question
    chosen_terms = [terms_by_id[term_id] for term_id in _known(understanding.term_ids, terms_by_id)]
    outcome.glossary_terms = [{"id": term["id"], "name": term["name"]} for term in chosen_terms]
    outcome.undefined_concepts = [concept.strip() for concept in understanding.undefined_concepts if concept.strip()]
    chosen_metrics: list[dict[str, Any]] = []
    for item in understanding.metrics:
        metric = metrics_by_key.get((item.dataset_id, item.metric_id))
        if metric and metric not in chosen_metrics:
            chosen_metrics.append(metric)
    outcome.metrics = [
        {"dataset_id": metric["dataset_id"], "metric_id": metric["metric_id"], "name": metric["name"]}
        for metric in chosen_metrics
    ]
    used_definition_ids = _known(understanding.user_definition_ids, definitions_by_id)
    outcome.requires_expert_rule = understanding.question_kind == "qualitative"
    chosen_rules = []
    if outcome.requires_expert_rule:
        chosen_rules = [rules_by_id[rule_id] for rule_id in _known(understanding.rule_ids, rules_by_id)]
        outcome.expert_rules = [{"id": rule["id"], "name": rule["name"]} for rule in chosen_rules]
        used_definition_ids += _known(understanding.user_rule_ids, user_rules_by_id)
    outcome.user_definitions = [
        {key: definitions_by_id[item_id][key] for key in ("id", "kind", "name", "definition")}
        for item_id in dict.fromkeys(used_definition_ids)
    ]

    missing = outcome.missing
    step = 3
    if missing:
        proposal_context = {
            "question": asked,
            "question_kind": understanding.question_kind,
            "undefined_concepts": outcome.undefined_concepts,
            "qualitative_concepts": understanding.qualitative_concepts,
            "missing": missing,
            "found": {
                "glossary_terms": outcome.glossary_terms,
                "metrics": _described(chosen_metrics, ("name", "definition", "unit")),
                "expert_rules": outcome.expert_rules,
                "user_definitions": outcome.user_definitions,
            },
            "existing_names": catalog.summary(),
        }
        try:
            proposals = yield from _tool_call(
                step, "propose_missing_items", {"question": asked, "missing": missing},
                lambda: _ask(
                    model, MissingProposals, prompts.PROPOSE_MISSING_ITEMS,
                    _data_block("Câu hỏi và phần còn thiếu", proposal_context),
                ),
                lambda value: _proposals_shown(value, missing),
            )
        except Exception:  # noqa: BLE001
            # A proposal is a convenience; the error is already reported and the answer still goes on.
            proposals = MissingProposals()
        outcome.clarifications = _clarifications(proposals, missing)
        outcome.suggestions = _suggestions(proposals, missing)
    elif run_metric is not None:
        plan = understanding.query.model_dump() if understanding.query else None
        try:
            planned = plan_query(plan, catalog.datasets, catalog.metrics, chosen_rules)
            outcome.result = yield from _tool_call(
                step, "query_metrics", {"plan": plan, "expert_rule_ids": [rule["id"] for rule in chosen_rules]},
                lambda: _run_metrics(planned, run_metric),
                _query_shown,
            )
            yield "result", outcome.result
        except (QueryPlanError, MetricQueryError) as ex:
            outcome.query_error = str(ex)

    context = {
        "today": today.isoformat(),
        "question": asked,
        "glossary_terms": _described(chosen_terms, ("name", "definition")),
        "metrics": _described(chosen_metrics, ("name", "definition", "unit")),
        "expert_rules": _described(chosen_rules, ("name", "conditions", "exceptions")),
        "user_definitions": outcome.user_definitions,
        "missing": missing,
        "clarifications": outcome.clarifications,
        "suggestions": outcome.suggestions,
    }
    if outcome.result is not None:
        context["result"] = result_for_answer(outcome.result)
    if outcome.query_error:
        context["query_error"] = outcome.query_error
    answer_prompt = [("system", prompts.FINAL_ANSWER), ("human", _data_block("Bối cảnh trả lời", context))]
    for chunk in model.stream(answer_prompt):
        text = chunk.content if isinstance(chunk.content, str) else ""
        if text:
            outcome.answer += text
            yield "token", {"text": text}
    return outcome
