import json
from pathlib import Path

import pytest

from text_to_bi.superset_ai_agent.modules.schema_link.exceptions import NoJoinPathError
from text_to_bi.superset_ai_agent.modules.schema_link.services.analysis import analyze
from text_to_bi.superset_ai_agent.modules.schema_link.services.graph import FANOUT_COST, SchemaGraph
from text_to_bi.superset_ai_agent.modules.schema_link.services.paths import (
    join_tree,
    shortest_path_tree,
    steiner_tree,
)

WEATHER = json.loads((Path(__file__).parent / "fixtures" / "schema_graph_weather.json").read_text(encoding="utf-8"))
VALUES, OBSERVATIONS, CITIES, INDICATORS, DAYS, LOADS = 13, 15, 10, 6, 8, 14
HANOI_HOURLY_TEMPERATURE = {
    "measures": [{"indicator": "nhiet_do_c"}],
    "group_by": [{"dataset_id": OBSERVATIONS, "column": "thoi_diem_quan_sat", "time_grain": "hour"}],
    "filters": [
        {"dataset_id": CITIES, "column": "ten_thanh_pho", "operator": "==", "value": "Ha Noi"},
        {"dataset_id": OBSERVATIONS, "column": "thoi_diem_quan_sat", "operator": "==", "value": "2026-10-25"},
    ],
    "row_kinds": [{"dataset_id": OBSERVATIONS, "value": "DU_BAO_GIO"}],
}


def _graph(tables, edges):
    """A small graph: `tables` as IDs, `edges` as (id, from, to) foreign keys, many to one unless a fourth item says."""
    return SchemaGraph.from_payload({
        "database": {"dialect": "postgresql"},
        "tables": [{"dataset_id": table, "table": f"t{table}", "columns": []} for table in tables],
        "edges": [
            {"id": edge[0], "from": {"dataset_id": edge[1], "column": f"k{edge[2]}"},
             "to": {"dataset_id": edge[2], "column": "id"}, "cardinality": edge[3] if len(edge) > 3 else "many_to_one"}
            for edge in edges
        ],
    })


def _path(tree):
    return [(step.edge.id, step.forward) for step in tree.steps]


def test_dijkstra_from_the_root_joins_the_temperature_question_in_three_steps():
    graph = SchemaGraph.from_payload(WEATHER)

    tree = join_tree(graph, VALUES, [VALUES, OBSERVATIONS, CITIES, INDICATORS])

    assert tree.algorithm == "dijkstra" and tree.cost == 3 and not tree.fanout
    assert [(graph.table_name(step.start), graph.table_name(step.end)) for step in tree.steps] == [
        ("tb_gia_tri_quan_sat", "tb_quan_sat_thoi_tiet"),
        ("tb_gia_tri_quan_sat", "dm_chi_so_thoi_tiet"),
        ("tb_quan_sat_thoi_tiet", "dm_thanh_pho"),
    ]
    assert tree.alternatives == {}


def test_two_equal_paths_are_reported_as_alternatives_with_the_chosen_one_first():
    # 1 reaches 4 through 2 or through 3, at the same cost.
    graph = _graph([1, 2, 3, 4], [(10, 1, 2), (11, 1, 3), (12, 2, 4), (13, 3, 4)])

    tree = shortest_path_tree(graph, 1, [1, 4])

    assert tree.cost == 2 and tree.alternatives == {4: [[10, 12], [11, 13]]}


def test_a_table_reached_only_against_a_key_falls_back_to_a_steiner_tree_that_fans_out():
    # The root 1 points to 2; table 3 points to 2 as well, so reaching 3 walks 2 → 3 against its key.
    graph = _graph([1, 2, 3], [(20, 1, 2), (21, 3, 2)])

    assert shortest_path_tree(graph, 1, [1, 3]) is None
    tree = join_tree(graph, 1, [1, 3])
    assert tree.algorithm == "steiner" and tree.fanout and tree.cost == 1 + FANOUT_COST
    assert _path(tree) == [(20, True), (21, False)]


def test_a_one_to_one_edge_is_walked_either_way_without_fanning_out():
    graph = _graph([1, 2], [(30, 2, 1, "one_to_one")])

    tree = join_tree(graph, 1, [1, 2])

    assert tree.algorithm == "dijkstra" and not tree.fanout and _path(tree) == [(30, False)]


def test_dreyfus_wagner_shares_a_hub_that_separate_shortest_paths_would_not():
    # From 1, tables 5 and 6 are each 2 steps away directly (via 2 and 3, against their keys), or 1 step from hub 4.
    graph = _graph([1, 2, 3, 4, 5, 6], [
        (40, 2, 1), (41, 5, 2), (42, 3, 1), (43, 6, 3),
        (44, 4, 1), (45, 5, 4), (46, 6, 4),
    ])

    tree = steiner_tree(graph, 1, [1, 5, 6])

    assert tree.cost == 3 * FANOUT_COST and {step.edge.id for step in tree.steps} == {44, 45, 46}


