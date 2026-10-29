import json
from types import SimpleNamespace

from catalog_source import api_class, compile_into

from text_to_bi.superset_semantic_layer.modules.semantic_query.services.schema_graph import (
    GRAPH_VERSION,
    graph_edges,
    table_node,
)


def _live(name, type_="BIGINT", expression=None, is_active=True):
    return SimpleNamespace(column_name=name, type=type_, expression=expression, is_active=is_active, verbose_name=None)


def _entry(name, **fields):
    defaults = {
        "column_name": name,
        "display_name": name,
        "semantic_role": None,
        "aggregations": None,
        "synonyms": None,
        "description": None,
        "business_term": None,
        "unit": None,
        "temporal_kind": None,
        "is_pk": False,
        "is_unique": False,
        "is_fk": False,
    }
    return SimpleNamespace(**{**defaults, **fields})


def _contract(contract_id, source, target, status="approved"):
    return SimpleNamespace(
        id=contract_id,
        status=status,
        from_dataset_id=source,
        from_column="x_id",
        to_dataset_id=target,
        to_column="x_id",
        cardinality="many_to_one",
    )


def test_a_table_node_keeps_physical_columns_with_their_semantics():
    dataset = SimpleNamespace(
        id=15,
        schema="public",
        table_name="tb_quan_sat_thoi_tiet",
        description=None,
        columns=[
            _live("quan_sat_id"),
            _live("loai_quan_sat", "VARCHAR(30)"),
            _live("thoi_diem_quan_sat", "TIMESTAMP"),
            _live("ten_thanh_pho", "VARCHAR", expression="(SELECT ...)"),
            _live("cu", is_active=False),
        ],
    )
    dictionary = SimpleNamespace(
        display_name="Quan sát thời tiết",
        description="Một dòng một quan sát.",
        grain=None,
        time_column="thoi_diem_quan_sat",
        row_kind_column="loai_quan_sat",
        indicator_model=None,
    )
    entries = {
        "quan_sat_id": _entry("quan_sat_id", semantic_role="key", is_pk=True),
        "loai_quan_sat": _entry("loai_quan_sat", semantic_role="row_kind", synonyms=json.dumps(["loại quan sát"])),
    }
    grains = [SimpleNamespace(row_kind_value="DU_BAO_GIO", label="Dự báo theo giờ", grain="hour")]
    layer = SimpleNamespace(id=2, name="Nghiệp vụ", level=1)

    coded_values = {"loai_quan_sat": ["DU_BAO_GIO", "HIEN_TAI"]}
    node = table_node(dataset, dictionary, entries, grains, coded_values, None, None, layer)

    assert [column["name"] for column in node["columns"]] == ["quan_sat_id", "loai_quan_sat", "thoi_diem_quan_sat"]
    row_kind = node["columns"][1]
    assert (row_kind["role"], row_kind["synonyms"], row_kind["values"]) == (
        "row_kind",
        ["loại quan sát"],
        ["DU_BAO_GIO", "HIEN_TAI"],
    )
    assert node["columns"][2]["role"] is None and node["columns"][0]["is_pk"]
    assert node["time"]["row_kinds"] == [{"value": "DU_BAO_GIO", "label": "Dự báo theo giờ", "grain": "hour"}]
    assert node["layer"] == {"id": 2, "name": "Nghiệp vụ", "level": 1} and node["label"] == "Quan sát thời tiết"


def test_an_indicator_table_carries_its_declaration_and_indicators():
    model = {"kind": "values", "indicator_column": "chi_so_id", "value_columns": {"SO": "gia_tri_so"}}
    dictionary = SimpleNamespace(
        display_name=None,
        description=None,
        grain=None,
        time_column=None,
        row_kind_column=None,
        indicator_model=json.dumps(model),
    )
    dataset = SimpleNamespace(id=13, schema=None, table_name="tb_gia_tri_quan_sat", description=None, columns=[])

    node = table_node(dataset, dictionary, {}, [], {}, model, {"indicators": []}, None)

    assert node["indicator_model"] == model and node["indicators"] == {"indicators": []}
    assert node["label"] == "tb_gia_tri_quan_sat" and node["layer"] is None


def test_edges_follow_contract_order():
    edges = graph_edges([_contract(3, 15, 10), _contract(1, 13, 15)])

    assert [edge["id"] for edge in edges] == [1, 3]
    assert edges[0] == {
        "id": 1,
        "from": {"dataset_id": 13, "column": "x_id"},
        "to": {"dataset_id": 15, "column": "x_id"},
        "cardinality": "many_to_one",
    }


