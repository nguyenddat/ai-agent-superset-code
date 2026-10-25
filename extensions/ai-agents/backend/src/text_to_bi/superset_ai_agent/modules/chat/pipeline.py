"""The agent flow: rewrite the question, then name the glossary terms, metrics and expert rules it is about.

Expert rules are only required for a qualitative question: one worded by perception with a vague threshold (lớn,
nhỏ, đông, vắng), which someone has to pin down; a quantitative question needs defined concepts and metrics only.

What a concept means is often the asker's own sense, so a missing glossary term or expert rule becomes a question to
the user (`clarifications`) with a few candidate definitions to pick from or replace. What the user confirms is kept
for them on that dashboard and counts as defined in their later questions, unless an approved business term or rule
covers the concept. A missing metric is proposed to an administrator instead (`suggestions`).

`run_agent` is a generator of `(event_name, data)` pairs that the route streams as Server-Sent Events. Each step is
reported as a tool call (`tool_start`, then `tool_end` with its result), the final answer streams as `token`
events, and the generator returns an `AgentOutcome` for the question log.
"""

import json
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from . import prompts
from .semantic_source import SemanticCatalog

MAX_HISTORY_TURNS = 3
MAX_HISTORY_MESSAGE_LENGTH = 2000
MISSING_KINDS = ("glossary", "metric", "expert_rule")

Event = tuple[str, dict[str, Any]]


class RewrittenQuestion(BaseModel):
    standalone_question: str = Field(description="Câu hỏi đầy đủ, tự đứng được một mình.")


class GlossarySelection(BaseModel):
    term_ids: list[int] = Field(default_factory=list)
    user_definition_ids: list[int] = Field(
        default_factory=list, description="Cách hiểu người dùng đã xác nhận mà câu hỏi dùng tới.",
    )
    undefined_concepts: list[str] = Field(
        default_factory=list,
        description="Khái niệm nghiệp vụ trong câu hỏi mà không thuật ngữ hay metric nào định nghĩa.",
    )
    reason: str = ""


class MetricReference(BaseModel):
    dataset_id: int
    metric_id: int


class MetricSelection(BaseModel):
    metrics: list[MetricReference] = Field(default_factory=list)
    reason: str = ""


class ExpertRuleSelection(BaseModel):
    question_kind: Literal["qualitative", "quantitative"] = Field(
        description="qualitative khi câu hỏi dùng khái niệm cần chuyên gia đặt ngưỡng, ngược lại quantitative.",
    )
    qualitative_concepts: list[str] = Field(default_factory=list)
    rule_ids: list[int] = Field(default_factory=list)
    user_rule_ids: list[int] = Field(
        default_factory=list, description="Cách hiểu khái niệm định tính người dùng đã xác nhận áp dụng cho câu hỏi.",
    )
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
    return f"{label}:\n```json\n{json.dumps(value, ensure_ascii=False, indent=1)}\n```"


