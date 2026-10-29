from datetime import date
from types import SimpleNamespace

import pytest

from text_to_bi.superset_ai_agent.modules.chat.services import pipeline
from text_to_bi.superset_ai_agent.modules.semantic_layer.services.catalog import (
    SemanticCatalog,
    flatten_catalog,
    rule_filters,
)


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


DATASET = {
    "id": 12,
    "name": "fact_tong_hop_thoi_tiet",
    "columns": [
        {"name": "ngay", "label": "Ngày", "type": "DATE", "temporal": True, "groupby": True, "filterable": True},
        {"name": "thanh_pho_key", "type": "INTEGER", "groupby": True, "filterable": True},
        {"name": "nhiet_do_cao_nhat_c", "type": "NUMERIC(5,2)", "groupby": True, "filterable": True},
        {"name": "ten_thanh_pho", "type": "TEXT", "groupby": True, "filterable": False},
    ],
    "labelled_values": [{"column": "thanh_pho_key", "label": "Thành phố", "values": [{"value": 1, "label": "Ha Noi"}]}],
}
CATALOG = SemanticCatalog(
    glossary_terms=[{"id": 3, "name": "Nắng nóng", "synonyms": ["oi bức"], "definition": "Nóng."}],
    metrics=[{
        "dataset_id": 12, "metric_id": 17, "name": "Nhiệt độ cao nhất", "metric_name": "nhiet_do_cao_nhat",
        "unit": "°C", "glossary_term_ids": [3],
    }],
    expert_rules=[{
        "id": 1, "name": "Ngày nắng nóng gay gắt", "dataset_id": 12, "metric_ids": [17], "glossary_term_ids": [3],
        "conditions": ["Nhiệt độ cao nhất >= 37"],
        "filters": [{"column": "nhiet_do_cao_nhat_c", "operator": ">=", "value": 37}],
    }],
    datasets=[DATASET],
)
TODAY = date(2026, 10, 26)


class FakeSemanticLayer:
    """Runs a metric by echoing one row per day, and records each request."""

    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, dataset_id, metric_id, query):
        self.calls.append((dataset_id, metric_id, query))
        if self.error:
            raise self.error
        return {
            "rows": [
                {"ngay": "Tue, 20 Oct 2026 00:00:00 GMT", "nhiet_do_cao_nhat": "37.5000"},
                {"ngay": "Mon, 19 Oct 2026 00:00:00 GMT", "nhiet_do_cao_nhat": "38.0000"},
            ],
            "truncated": False,
        }