class _Field:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return (self.name, lambda found: found == value)

    def in_(self, values):
        return (self.name, lambda found: found in set(values))


class _Contracts:
    status, from_dataset_id, to_dataset_id = _Field("status"), _Field("from_dataset_id"), _Field("to_dataset_id")


def _schema_graph_api(datasets, access, rls, contracts):
    """The schema_graph route with Superset, the session and the per-table reads stubbed."""
    route_class = api_class({"schema_graph", "_has_row_level_security"})
    route_class.bases = []

    class Query:
        def __init__(self, items):
            self.items = items

        def filter(self, *conditions):
            return Query([item for item in self.items if all(test(getattr(item, name)) for name, test in conditions)])

        def all(self):
            return self.items

    session = SimpleNamespace(
        get=lambda _model, identifier: SimpleNamespace(id=identifier, database_name="Weather", backend="postgresql"),
        query=lambda _model: Query(contracts),
    )
    namespace = {
        "Any": object,
        "SqlaTable": object,
        "staticmethod": staticmethod,
        "db": SimpleNamespace(session=session),
        "Database": object,
        "RelationshipContract": _Contracts,
        "GRAPH_VERSION": GRAPH_VERSION,
        "graph_edges": graph_edges,
        "ensure_dictionary_tables": lambda: None,
        "can_access_dataset": lambda dataset: access[dataset.id],
        "request": SimpleNamespace(args=SimpleNamespace(get=lambda name, type=None: 1)),
        "security_manager": SimpleNamespace(get_rls_filters=lambda dataset: rls.get(dataset.id, [])),
        "logger": SimpleNamespace(warning=lambda *args, **kwargs: None),
        "ColumnDictionaryRepository": lambda _session: SimpleNamespace(
            get_for_dataset_column=lambda dataset_id, column: SimpleNamespace(
                dataset_id=dataset_id, column_name=column
            ),
        ),
        # Contract 5 is approved but no longer matches the live columns.
        "relationship_is_approved_current": lambda contract, *_ends: contract.id != 5,
    }
    compile_into(namespace, route_class)
    api = namespace["SemanticLayerAPI"]()
    api.response = lambda status, **payload: (status, payload)
    api.response_400 = lambda **payload: (400, payload)
    namespace["base_tables"] = lambda _database_id: datasets
    api._schema_graph_node = lambda dataset: {"dataset_id": dataset.id, "table": dataset.table_name}
    namespace["relationship_ends"] = lambda entry: (entry, entry)
    return api


def test_the_route_hides_unreadable_tables_and_tables_under_rls_with_their_edges():
    datasets = [
        SimpleNamespace(id=dataset_id, table_name=name)
        for dataset_id, name in (
            (13, "tb_gia_tri_quan_sat"),
            (15, "tb_quan_sat_thoi_tiet"),
            (10, "dm_thanh_pho"),
            (6, "dm_chi_so_thoi_tiet"),
        )
    ]
    contracts = [
        _contract(1, 13, 15),
        _contract(2, 15, 10),
        _contract(3, 13, 6),
        _contract(4, 15, 10, "revoked"),
        _contract(5, 15, 13),
    ]
    api = _schema_graph_api(
        datasets,
        access={13: True, 15: True, 10: False, 6: True},
        rls={6: ["region = 'north'"]},
        contracts=contracts,
    )

    status, graph = api.schema_graph()

    assert status == 200 and graph["version"] == GRAPH_VERSION
    assert [table["dataset_id"] for table in graph["tables"]] == [13, 15]
    assert [edge["id"] for edge in graph["edges"]] == [1]
    # A table the caller may read but an RLS rule filters is reported; one they may not read is not even named.
    assert graph["excluded"] == [{"dataset_id": 6, "table": "dm_chi_so_thoi_tiet", "reason": "row_level_security"}]


def test_unreadable_rls_rules_count_as_a_rule():
    api = _schema_graph_api([], access={}, rls={}, contracts=[])
    namespace_manager = api._has_row_level_security.__globals__["security_manager"]
    namespace_manager.get_rls_filters = lambda dataset: (_ for _ in ()).throw(RuntimeError("no rules table"))

    assert api._has_row_level_security(SimpleNamespace(table_name="dm_thanh_pho")) is True