def _described(items: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Catalog items reduced to the fields a step needs to judge them, so later steps see definitions, not names."""
    return [{key: item.get(key) for key in fields if item.get(key) not in (None, "", [])} for item in items]


TERM_FIELDS = ("id", "name", "synonyms", "definition")
USER_DEFINITION_FIELDS = ("id", "kind", "name", "concept", "definition")
METRIC_FIELDS = ("dataset_id", "metric_id", "name", "definition", "unit", "glossary_term_ids")


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


def run_agent(
    question: str,
    history: list[dict[str, str]],
    model: Any,
    load_catalog: Callable[[], SemanticCatalog],
    user_definitions: Sequence[dict[str, Any]] = (),
) -> Iterator[Event]:
    """Run one question; `user_definitions` are what the user confirmed on this dashboard."""
    outcome = AgentOutcome()
    definitions_by_id = {item["id"]: item for item in user_definitions}
    own_definitions = _data_block(
        "Cách hiểu người dùng đã xác nhận",
        _described(list(user_definitions), USER_DEFINITION_FIELDS),
    )

    conversation = "\n".join(f"{item['role']}: {item['content']}" for item in history) or "(chưa có)"
    rewritten = yield from _tool_call(
        1, "rewrite_question", {"question": question, "history_turns": len(history) // 2},
        lambda: _ask(
            model, RewrittenQuestion, prompts.REWRITE_QUESTION,
            f"Lịch sử hội thoại:\n{conversation}\n\nCâu hỏi mới nhất: {question}",
        ),
        lambda value: {"standalone_question": value.standalone_question},
    )
    outcome.rewritten_question = rewritten.standalone_question.strip() or question
    asked = outcome.rewritten_question

    catalog = yield from _tool_call(2, "load_semantic_catalog", {}, load_catalog, SemanticCatalog.summary)

    # The model is asked even without approved terms: a concept nothing defines is what makes a term missing.
    terms_by_id = {term["id"]: term for term in catalog.glossary_terms}
    glossary = yield from _tool_call(
        3, "identify_glossary_terms", {"question": asked, "candidates": len(terms_by_id)},
        lambda: _ask(
            model, GlossarySelection, prompts.IDENTIFY_GLOSSARY,
            f"Câu hỏi: {asked}\n\n"
            + _data_block("Thuật ngữ đã duyệt", _described(catalog.glossary_terms, TERM_FIELDS)) + "\n\n"
            + _data_block("Metric đã duyệt", _described(catalog.metrics, ("name", "definition", "unit"))) + "\n\n"
            + _data_block("Expert rule đã duyệt", _described(catalog.expert_rules, ("name", "conditions"))) + "\n\n"
            + own_definitions,
        ),
        lambda value: {
            "glossary_terms": [terms_by_id[term_id]["name"] for term_id in _known(value.term_ids, terms_by_id)],
            "user_definitions": [
                definitions_by_id[item_id]["name"]
                for item_id in _known(value.user_definition_ids, definitions_by_id)
            ],
            "undefined_concepts": value.undefined_concepts,
            "reason": value.reason,
        },
    )
    used_definition_ids = _known(glossary.user_definition_ids, definitions_by_id)
    chosen_terms = [terms_by_id[term_id] for term_id in _known(glossary.term_ids, terms_by_id)]
    outcome.glossary_terms = [{"id": term["id"], "name": term["name"]} for term in chosen_terms]
    outcome.undefined_concepts = [concept.strip() for concept in glossary.undefined_concepts if concept.strip()]

    metrics_by_key = {(metric["dataset_id"], metric["metric_id"]): metric for metric in catalog.metrics}
    chosen_term_ids = [term["id"] for term in outcome.glossary_terms]
    metric_arguments = {"question": asked, "glossary_term_ids": chosen_term_ids, "candidates": len(metrics_by_key)}
    metric_selection = yield from _tool_call(
        4, "identify_metrics", metric_arguments,
        lambda: _ask(
            model, MetricSelection, prompts.IDENTIFY_METRICS,
            f"Câu hỏi: {asked}\n\n"
            + _data_block("Thuật ngữ đã xác định", _described(chosen_terms, TERM_FIELDS)) + "\n\n"
            + _data_block("Metric đã duyệt", _described(catalog.metrics, METRIC_FIELDS)),
        ) if metrics_by_key else MetricSelection(reason="Semantic layer chưa có metric nào được duyệt."),
        lambda value: {
            "metrics": [
                metrics_by_key[(item.dataset_id, item.metric_id)]["name"]
                for item in value.metrics if (item.dataset_id, item.metric_id) in metrics_by_key
            ],
            "reason": value.reason,
        },
    )
    chosen_metrics: list[dict[str, Any]] = []
    for item in metric_selection.metrics:
        key = (item.dataset_id, item.metric_id)
        if key in metrics_by_key and metrics_by_key[key] not in chosen_metrics:
            chosen_metrics.append(metrics_by_key[key])
    outcome.metrics = [
        {"dataset_id": metric["dataset_id"], "metric_id": metric["metric_id"], "name": metric["name"]}
        for metric in chosen_metrics
    ]

    # The model is asked even without approved rules: whether the question is qualitative decides if one is missing.
    rules_by_id = {rule["id"]: rule for rule in catalog.expert_rules}
    user_rules_by_id = {
        item_id: item for item_id, item in definitions_by_id.items() if item["kind"] == "expert_rule"
    }
    rule_selection = yield from _tool_call(
        5, "identify_expert_rules", {"question": asked, "candidates": len(rules_by_id)},
        lambda: _ask(
            model, ExpertRuleSelection, prompts.IDENTIFY_EXPERT_RULES,
            f"Câu hỏi: {asked}\n\n"
            + _data_block("Thuật ngữ đã xác định", _described(chosen_terms, TERM_FIELDS)) + "\n\n"
            + _data_block("Metric đã xác định", _described(chosen_metrics, METRIC_FIELDS)) + "\n\n"
            + _data_block("Expert rule đã duyệt", catalog.expert_rules) + "\n\n"
            + _data_block(
                "Cách hiểu khái niệm định tính người dùng đã xác nhận",
                _described(list(user_rules_by_id.values()), USER_DEFINITION_FIELDS),
            ),
        ),
        lambda value: {
            "question_kind": value.question_kind,
            "qualitative_concepts": value.qualitative_concepts,
            "expert_rules": [
                rules_by_id[rule_id]["name"] for rule_id in _known(value.rule_ids, rules_by_id)
            ] if value.question_kind == "qualitative" else [],
            "user_rules": [
                user_rules_by_id[item_id]["name"] for item_id in _known(value.user_rule_ids, user_rules_by_id)
            ] if value.question_kind == "qualitative" else [],
            "reason": value.reason,
        },
    )
    outcome.requires_expert_rule = rule_selection.question_kind == "qualitative"
    if outcome.requires_expert_rule:
        outcome.expert_rules = [
            {"id": rule_id, "name": rules_by_id[rule_id]["name"]}
            for rule_id in _known(rule_selection.rule_ids, rules_by_id)
        ]
        used_definition_ids += _known(rule_selection.user_rule_ids, user_rules_by_id)
    outcome.user_definitions = [
        {key: definitions_by_id[item_id][key] for key in ("id", "kind", "name", "definition")}
        for item_id in dict.fromkeys(used_definition_ids)
    ]

    missing = outcome.missing
    if missing:
        proposal_context = {
            "question": asked,
            "question_kind": rule_selection.question_kind,
            "undefined_concepts": outcome.undefined_concepts,
            "qualitative_concepts": rule_selection.qualitative_concepts,
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
                6, "propose_missing_items", {"question": asked, "missing": missing},
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

    selection = {
        "question": asked,
        "glossary_terms": outcome.glossary_terms,
        "undefined_concepts": outcome.undefined_concepts,
        "glossary_reason": glossary.reason,
        "metrics": outcome.metrics,
        "metric_reason": metric_selection.reason,
        "question_kind": rule_selection.question_kind,
        "qualitative_concepts": rule_selection.qualitative_concepts,
        "expert_rules": outcome.expert_rules,
        "expert_rule_reason": rule_selection.reason,
        "user_definitions": outcome.user_definitions,
        "missing": missing,
        "clarifications": outcome.clarifications,
        "suggestions": outcome.suggestions,
    }
    answer_prompt = [("system", prompts.FINAL_ANSWER), ("human", _data_block("Kết quả xác định", selection))]
    for chunk in model.stream(answer_prompt):
        text = chunk.content if isinstance(chunk.content, str) else ""
        if text:
            outcome.answer += text
            yield "token", {"text": text}
    return outcome