def _run(answers, catalog=CATALOG, history=(), user_definitions=(), run_metric=None):
    model = FakeModel(answers)
    events = []
    generator = pipeline.run_agent(
        "Hà Nội có mấy ngày như vậy?", list(history), model, lambda: catalog, user_definitions,
        run_metric=run_metric, today=TODAY,
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
WEEK_FILTERS = [
    {"column": "ngay", "operator": ">=", "value": "2026-10-19", "source": "time"},
    {"column": "ngay", "operator": "<=", "value": "2026-10-25", "source": "time"},
    {"column": "thanh_pho_key", "operator": "==", "value": "1", "source": "place"},
]


def _answers(
    term_ids=(3,), metrics=((12, 17),), rule_ids=(1,), question_kind="qualitative", proposals=PROPOSALS,
    undefined_concepts=(), user_definition_ids=(), user_rule_ids=(), filters=WEEK_FILTERS, dimensions=("ngay",),
):
    query = {
        "dataset_id": 12, "metric_ids": [metric for _, metric in metrics], "dimensions": list(dimensions),
        "filters": list(filters), "presentation": "table", "scope": "Hà Nội, tuần trước",
    }
    return {
        "Understanding": pipeline.Understanding(
            standalone_question="Hà Nội có mấy ngày nắng nóng?",
            term_ids=list(term_ids), undefined_concepts=list(undefined_concepts),
            user_definition_ids=list(user_definition_ids),
            metrics=[pipeline.MetricReference(dataset_id=dataset, metric_id=metric) for dataset, metric in metrics],
            question_kind=question_kind, qualitative_concepts=["nắng nóng"], rule_ids=list(rule_ids),
            user_rule_ids=list(user_rule_ids), query=pipeline.QueryPlan(**query) if metrics else None, reason="r",
        ),
        "MissingProposals": proposals,
    }


def test_one_understanding_step_then_the_query_and_the_streamed_answer():
    semantic_layer = FakeSemanticLayer()
    outcome, events, model = _run(_answers(), run_metric=semantic_layer)

    names = [data["name"] for name, data in events if name == "tool_start"]
    assert names == ["load_semantic_catalog", "understand_question", "query_metrics"]
    assert [data["status"] for name, data in events if name == "tool_end"] == ["ok"] * 3
    assert [schema for schema, _ in model.prompts] == ["Understanding", "final"]
    understood = next(data for name, data in events if name == "tool_end" and data["name"] == "understand_question")
    assert understood["result"]["question_kind"] == "qualitative"
    assert understood["result"]["expert_rules"] == ["Ngày nắng nóng gay gắt"]
    assert "".join(data["text"] for name, data in events if name == "token") == "Đã xác định."
    assert outcome.rewritten_question == "Hà Nội có mấy ngày nắng nóng?"
    assert outcome.glossary_terms == [{"id": 3, "name": "Nắng nóng"}]
    assert outcome.metrics == [{"dataset_id": 12, "metric_id": 17, "name": "Nhiệt độ cao nhất"}]
    assert outcome.expert_rules == [{"id": 1, "name": "Ngày nắng nóng gay gắt"}]
    assert (outcome.status, outcome.missing, outcome.answer) == ("resolved", [], "Đã xác định.")


def test_the_rule_filters_come_from_the_rule_and_the_rows_are_cleaned():
    semantic_layer = FakeSemanticLayer()
    retyped_rule = {"column": "nhiet_do_cao_nhat_c", "operator": ">", "value": 1, "source": "expert_rule"}
    model_filters = WEEK_FILTERS + [retyped_rule]
    outcome, _, model = _run(_answers(filters=model_filters), run_metric=semantic_layer)

    ((dataset_id, metric_id, body),) = semantic_layer.calls
    assert (dataset_id, metric_id, body["dimensions"]) == (12, 17, ["ngay"])
    assert body["filters"] == [
        {"column": "nhiet_do_cao_nhat_c", "operator": ">=", "value": 37},
        {"column": "ngay", "operator": ">=", "value": "2026-10-19"},
        {"column": "ngay", "operator": "<=", "value": "2026-10-25"},
        {"column": "thanh_pho_key", "operator": "==", "value": 1},
    ]
    assert outcome.result["rows"] == [
        {"ngay": "2026-10-19", "nhiet_do_cao_nhat": 38},
        {"ngay": "2026-10-20", "nhiet_do_cao_nhat": 37.5},
    ]
    assert outcome.result["metrics"] == [
        {
            "name": "nhiet_do_cao_nhat", "label": "Nhiệt độ cao nhất", "unit": "°C", "format": None,
            "compared_name": None,
        },
    ]
    assert [item["source"] for item in outcome.result["filters"]] == ["expert_rule", "time", "time", "place"]
    final_prompt = model.prompts[-1][1][1][1]
    assert '"row_count": 2' in final_prompt and '"today": "2026-10-26"' in final_prompt


def test_a_query_the_catalog_does_not_allow_becomes_a_query_error():
    semantic_layer = FakeSemanticLayer()
    bad_filter = [{"column": "ten_thanh_pho", "operator": "==", "value": "Hà Nội", "source": "place"}]
    outcome, events, model = _run(_answers(filters=bad_filter), run_metric=semantic_layer)

    assert semantic_layer.calls == []
    assert outcome.result is None and "ten_thanh_pho" in outcome.query_error
    assert "query_metrics" not in [data["name"] for name, data in events if name == "tool_start"]
    assert "query_error" in model.prompts[-1][1][1][1]


def test_a_refused_metric_query_is_reported_and_still_answered():
    from text_to_bi.superset_ai_agent.modules.semantic_layer.exceptions import SemanticLayerRefusedError

    semantic_layer = FakeSemanticLayer(error=SemanticLayerRefusedError("Metric chưa được duyệt."))
    outcome, events, _ = _run(_answers(), run_metric=semantic_layer)

    failed = [data for name, data in events if name == "tool_end" and data["status"] == "error"]
    assert [data["name"] for data in failed] == ["query_metrics"]
    assert (outcome.query_error, outcome.answer) == ("Metric chưa được duyệt.", "Đã xác định.")


def test_ids_the_model_invents_or_repeats_are_dropped():
    outcome, _, _ = _run(_answers(term_ids=(3, 3, 99), metrics=((12, 17), (12, 17), (12, 99)), rule_ids=(7,)))

    assert [term["id"] for term in outcome.glossary_terms] == [3]
    assert [metric["metric_id"] for metric in outcome.metrics] == [17]
    assert outcome.expert_rules == []
    assert (outcome.status, outcome.missing) == ("needs_review", ["expert_rule"])
    assert (outcome.clarifications, outcome.suggestions) == ([RULE_DRAFT], {})


def test_a_quantitative_question_needs_no_expert_rule():
    semantic_layer = FakeSemanticLayer()
    outcome, events, _ = _run(_answers(rule_ids=(1,), question_kind="quantitative"), run_metric=semantic_layer)

    assert (outcome.requires_expert_rule, outcome.expert_rules) == (False, [])
    assert (outcome.status, outcome.missing, outcome.suggestions) == ("resolved", [], {})
    assert "propose_missing_items" not in [data["name"] for name, data in events if name == "tool_start"]
    # The rule the model named is not applied to a quantitative question.
    assert [item["column"] for item in semantic_layer.calls[0][2]["filters"]] == ["ngay", "ngay", "thanh_pho_key"]


def test_the_understanding_prompt_carries_today_the_catalog_and_the_labelled_values():
    _, _, model = _run(_answers(term_ids=(), question_kind="quantitative"))

    prompt = model.prompts[0][1][1][1]
    assert '"today": "2026-10-26"' in prompt and "thứ Hai" in prompt
    assert all(text in prompt for text in ("Nhiệt độ cao nhất", "Nóng.", "Ngày nắng nóng gay gắt", "Ha Noi"))


def test_a_missing_term_or_rule_is_drafted_for_the_user_and_a_missing_metric_for_administrators():
    semantic_layer = FakeSemanticLayer()
    answers = _answers(term_ids=(), metrics=(), question_kind="quantitative", undefined_concepts=("lượng mưa",))
    outcome, events, model = _run(answers, run_metric=semantic_layer)

    assert outcome.missing == ["glossary", "metric"]
    assert outcome.clarifications == [GLOSSARY_DRAFT]
    assert outcome.suggestions == {"metric": {"name": "Tổng lượng mưa", "definition": "Cộng lượng mưa.", "unit": "mm"}}
    assert semantic_layer.calls == [] and outcome.result is None
    tool_end = next(data for name, data in events if name == "tool_end" and data["name"] == "propose_missing_items")
    assert list(tool_end["result"]) == ["clarifications", "metric"]
    final_prompt = model.prompts[-1][1][1][1]
    assert "Tổng lượng mưa" in final_prompt and "Bạn hiểu “lượng mưa” là gì?" in final_prompt


def test_definitions_the_user_confirmed_count_for_the_rest_of_the_conversation():
    user_definitions = [
        {"id": 5, "kind": "glossary", "name": "Khách du lịch", "concept": "khách", "definition": "Người lưu trú."},
        {"id": 6, "kind": "expert_rule", "name": "Ngày nóng", "concept": "nóng", "definition": "Cao nhất ≥ 35 °C."},
    ]
    user_filter = {"column": "nhiet_do_cao_nhat_c", "operator": ">=", "value": "35", "source": "user_definition"}
    filters = WEEK_FILTERS + [user_filter]
    answers = _answers(rule_ids=(), user_definition_ids=(5, 99), user_rule_ids=(6,), filters=filters)
    semantic_layer = FakeSemanticLayer()
    outcome, _, model = _run(answers, user_definitions=user_definitions, run_metric=semantic_layer)

    assert (outcome.status, outcome.missing, outcome.clarifications) == ("resolved", [], [])
    assert [item["id"] for item in outcome.user_definitions] == [5, 6]
    assert "Cao nhất ≥ 35 °C." in model.prompts[0][1][1][1]
    assert semantic_layer.calls[0][2]["filters"][-1] == {"column": "nhiet_do_cao_nhat_c", "operator": ">=", "value": 35}
    assert outcome.result["filters"][-1]["source"] == "user_definition"


def test_a_failing_proposal_still_answers():
    model = FakeModel(_answers(rule_ids=()))
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
    answers = _answers(undefined_concepts=("nắng nóng",), term_ids=(), metrics=(), rule_ids=())
    outcome, _, model = _run(answers, catalog=SemanticCatalog())

    assert [schema for schema, _ in model.prompts] == ["Understanding", "MissingProposals", "final"]
    assert outcome.missing == ["glossary", "metric", "expert_rule"]
    assert [draft["kind"] for draft in outcome.clarifications] == ["glossary", "expert_rule"]
    assert list(outcome.suggestions) == ["metric"]


def test_a_failing_step_reports_an_error_tool_end_and_stops():
    def failing_catalog():
        raise RuntimeError("Semantic Layer không phản hồi")

    model = FakeModel(_answers())
    generator = pipeline.run_agent("Câu hỏi", [], model, failing_catalog)
    events = [next(generator) for _ in range(2)]

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


def test_the_understanding_prompt_carries_the_conversation():
    history = [{"role": "user", "content": "Nhiệt độ ở Huế?"}, {"role": "assistant", "content": "Đã xác định."}]
    _, events, model = _run(_answers(), history=history)

    prompt = model.prompts[0][1][1][1]
    assert "user: Nhiệt độ ở Huế?" in prompt and "Câu hỏi mới nhất" in prompt
    assert events[2][1]["arguments"]["history_turns"] == 1


def test_consumer_payloads_flatten_to_the_ids_the_agent_answers_with():
    metric = {
        "metric_id": 17, "metric_name": "max_temp", "verbose_name": "Nhiệt độ cao nhất", "unit": "°C",
        "business_definition": "Cao nhất.", "glossary_terms": [{"term_id": 3, "name": "Nắng nóng", "synonyms": []}],
    }
    term = {"term_id": 3, "canonical_name": "Nắng nóng", "definition": "Nóng.", "synonyms": ["oi bức"], "links": []}
    rule = {
        "id": 1, "name": "Ngày nắng nóng gay gắt", "dataset_id": 12, "column_names": {"92": "Nhiệt độ cao nhất (°C)"},
        "condition_columns": {"92": "nhiet_do_cao_nhat_c"},
        "conditions": [{"field_ref": {"column_dictionary_id": 92}, "operator": "greater_than_or_equal", "value": 37}],
        "exceptions": [{"when": "dự báo", "outcome": "bỏ qua"}],
        "examples": [{"question": "Mấy ngày?", "intent": "đếm"}],
        "metric_ids": [17], "glossary_term_ids": [3],
    }
    dimension = {"name": "ngay", "label": "Ngày", "type": "DATE", "temporal": True, "groupby": True, "filterable": True}
    members = {12: {"dimensions": [{
        "key_column": "thanh_pho_key", "label_column": "ten_thanh_pho", "label": "Thành phố",
        "members": [{"value": 1, "label": "Ha Noi"}],
    }]}}
    catalog = flatten_catalog(
        {"datasets": [{"id": 12, "name": "fact", "metrics": [metric], "dimensions": [dimension]}]},
        {"terms": [term]}, {"rules": [rule]}, members,
    )

    assert catalog.glossary_terms == [{"id": 3, "name": "Nắng nóng", "synonyms": ["oi bức"], "definition": "Nóng."}]
    assert catalog.metrics[0]["glossary_term_ids"] == [3] and catalog.metrics[0]["name"] == "Nhiệt độ cao nhất"
    assert catalog.expert_rules[0]["conditions"] == ["Nhiệt độ cao nhất (°C) greater_than_or_equal 37"]
    assert catalog.expert_rules[0]["filters"] == [{"column": "nhiet_do_cao_nhat_c", "operator": ">=", "value": 37}]
    assert catalog.datasets == [{
        "id": 12, "name": "fact", "columns": [dimension],
        "labelled_values": [
            {"column": "thanh_pho_key", "label": "Thành phố", "values": [{"value": 1, "label": "Ha Noi"}]},
        ],
        "time_ranges": [],
    }]
    assert catalog.summary() == {
        "glossary_terms": ["Nắng nóng"], "metrics": ["Nhiệt độ cao nhất"], "expert_rules": ["Ngày nắng nóng gay gắt"],
    }


def test_a_rule_condition_no_filter_can_express_has_no_filters():
    rule = {
        "condition_columns": {"92": "ghi_chu"},
        "conditions": [{"field_ref": {"column_dictionary_id": 92}, "operator": "contains", "value": "bão"}],
    }

    assert rule_filters(rule) is None
    assert rule_filters({"conditions": [{"field_ref": {"column_dictionary_id": 5}, "operator": "equals"}]}) is None


def test_a_user_definition_with_stored_conditions_is_queried_with_them():
    stored = {"dataset_id": 12, "filters": [{"column": "nhiet_do_cao_nhat_c", "operator": ">=", "value": 35}]}
    user_definitions = [
        {"id": 6, "kind": "expert_rule", "name": "Ngày nóng", "concept": "nóng", "definition": "Từ 35 °C.",
         "conditions": stored},
    ]
    retyped = {"column": "nhiet_do_cao_nhat_c", "operator": ">=", "value": "30", "source": "user_definition"}
    answers = _answers(rule_ids=(), user_rule_ids=(6,), filters=WEEK_FILTERS + [retyped])
    semantic_layer = FakeSemanticLayer()
    _, _, model = _run(answers, user_definitions=user_definitions, run_metric=semantic_layer)

    sent = semantic_layer.calls[0][2]["filters"]
    assert sent[0] == {"column": "nhiet_do_cao_nhat_c", "operator": ">=", "value": 35}
    assert [item["value"] for item in sent if item["column"] == "nhiet_do_cao_nhat_c"] == [35]
    assert '"conditions"' in model.prompts[0][1][1][1]
