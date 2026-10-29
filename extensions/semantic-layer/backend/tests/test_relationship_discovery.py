import json

from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

from text_to_bi.superset_semantic_layer.modules.semantic_query.services.relationship_discovery import (
    MAX_ORPHAN_SAMPLES,
    TableKeys,
    database_suggestions,
    merged_suggestions,
    naming_suggestions,
    stored_verification,
    types_match,
    verification_queries,
    verification_result,
)

CITY = TableKeys(10, "public", "dm_thanh_pho", {"thanh_pho_id": "BIGINT", "ten_thanh_pho": "VARCHAR(100)"},
                 frozenset({"thanh_pho_id", "ten_thanh_pho"}))
DAY = TableKeys(8, "public", "dm_ngay", {"ngay_id": "DATE"}, frozenset({"ngay_id"}))
OBSERVATION = TableKeys(
    15, "public", "tb_quan_sat_thoi_tiet",
    {"quan_sat_id": "BIGINT", "thanh_pho_id": "BIGINT", "ngay_id": "DATE", "loai_quan_sat": "VARCHAR(30)"},
    frozenset({"quan_sat_id"}),
)
VALUE = TableKeys(13, "public", "tb_gia_tri_quan_sat", {"quan_sat_id": "BIGINT", "chi_so_id": "BIGINT"}, frozenset())
TABLES = [CITY, DAY, OBSERVATION, VALUE]


def _pairs(suggestions):
    return {
        (item["from_dataset_id"], item["from_column"], item["to_dataset_id"], item["to_column"]) for item in suggestions
    }


def test_types_compare_by_family():
    assert types_match("BIGINT", "INTEGER") and types_match("VARCHAR(10)", "TEXT")
    assert not types_match("DATE", "TIMESTAMP WITHOUT TIME ZONE") and not types_match(None, "BIGINT")


def test_a_key_named_column_suggests_the_table_whose_key_it_matches():
    assert _pairs(naming_suggestions(TABLES)) == {
        (15, "thanh_pho_id", 10, "thanh_pho_id"),
        (15, "ngay_id", 8, "ngay_id"),
        (13, "quan_sat_id", 15, "quan_sat_id"),
    }


def test_a_key_of_another_type_is_not_suggested():
    text_city = TableKeys(10, "public", "dm_thanh_pho", {"thanh_pho_id": "VARCHAR(10)"}, frozenset({"thanh_pho_id"}))

    assert (15, "thanh_pho_id", 10, "thanh_pho_id") not in _pairs(naming_suggestions([text_city, OBSERVATION]))


def test_database_foreign_keys_map_to_datasets_and_composite_or_outside_keys_are_left_out():
    foreign_keys = {
        15: [
            {
                "constrained_columns": ["thanh_pho_id"],
                "referred_schema": "public",
                "referred_table": "dm_thanh_pho",
                "referred_columns": ["thanh_pho_id"],
            },
            {
                "constrained_columns": ["ngay_id", "thanh_pho_id"],
                "referred_schema": "public",
                "referred_table": "dm_ngay",
                "referred_columns": ["ngay_id", "x"],
            },
            {
                "constrained_columns": ["nguon_du_lieu_id"],
                "referred_schema": "public",
                "referred_table": "dm_nguon",
                "referred_columns": ["nguon_du_lieu_id"],
            },
        ]
    }

    assert _pairs(database_suggestions(TABLES, foreign_keys)) == {(15, "thanh_pho_id", 10, "thanh_pho_id")}


def test_suggestions_from_several_sources_merge_with_the_strongest_first():
    database = database_suggestions(
        TABLES,
        {
            15: [
                {
                    "constrained_columns": ["thanh_pho_id"],
                    "referred_schema": None,
                    "referred_table": "dm_thanh_pho",
                    "referred_columns": ["thanh_pho_id"],
                }
            ]
        },
    )

    merged = merged_suggestions(naming_suggestions(TABLES), database)

    city = next(item for item in merged if item["from_column"] == "thanh_pho_id")
    assert city["sources"] == ["database", "naming"] and len(merged) == 3


def test_check_queries_quote_names_with_the_database_dialect():
    queries = verification_queries("public", "tb quan sat", "thanh_pho_id", "public", "dm_thanh_pho", "thanh_pho_id")

    sql = str(queries["orphans"].compile(dialect=postgresql.dialect()))
    assert 'public."tb quan sat" AS source_table LEFT OUTER JOIN public.dm_thanh_pho AS target_table' in sql


def test_check_queries_count_uniqueness_and_orphans_on_real_tables():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE city (city_id INTEGER, name TEXT)"))
        connection.execute(text("INSERT INTO city VALUES (1, 'Ha Noi'), (2, 'Hue')"))
        connection.execute(text("CREATE TABLE observation (city_id INTEGER)"))
        connection.execute(text("INSERT INTO observation VALUES (1), (1), (2), (3), (4), (NULL)"))
        connection.execute(text("CREATE TABLE twin (city_id INTEGER)"))
        connection.execute(text("INSERT INTO twin VALUES (1), (1)"))
        queries = verification_queries(None, "observation", "city_id", None, "city", "city_id")
        uniqueness = dict(connection.execute(queries["uniqueness"]).mappings().one())
        orphans = dict(connection.execute(queries["orphans"]).mappings().one())
        samples = connection.execute(queries["samples"]).scalars().all()
        duplicated = dict(
            connection.execute(
                verification_queries(None, "observation", "city_id", None, "twin", "city_id")["uniqueness"]
            )
            .mappings()
            .one()
        )

    result = verification_result(uniqueness, orphans, samples, type_match=True)

    assert result["target_unique"] and result["passed"]
    assert (result["references"], result["orphans"], result["orphan_ratio"]) == (5, 2, 0.4)
    assert sorted(result["orphan_samples"]) == ["3", "4"]
    assert not verification_result(duplicated, None, [], type_match=True)["passed"]
    assert not verification_result(uniqueness, orphans, samples, type_match=False)["passed"]


def test_orphan_samples_are_bounded_and_a_stored_check_survives_only_as_json():
    result = verification_result(
        {"target_values": 1, "target_distinct": 1}, {"references": 9, "orphans": 9}, list(range(20)), type_match=True
    )

    assert len(result["orphan_samples"]) == MAX_ORPHAN_SAMPLES
    assert stored_verification(json.dumps(result)) == result
    assert stored_verification("not json") is None and stored_verification("[1]") is None
