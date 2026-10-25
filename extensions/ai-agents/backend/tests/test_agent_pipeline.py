from types import SimpleNamespace

import pytest

from text_to_bi.superset_ai_agent.modules.chat import pipeline
from text_to_bi.superset_ai_agent.modules.chat.semantic_source import SemanticCatalog, flatten_catalog


class FakeModel:
    """Answers each structured step from a table keyed by schema, and streams a fixed final answer."""

    def __init__(self, answers):
        self.answers = answers
        self.prompts = []

    def with_structured_output(self, schema):
        def invoke(messages):
            self.prompts.append((schema.__name__, messages))
            return self.answers[schema.__name__]

        return SimpleNamespace(invoke=invoke)

    def stream(self, messages):
        self.prompts.append(("final", messages))
        return [SimpleNamespace(content="Đã "), SimpleNamespace(content="xác định.")]


CATALOG = SemanticCatalog(
    glossary_terms=[{"id": 3, "name": "Nắng nóng", "synonyms": ["oi bức"], "definition": "Nóng."}],
    metrics=[{"dataset_id": 12, "metric_id": 17, "name": "Nhiệt độ cao nhất", "glossary_term_ids": [3]}],
    expert_rules=[{"id": 1, "name": "Ngày nắng nóng gay gắt", "metric_ids": [17], "glossary_term_ids": [3]}],
)


def _run(answers, catalog=CATALOG, history=(), user_definitions=()):
    model = FakeModel(answers)
    events = []
    generator = pipeline.run_agent(
        "Hà Nội có mấy ngày như vậy?", list(history), model, lambda: catalog, user_definitions,
    )
    while True:
        try:
            events.append(next(generator))
        except StopIteration as finished:
            return finished.value, events, model


GLOSSARY_DRAFT = {
    "kind": "glossary", "concept": "lượng mưa", "name": "Lượng mưa", "question": "Bạn hiểu “lượng mưa” là gì?",
    "options": [{"label": "Tổng trong ngày", "definition": "Tổng nước mưa trong ngày."}],
}
RULE_DRAFT = {
    "kind": "expert_rule", "concept": "mưa lớn", "name": "Ngày mưa lớn", "question": "Mưa bao nhiêu là lớn?",
    "options": [
        {"label": "Từ 50 mm", "definition": "Lượng mưa trong ngày từ 50 mm trở lên."},
        {"label": "Từ 100 mm", "definition": "Lượng mưa trong ngày từ 100 mm trở lên."},
    ],
}
PROPOSALS = pipeline.MissingProposals(
    definitions=[
        pipeline.DefinitionDraft(**GLOSSARY_DRAFT),
        pipeline.DefinitionDraft(**RULE_DRAFT),
        pipeline.DefinitionDraft(**{**RULE_DRAFT, "name": " ngày mưa lớn "}),
    ],
    metric=pipeline.MetricProposal(name="Tổng lượng mưa", definition="Cộng lượng mưa.", unit="mm"),
)


def _answers(
    term_ids=(3,), metrics=((12, 17),), rule_ids=(1,), question_kind="qualitative", proposals=PROPOSALS,
    undefined_concepts=(), user_definition_ids=(), user_rule_ids=(),
):
    return {
        "RewrittenQuestion": pipeline.RewrittenQuestion(standalone_question="Hà Nội có mấy ngày nắng nóng?"),
        "GlossarySelection": pipeline.GlossarySelection(
            term_ids=list(term_ids), undefined_concepts=list(undefined_concepts),
            user_definition_ids=list(user_definition_ids), reason="r",
        ),
        "MetricSelection": pipeline.MetricSelection(
            metrics=[pipeline.MetricReference(dataset_id=dataset, metric_id=metric) for dataset, metric in metrics],
            reason="r",
        ),
        "ExpertRuleSelection": pipeline.ExpertRuleSelection(
            question_kind=question_kind, qualitative_concepts=["nắng nóng"], rule_ids=list(rule_ids),
            user_rule_ids=list(user_rule_ids), reason="r",
        ),
        "MissingProposals": proposals,
    }


def test_each_step_is_reported_as_a_tool_call_and_the_answer_streams():
    outcome, events, _ = _run(_answers())

    names = [data["name"] for name, data in events if name == "tool_start"]
    assert names == [
        "rewrite_question", "load_semantic_catalog", "identify_glossary_terms", "identify_metrics",
        "identify_expert_rules",
    ]
    assert [data["status"] for name, data in events if name == "tool_end"] == ["ok"] * 5
    tool_end = next(data for name, data in events if name == "tool_end" and data["name"] == "identify_expert_rules")
    assert tool_end["result"]["question_kind"] == "qualitative"
    assert "".join(data["text"] for name, data in events if name == "token") == "Đã xác định."
    assert outcome.rewritten_question == "Hà Nội có mấy ngày nắng nóng?"
    assert outcome.glossary_terms == [{"id": 3, "name": "Nắng nóng"}]
    assert outcome.metrics == [{"dataset_id": 12, "metric_id": 17, "name": "Nhiệt độ cao nhất"}]
    assert outcome.expert_rules == [{"id": 1, "name": "Ngày nắng nóng gay gắt"}]
    assert (outcome.status, outcome.missing, outcome.answer) == ("resolved", [], "Đã xác định.")
    assert (outcome.requires_expert_rule, outcome.suggestions) == (True, {})


