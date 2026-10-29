import pytest

from text_to_bi.superset_ai_agent.modules.definitions.exceptions import UserDefinitionValidationError
from text_to_bi.superset_ai_agent.modules.definitions.services.parsing import (
    parse_clarification,
    parse_definition,
    parse_definitions,
    parse_review,
)


def test_a_definition_is_trimmed_and_its_concept_is_optional():
    parsed = parse_definition({"kind": "expert_rule", "name": " Ngày gió mạnh ", "definition": " Gió ≥ 30 km/h. "})

    assert parsed == {"kind": "expert_rule", "name": "Ngày gió mạnh", "concept": None, "definition": "Gió ≥ 30 km/h."}


@pytest.mark.parametrize("item", [
    "gió mạnh",
    {"kind": "metric", "name": "Gió", "definition": "Gió."},
    {"kind": "glossary", "name": "  ", "definition": "Gió."},
    {"kind": "glossary", "name": "Gió", "definition": "x" * 2001},
])
def test_invalid_definitions_are_rejected(item):
    with pytest.raises(UserDefinitionValidationError):
        parse_definition(item)


def test_confirming_the_same_concept_twice_keeps_the_last_wording():
    parsed = parse_definitions([
        {"kind": "glossary", "name": "Khách du lịch", "definition": "Cũ."},
        {"kind": "glossary", "name": "khách du lịch", "definition": "Mới."},
        {"kind": "expert_rule", "name": "Khách du lịch", "definition": "Rule."},
    ])

    assert [(item["kind"], item["definition"]) for item in parsed] == [("glossary", "Mới."), ("expert_rule", "Rule.")]


@pytest.mark.parametrize("items", [None, [], [{"kind": "glossary", "name": "A", "definition": "B"}] * 11])
def test_a_confirmation_needs_between_one_and_ten_definitions(items):
    with pytest.raises(UserDefinitionValidationError):
        parse_definitions(items)


def test_a_dismissed_clarification_keeps_no_definition():
    assert parse_clarification({"state": "dismissed", "definitions": [{"kind": "glossary"}]}) == ("dismissed", [])


def test_a_confirmed_clarification_carries_the_chosen_definitions():
    state, definitions = parse_clarification({
        "state": "confirmed", "definitions": [{"kind": "glossary", "name": "Gió", "definition": "Gió mạnh."}],
    })

    assert state == "confirmed"
    assert [item["name"] for item in definitions] == ["Gió"]


@pytest.mark.parametrize("body", [None, {}, {"state": "pending"}, {"state": "confirmed", "definitions": []}])
def test_an_invalid_clarification_answer_is_rejected(body):
    with pytest.raises(UserDefinitionValidationError):
        parse_clarification(body)


def test_a_review_decision_names_its_definitions_and_status():
    assert parse_review({"ids": [3, 5], "status": "promoted"}) == ([3, 5], "promoted")


@pytest.mark.parametrize("body", [
    None,
    {"ids": [1], "status": "approved"},
    {"ids": [], "status": "ignored"},
    {"ids": [True], "status": "ignored"},
    {"ids": list(range(201)), "status": "ignored"},
])
def test_an_invalid_review_decision_is_rejected(body):
    with pytest.raises(UserDefinitionValidationError):
        parse_review(body)
