import json
from datetime import date

import pytest
from test_agent_pipeline import CATALOG, FakeModel, FakeSemanticLayer

from text_to_bi.superset_ai_agent.modules.chat import pipeline
from text_to_bi.superset_ai_agent.modules.chat.semantic_source import DataModelSources, MetricQueryError

AGGREGATE = {
    "id": 12, "name": "fact_tong_hop_thoi_tiet", "label": "Tổng hợp thời tiết",
    "columns": [
        {"name": "ngay", "label": "Ngày", "type": "DATE", "temporal": True, "groupby": True, "filterable": True},
        {"name": "thanh_pho_key", "type": "INTEGER", "groupby": True, "filterable": True},
        {"name": "loai_quan_sat", "label": "Loại quan sát", "type": "VARCHAR(30)", "values": ["DU_BAO_NGAY", "HIEN_TAI"]},
        {"name": "gio_giat_toi_da_kmh", "label": "Gió giật tối đa", "unit": "km/h", "groupby": True,
         "filterable": True},
    ],
    "labelled_values": [{"column": "thanh_pho_key", "label": "Thành phố", "values": [{"value": 1, "label": "Ha Noi"}]}],
    "metrics": [{"metric_id": 23, "metric_name": "toc_do_gio_toi_da", "expression": "MAX(toc_do_gio_toi_da_kmh)",
                 "state": "approved"}],
}
LOADS = {
    "id": 14, "name": "tb_lan_nap_du_lieu", "dataset_type": "base",
    "columns": [{"name": "lan_nap_id", "type": "BIGINT"}, {"name": "trang_thai", "type": "VARCHAR(20)"}],
}
SOURCES = DataModelSources(aggregates=[AGGREGATE], bases=[LOADS])
GUST = "MAX(CASE WHEN loai_quan_sat = 'DU_BAO_NGAY' THEN gio_giat_toi_da_kmh END)"


class FakeBuilder:
    def __init__(self, provisional=True, error=None, proposes=True):
        self.provisional, self.error = provisional, error
        self.created, self.proposed = [], []
        self.reads = 0
        self.propose_dataset = self._propose if proposes else None

    def _propose(self, draft):
        self.proposed.append(draft)
        return {"id": 5, "name": draft["name"], "label": draft["label"], "status": "pending"}

    def load_sources(self):
        self.reads += 1
        return SOURCES

    def create_metric(self, draft):
        self.created.append(draft)
        if self.error:
            raise self.error
        metric = {
            "dataset_id": draft["dataset_id"], "metric_id": 41, "metric_name": draft["metric_name"],
            "verbose_name": draft["label"], "business_definition": draft["definition"], "unit": draft["unit"],
        }
        return metric, self.provisional


def _understanding(**changes):
    values = {
        "standalone_question": "Gió giật mạnh nhất ở các thành phố tuần trước là bao nhiêu?",
        "question_kind": "quantitative", "metrics": [], "query": None, "reason": "r",
    }
    return pipeline.Understanding(**{**values, **changes})


def _draft(**changes):
    query = pipeline.QueryPlan(
        dataset_id=12, metric_ids=[], dimensions=["thanh_pho_key"],
        filters=[
            {"column": "ngay", "operator": ">=", "value": "2026-10-19", "source": "time"},
            {"column": "ngay", "operator": "<=", "value": "2026-10-25", "source": "time"},
        ],
        order_by={"metric_id": 0, "direction": "desc"}, limit=3, presentation="bar",
    )
    values = {
        "dataset_id": 12, "metric_name": "gio_giat_toi_da", "label": "Gió giật tối đa", "expression": GUST,
        "definition": "Tốc độ gió giật lớn nhất trong ngày.", "unit": "km/h", "query": query, "reason": "r",
    }
    return pipeline.MetricDraft(**{**values, **changes})


def _run(answers, builder, run_metric=None):
    model = FakeModel(answers)
    events = []
    generator = pipeline.run_agent(
        "Gió giật mạnh nhất tuần trước?", [], model, lambda: CATALOG, (),
        run_metric=run_metric or FakeSemanticLayer(), today=date(2026, 10, 26), builder=builder,
    )
    while True:
        try:
            events.append(next(generator))
        except StopIteration as finished:
            return finished.value, events, model