def test_ids_the_model_invents_or_repeats_are_dropped():
    outcome, _, _ = _run(_answers(term_ids=(3, 3, 99), metrics=((12, 17), (12, 17), (12, 99)), rule_ids=(7,)))

    assert [term["id"] for term in outcome.glossary_terms] == [3]
    assert [metric["metric_id"] for metric in outcome.metrics] == [17]
    assert outcome.expert_rules == []
    assert (outcome.status, outcome.missing) == ("needs_review", ["expert_rule"])
    assert (outcome.clarifications, outcome.suggestions) == ([RULE_DRAFT], {})


def test_a_quantitative_question_needs_no_expert_rule():
    outcome, events, _ = _run(_answers(rule_ids=(1,), question_kind="quantitative"))

    assert (outcome.requires_expert_rule, outcome.expert_rules) == (False, [])
    assert (outcome.status, outcome.missing, outcome.suggestions) == ("resolved", [], {})
    assert "propose_missing_items" not in [data["name"] for name, data in events if name == "tool_start"]


def test_a_question_a_metric_defines_needs_no_glossary_term():
    outcome, _, model = _run(_answers(term_ids=(), question_kind="quantitative"))

    assert (outcome.glossary_terms, outcome.undefined_concepts) == ([], [])
    assert (outcome.status, outcome.missing) == ("resolved", [])
    glossary_prompt = next(messages for schema, messages in model.prompts if schema == "GlossarySelection")[1][1]
    assert all(text in glossary_prompt for text in ("Nhiệt độ cao nhất", "Nóng.", "Ngày nắng nóng gay gắt"))


def test_later_steps_see_the_definitions_of_what_was_chosen():
    catalog = SemanticCatalog(
        glossary_terms=[{"id": 3, "name": "Nắng nóng", "synonyms": ["oi bức"], "definition": "Trời nóng bức."}],
        metrics=[{"dataset_id": 12, "metric_id": 17, "name": "Nhiệt độ cao nhất", "definition": "Cao nhất ngày.",
                  "unit": "°C", "glossary_term_ids": [3]}],
        expert_rules=CATALOG.expert_rules,
    )
    _, _, model = _run(_answers(), catalog=catalog)

    rule_prompt = next(messages for schema, messages in model.prompts if schema == "ExpertRuleSelection")[1][1]
    assert "Trời nóng bức." in rule_prompt and "Cao nhất ngày." in rule_prompt and "°C" in rule_prompt


def test_a_missing_term_or_rule_is_drafted_for_the_user_and_a_missing_metric_for_administrators():
    answers = _answers(term_ids=(), metrics=(), question_kind="quantitative", undefined_concepts=("lượng mưa",))
    outcome, events, model = _run(answers)

    assert outcome.missing == ["glossary", "metric"]
    assert outcome.clarifications == [GLOSSARY_DRAFT]
    assert outcome.suggestions == {"metric": {"name": "Tổng lượng mưa", "definition": "Cộng lượng mưa.", "unit": "mm"}}
    tool_end = next(data for name, data in events if name == "tool_end" and data["name"] == "propose_missing_items")
    assert list(tool_end["result"]) == ["clarifications", "metric"]
    final_prompt = model.prompts[-1][1][1][1]
    assert "Tổng lượng mưa" in final_prompt and "Bạn hiểu “lượng mưa” là gì?" in final_prompt


def test_definitions_the_user_confirmed_count_for_the_rest_of_the_conversation():
    user_definitions = [
        {"id": 5, "kind": "glossary", "name": "Khách du lịch", "concept": "khách", "definition": "Người lưu trú."},
        {"id": 6, "kind": "expert_rule", "name": "Ngày gió mạnh", "concept": "gió", "definition": "Gió ≥ 30 km/h."},
    ]
    answers = _answers(rule_ids=(), user_definition_ids=(5, 99), user_rule_ids=(6,))
    outcome, _, model = _run(answers, user_definitions=user_definitions)

    assert (outcome.status, outcome.missing, outcome.clarifications) == ("resolved", [], [])
    assert [item["id"] for item in outcome.user_definitions] == [5, 6]
    rule_prompt = next(messages for schema, messages in model.prompts if schema == "ExpertRuleSelection")[1][1]
    assert "Gió ≥ 30 km/h." in rule_prompt and "Người lưu trú." not in rule_prompt
    assert "Gió ≥ 30 km/h." in model.prompts[-1][1][1][1]