def test_a_table_no_approved_relationship_reaches_raises_no_join_path():
    graph = _graph([1, 2, 3], [(50, 1, 2)])

    with pytest.raises(NoJoinPathError) as raised:
        join_tree(graph, 1, [1, 3])
    assert raised.value.unreachable == [3]


def test_the_temperature_goal_becomes_sql_over_base_tables():
    trace = analyze(HANOI_HOURLY_TEMPERATURE, SchemaGraph.from_payload(WEATHER))

    assert trace["status"] == "ok", trace["message"]
    goal = trace["stages"]["goal"]
    assert goal["measures"][0]["column"] == "gia_tri_so" and goal["measures"][0]["aggregation"] == "AVG"
    assert [item["column"] for item in goal["filters"]] == ["ma_chi_so", "ten_thanh_pho", "thoi_diem_quan_sat"]
    assert trace["stages"]["nodes"]["root"] == VALUES
    assert trace["stages"]["path"]["algorithm"] == "dijkstra" and trace["stages"]["path"]["cost"] == 3
    sql = " ".join(trace["sql"].split())
    assert 'FROM "public"."tb_gia_tri_quan_sat" AS t0' in sql
    assert 'JOIN "public"."tb_quan_sat_thoi_tiet" AS t1 ON "t0"."quan_sat_id" = "t1"."quan_sat_id"' in sql
    assert "AVG(\"t0\".\"gia_tri_so\") AS \"nhiet_do_c\"" in sql
    assert "DATE_TRUNC('hour', \"t1\".\"thoi_diem_quan_sat\")" in sql
    assert "\"t1\".\"thoi_diem_quan_sat\" >= '2026-10-25' AND \"t1\".\"thoi_diem_quan_sat\" < '2026-10-26'" in sql
    assert "\"t1\".\"loai_quan_sat\" = 'DU_BAO_GIO'" in sql and sql.endswith("LIMIT 1000")


def test_a_count_on_one_table_needs_no_join():
    trace = analyze({
        "measures": [{"dataset_id": LOADS, "aggregation": "COUNT"}],
        "filters": [{"dataset_id": LOADS, "column": "trang_thai", "operator": "==", "value": "THAT_BAI"}],
    }, SchemaGraph.from_payload(WEATHER))

    assert trace["status"] == "ok" and trace["stages"]["path"]["steps"] == []
    assert "COUNT(*)" in trace["sql"] and "JOIN" not in trace["sql"]


def test_a_table_mixing_grains_without_a_chosen_kind_of_row_stops_at_the_path():
    goal = {**HANOI_HOURLY_TEMPERATURE, "row_kinds": []}

    trace = analyze(goal, SchemaGraph.from_payload(WEATHER))

    assert trace["status"] == "row_kind_missing" and trace["sql"] is None
    assert trace["stages"]["path"]["status"] == "failed"
    assert trace["stages"]["path"]["problems"][0]["options"] == ["DU_BAO_GIO", "DU_BAO_NGAY", "HIEN_TAI"]


def test_daily_rain_cannot_be_grouped_by_hour():
    goal = {
        **HANOI_HOURLY_TEMPERATURE,
        "measures": [{"indicator": "tong_luong_mua_mm"}],
        "row_kinds": [{"dataset_id": OBSERVATIONS, "value": "DU_BAO_NGAY"}],
    }

    trace = analyze(goal, SchemaGraph.from_payload(WEATHER))

    assert trace["status"] == "grain_too_fine"


@pytest.mark.parametrize(
    "goal",
    [
        {"measures": []},
        {"measures": [{"indicator": "khong_co"}]},
        {"measures": [{"indicator": "la_ban_ngay"}]},
        {"measures": [{"dataset_id": 999, "column": "x", "aggregation": "SUM"}]},
        {"measures": [{"dataset_id": CITIES, "column": "ten_thanh_pho", "aggregation": "SUM"}]},
        {"measures": [{"dataset_id": LOADS, "column": "so_quan_sat", "aggregation": "COUNT_DISTINCT"}], "limit": 0},
        {"measures": [{"dataset_id": LOADS, "aggregation": "COUNT"}],
         "filters": [{"dataset_id": LOADS, "column": "trang_thai", "operator": "LIKE", "value": "%"}]},
    ],
)
def test_goals_that_do_not_fit_the_graph_stop_at_the_goal_stage(goal):
    trace = analyze(goal, SchemaGraph.from_payload(WEATHER))

    assert trace["status"] == "invalid_goal" and trace["stages"]["goal"]["status"] == "failed"
    assert trace["stages"]["path"]["status"] == "pending"