def _steps(events):
    return [data["name"] for name, data in events if name == "tool_start"]


def _final_context(model):
    final = next(messages for name, messages in model.prompts if name == "final")
    return json.loads(final[1][1].split("```json\n", 1)[1].rsplit("\n```", 1)[0])


def test_a_question_only_missing_a_metric_builds_one_on_an_aggregate_and_answers_provisionally():
    builder, semantic_layer = FakeBuilder(), FakeSemanticLayer()
    answers = {"Understanding": _understanding(), "MetricDraft": _draft()}

    outcome, events, model = _run(answers, builder, semantic_layer)

    assert _steps(events) == [
        "load_semantic_catalog", "understand_question", "load_data_model", "draft_metric", "create_metric",
        "query_metrics",
    ]
    assert builder.created[0]["expression"] == GUST
    assert builder.created[0]["question"] == "Gió giật mạnh nhất ở các thành phố tuần trước là bao nhiêu?"
    dataset_id, metric_id, query = semantic_layer.calls[0]
    assert (dataset_id, metric_id, query["dimensions"]) == (12, 41, ["thanh_pho_key"])
    assert outcome.result["provisional"] is True and outcome.result["order"]["metric_name"] == "gio_giat_toi_da"
    sentence = "".join(part.get("label") or part["text"] for part in outcome.result["formula"]["parts"])
    assert sentence == "Giá trị lớn nhất của Gió giật tối đa, chỉ tính các dòng có Loại quan sát là “DU_BAO_NGAY”"
    assert outcome.result["formula"]["expression"] == GUST and "doubt" in outcome.result
    assert outcome.metrics == [{"dataset_id": 12, "metric_id": 41, "name": "Gió giật tối đa", "provisional": True}]
    # Until an administrator approves it the metric is still a gap, though the asker got an answer.
    assert outcome.missing == ["metric"] and outcome.status == "needs_review"
    context = _final_context(model)
    assert context["missing"] == [] and context["result"]["provisional"] is True
    assert context["metrics"][0]["definition"] == "Tốc độ gió giật lớn nhất trong ngày."
    draft_prompt = next(messages for name, messages in model.prompts if name == "MetricDraft")[1][1]
    assert "MAX(toc_do_gio_toi_da_kmh)" in draft_prompt


def test_a_reused_approved_metric_answers_as_an_ordinary_one():
    outcome, _, _ = _run({"Understanding": _understanding(), "MetricDraft": _draft()}, FakeBuilder(provisional=False))
    assert outcome.result["provisional"] is False and outcome.status == "resolved"
    assert "formula" not in outcome.result and "doubt" not in outcome.result


def test_a_missing_term_is_asked_back_before_the_data_model_is_touched():
    builder = FakeBuilder()
    answers = {
        "Understanding": _understanding(undefined_concepts=["gió giật"]),
        "MissingProposals": pipeline.MissingProposals(),
    }
    _, events, _ = _run(answers, builder)
    assert "load_data_model" not in _steps(events) and builder.reads == 0


def test_no_aggregate_column_for_it_falls_back_to_a_proposal_for_administrators():
    answers = {
        "Understanding": _understanding(),
        "MetricDraft": pipeline.MetricDraft(dataset_id=None, reason="Không có cột đo chỉ số UV."),
        "MissingProposals": pipeline.MissingProposals(
            metric=pipeline.MetricProposal(name="Chỉ số UV", definition="UV lớn nhất.", unit=""),
        ),
    }
    outcome, events, _ = _run(answers, FakeBuilder(proposes=False))
    assert _steps(events)[-2:] == ["draft_metric", "propose_missing_items"]
    assert outcome.suggestions["metric"]["name"] == "Chỉ số UV" and outcome.result is None


def test_a_metric_the_semantic_layer_refuses_becomes_a_proposal_with_the_reason():
    builder = FakeBuilder(error=MetricQueryError("Một metric cùng công thức đang chờ quản trị viên xử lý."))
    outcome, events, _ = _run({"Understanding": _understanding(), "MetricDraft": _draft()}, builder)
    assert "propose_missing_items" not in _steps(events)
    assert outcome.query_error.startswith("Một metric cùng công thức")
    assert outcome.suggestions == {
        "metric": {"name": "Gió giật tối đa", "definition": "Tốc độ gió giật lớn nhất trong ngày.", "unit": "km/h"},
    }