def test_a_failing_proposal_still_answers():
    model = FakeModel(_answers(rule_ids=()))
    model.answers["MissingProposals"] = None
    original = model.with_structured_output

    def with_structured_output(schema):
        if schema is pipeline.MissingProposals:
            return SimpleNamespace(invoke=lambda messages: (_ for _ in ()).throw(RuntimeError("hết hạn mức")))
        return original(schema)

    model.with_structured_output = with_structured_output
    generator = pipeline.run_agent("Hà Nội có mấy ngày nắng nóng?", [], model, lambda: CATALOG)
    events = []
    while True:
        try:
            events.append(next(generator))
        except StopIteration as finished:
            outcome = finished.value
            break

    failed = [data for name, data in events if name == "tool_end" and data["status"] == "error"]
    assert [data["name"] for data in failed] == ["propose_missing_items"]
    assert (outcome.missing, outcome.clarifications, outcome.answer) == (["expert_rule"], [], "Đã xác định.")


def test_an_empty_catalog_still_classifies_the_question_and_proposes_every_missing_kind():
    outcome, _, model = _run(_answers(undefined_concepts=("nắng nóng",)), catalog=SemanticCatalog())

    schemas = [schema for schema, _ in model.prompts]
    assert schemas == ["RewrittenQuestion", "GlossarySelection", "ExpertRuleSelection", "MissingProposals", "final"]
    assert outcome.missing == ["glossary", "metric", "expert_rule"]
    assert [draft["kind"] for draft in outcome.clarifications] == ["glossary", "expert_rule"]
    assert list(outcome.suggestions) == ["metric"]


def test_a_failing_step_reports_an_error_tool_end_and_stops():
    def failing_catalog():
        raise RuntimeError("Semantic Layer không phản hồi")

    model = FakeModel(_answers())
    generator = pipeline.run_agent("Câu hỏi", [], model, failing_catalog)
    events = [next(generator) for _ in range(4)]

    assert events[-1][0] == "tool_end" and events[-1][1]["status"] == "error"
    assert events[-1][1]["error"] == "Semantic Layer không phản hồi"
    with pytest.raises(RuntimeError):
        next(generator)


def test_history_keeps_the_last_three_turns_and_drops_malformed_messages():
    history = [{"role": "user", "content": f"câu {index}"} for index in range(10)]
    history += [{"role": "system", "content": "bỏ"}, {"role": "assistant", "content": "  "}, "rác"]

    kept = pipeline.recent_history(history)

    assert [message["content"] for message in kept] == [f"câu {index}" for index in range(4, 10)]
    assert pipeline.recent_history("không phải danh sách") == []


def test_rewrite_prompt_carries_the_conversation():
    history = [{"role": "user", "content": "Nhiệt độ ở Huế?"}, {"role": "assistant", "content": "Đã xác định."}]
    _, events, model = _run(_answers(), history=history)

    rewrite_prompt = model.prompts[0][1][1][1]
    assert "user: Nhiệt độ ở Huế?" in rewrite_prompt and "Câu hỏi mới nhất" in rewrite_prompt
    assert events[0][1]["arguments"]["history_turns"] == 1


def test_consumer_payloads_flatten_to_the_ids_the_agent_answers_with():
    metric = {
        "metric_id": 17, "metric_name": "max_temp", "verbose_name": "Nhiệt độ cao nhất", "unit": "°C",
        "business_definition": "Cao nhất.", "glossary_terms": [{"term_id": 3, "name": "Nắng nóng", "synonyms": []}],
    }
    term = {"term_id": 3, "canonical_name": "Nắng nóng", "definition": "Nóng.", "synonyms": ["oi bức"], "links": []}
    rule = {
        "id": 1, "name": "Ngày nắng nóng gay gắt", "dataset_id": 12, "column_names": {"92": "Nhiệt độ cao nhất (°C)"},
        "conditions": [{"field_ref": {"column_dictionary_id": 92}, "operator": "greater_than_or_equal", "value": 37}],
        "exceptions": [{"when": "dự báo", "outcome": "bỏ qua"}],
        "examples": [{"question": "Mấy ngày?", "intent": "đếm"}],
        "metric_ids": [17], "glossary_term_ids": [3],
    }
    catalog = flatten_catalog(
        {"datasets": [{"id": 12, "name": "fact", "metrics": [metric]}]}, {"terms": [term]}, {"rules": [rule]},
    )

    assert catalog.glossary_terms == [{"id": 3, "name": "Nắng nóng", "synonyms": ["oi bức"], "definition": "Nóng."}]
    assert catalog.metrics[0]["glossary_term_ids"] == [3] and catalog.metrics[0]["name"] == "Nhiệt độ cao nhất"
    assert catalog.expert_rules[0]["conditions"] == ["Nhiệt độ cao nhất (°C) greater_than_or_equal 37"]
    assert catalog.summary() == {
        "glossary_terms": ["Nắng nóng"], "metrics": ["Nhiệt độ cao nhất"], "expert_rules": ["Ngày nắng nóng gay gắt"],
    }
