from text_to_bi.text_to_bi_code.agent_package.context.contract import (
    BIContract, ChartResolve, DataMetric, DataResolve, DataSource, UserIntent,
)
from text_to_bi.text_to_bi_code.agent_package.context.dashboard import (
    ColumnDTO, DatasetDTO, MetricDTO,
)
from text_to_bi.text_to_bi_code.agent_package.tools.validate_bi_contract import BIContractValidator


def dataset(dataset_id=1):
    return DatasetDTO(
        id=dataset_id,
        columns=[
            ColumnDTO(column_name="month", type="DATE", is_dttm=True),
            ColumnDTO(column_name="revenue", type="DECIMAL"),
            ColumnDTO(column_name="region", type="VARCHAR"),
        ],
        metrics=[MetricDTO(metric_name="gross_revenue", allowed_aggregations=["sum"])],
    )


def contract(*, sources=None, combination="single", chart=None):
    return BIContract(
        user_intent=UserIntent(objective="So sánh doanh thu theo tháng"),
        data_resolve=DataResolve(sources=sources or [DataSource(dataset_id=1, metrics=[DataMetric(name="revenue", aggregation="sum")], group_by=["month"])], combination=combination, time_grain="month" if any(s.group_by for s in (sources or [DataSource(dataset_id=1, group_by=["month"])])) else None),
        chart_resolve=chart or ChartResolve(mode="chart", data_shape="aggregated", data_grain="mỗi tháng", x_axis="month", y_axis=["revenue"], title="Doanh thu theo tháng"),
    )


def errors(plan, datasets=None, authorized=None, **kwargs):
    return {item["code"] for item in BIContractValidator().validate(plan, datasets or [dataset()], set(authorized or {1}), **kwargs)}


def test_single_dataset_aggregation_timeseries_and_categorical_comparison():
    assert errors(contract()) == set()
    categorical = contract(sources=[DataSource(dataset_id=1, metrics=[DataMetric(name="gross_revenue")], group_by=["region"])], chart=ChartResolve(mode="chart", data_shape="aggregated", data_grain="mỗi vùng", x_axis="region", y_axis=["gross_revenue"]))
    assert errors(categorical) == set()


def test_single_value_plan():
    plan = contract(sources=[DataSource(dataset_id=1, metrics=[DataMetric(name="gross_revenue")])], chart=ChartResolve(mode="single_value", data_shape="scalar", data_grain="một giá trị", y_axis=["gross_revenue"]))
    assert errors(plan) == set()


def test_unauthorized_dataset_column_metric_aggregation_chart_and_output_field():
    assert "unauthorized_dataset" in errors(contract(sources=[DataSource(dataset_id=2, metrics=[DataMetric(name="revenue", aggregation="sum")])]), authorized={1})
    assert "missing_column" in errors(contract(sources=[DataSource(dataset_id=1, group_by=["absent"], metrics=[DataMetric(name="revenue", aggregation="sum")])]))
    assert "missing_metric" in errors(contract(sources=[DataSource(dataset_id=1, metrics=[DataMetric(name="missing")])]))
    assert "invalid_aggregation" in errors(contract(sources=[DataSource(dataset_id=1, metrics=[DataMetric(name="region", aggregation="sum")])]))
    assert "unsupported_viz_type" in errors(contract(chart=ChartResolve(mode="chart", viz_type="not_supported", data_shape="aggregated", data_grain="tháng", x_axis="month", y_axis=["revenue"])), capabilities={"viz_types": ["table"]})
    assert "missing_output_field" in errors(contract(chart=ChartResolve(data_shape="aggregated", data_grain="tháng", x_axis="other", y_axis=["revenue"])))


def test_multiple_independent_and_unverified_join():
    sources = [DataSource(dataset_id=1, metrics=[DataMetric(name="revenue", aggregation="sum")], group_by=["month"]), DataSource(dataset_id=2, metrics=[DataMetric(name="revenue", aggregation="sum")], group_by=["month"])]
    plan = contract(sources=sources, combination="independent")
    assert "missing_combination_key" in errors(plan, datasets=[dataset(), dataset(2)])
    joined = contract(sources=sources, combination="join")
    assert "unverified_join" in errors(joined, datasets=[dataset(), dataset(2)])


def test_verified_join_can_be_supplied():
    sources = [DataSource(dataset_id=1, metrics=[DataMetric(name="revenue", aggregation="sum")], group_by=["month"]), DataSource(dataset_id=2, metrics=[DataMetric(name="revenue", aggregation="sum")], group_by=["month"])]
    plan = contract(sources=sources, combination="join")
    assert "unverified_join" not in errors(plan, datasets=[dataset(), dataset(2)], verified_relationships=[{"verified": True, "dataset_ids": [1, 2]}])


def test_repair_loop_success_and_exhaustion(monkeypatch):
    from text_to_bi.text_to_bi_code.agent_package import bi_planning

    valid = contract()
    class Agent:
        def __init__(self, values): self.values = iter(values)
        def invoke(self, *args, **kwargs):
            from types import SimpleNamespace
            return {"structured_response": next(self.values), "messages": [SimpleNamespace(name="validate_bi_contract")]}
    monkeypatch.setattr(bi_planning, "get_dashboard_datasets", lambda *_: [dataset()])
    monkeypatch.setattr(bi_planning, "superset_client", object())
    context = {"dashboard_id": 1, "allowed_dataset_ids": [1]}
    invalid = contract(sources=[DataSource(dataset_id=99)])
    repaired = bi_planning.plan_bi("doanh thu", context, agent=Agent([invalid, valid]))
    assert repaired.success and repaired.attempts == 2
    failed = bi_planning.plan_bi("doanh thu", context, agent=Agent([invalid, invalid]), max_repairs=1)
    assert not failed.success and failed.attempts == 2 and failed.errors


def test_missing_metadata_fails_explicitly(monkeypatch):
    from text_to_bi.text_to_bi_code.agent_package import bi_planning
    monkeypatch.setattr(bi_planning, "get_dashboard_datasets", lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    result = bi_planning.plan_bi("doanh thu", {"dashboard_id": 1, "allowed_dataset_ids": [1]})
    assert not result.success and result.errors[0]["code"] == "metadata_unavailable"