LOAD_DRAFT = pipeline.DatasetDraft(
    name="lan_nap_theo_ngay", label="Lần nạp dữ liệu theo ngày", description="Mỗi dòng là một lần nạp.",
    sql="SELECT lan_nap_id, CAST(bat_dau_luc AS DATE) AS ngay FROM public.tb_lan_nap_du_lieu",
    metric=pipeline.DatasetMetricDraft(
        metric_name="so_lan_nap", label="Số lần nạp", expression="COUNT(lan_nap_id)", definition="Đếm lần nạp.",
    ),
)


def test_with_no_aggregate_for_it_a_dataset_over_base_tables_goes_to_administrators_and_nothing_runs():
    builder, semantic_layer = FakeBuilder(), FakeSemanticLayer()
    answers = {
        "Understanding": _understanding(standalone_question="Tuần trước có bao nhiêu lần nạp dữ liệu?"),
        "MetricDraft": pipeline.MetricDraft(dataset_id=None, reason="Bảng tổng hợp không có lần nạp."),
        "DatasetDraft": LOAD_DRAFT,
    }

    outcome, events, model = _run(answers, builder, semantic_layer)

    assert _steps(events)[2:] == ["load_data_model", "draft_metric", "draft_dataset", "propose_dataset"]
    assert builder.proposed[0]["sql"] == LOAD_DRAFT.sql and builder.proposed[0]["metric"]["metric_name"] == "so_lan_nap"
    assert builder.proposed[0]["question"] == "Tuần trước có bao nhiêu lần nạp dữ liệu?"
    assert semantic_layer.calls == [] and outcome.result is None and builder.created == []
    assert outcome.suggestions["dataset"]["proposal_id"] == 5 and outcome.missing == ["metric"]
    draft_prompt = next(messages for name, messages in model.prompts if name == "DatasetDraft")[1][1]
    assert "tb_lan_nap_du_lieu" in draft_prompt and "fact_tong_hop_thoi_tiet" not in draft_prompt
    assert _final_context(model)["suggestions"]["dataset"]["label"] == "Lần nạp dữ liệu theo ngày"


def test_a_dataset_the_semantic_layer_refuses_still_reaches_administrators_as_a_metric_proposal():
    builder = FakeBuilder()
    builder.propose_dataset = lambda draft: (_ for _ in ()).throw(MetricQueryError("SQL chỉ được đọc dữ liệu."))
    answers = {
        "Understanding": _understanding(),
        "MetricDraft": pipeline.MetricDraft(dataset_id=None),
        "DatasetDraft": LOAD_DRAFT,
        "MissingProposals": pipeline.MissingProposals(
            metric=pipeline.MetricProposal(name="Số lần nạp", definition="Đếm lần nạp.", unit="lần"),
        ),
    }
    outcome, events, _ = _run(answers, builder)
    assert _steps(events)[-1] == "propose_missing_items"
    assert outcome.query_error == "SQL chỉ được đọc dữ liệu." and outcome.suggestions["metric"]["name"] == "Số lần nạp"


class ZeroSemanticLayer(FakeSemanticLayer):
    """Answers zero for the asked week; over all the data, `whole` decides whether the metric ever gives anything."""

    def __init__(self, whole):
        super().__init__()
        self.whole = whole

    def __call__(self, dataset_id, metric_id, query):
        self.calls.append((dataset_id, metric_id, query))
        value = self.whole if not query["filters"] else 0
        return {"rows": [{"gio_giat_toi_da": value}], "truncated": False}


@pytest.mark.parametrize(("whole", "doubt"), [(0, "zero"), (72.5, None)])
def test_a_provisional_zero_is_doubted_only_when_the_metric_gives_nothing_over_all_the_data(whole, doubt):
    draft = _draft(query=_draft().query.model_copy(update={"dimensions": [], "order_by": None, "limit": None}))
    semantic_layer = ZeroSemanticLayer(whole)
    outcome, _, _ = _run({"Understanding": _understanding(), "MetricDraft": draft}, FakeBuilder(), semantic_layer)
    assert outcome.result["doubt"] == doubt
    assert semantic_layer.calls[-1][2] == {"dimensions": [], "filters": []}
