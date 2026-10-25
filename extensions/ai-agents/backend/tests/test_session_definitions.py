import pytest

from text_to_bi.superset_ai_agent.modules.definitions.parsing import (
    DefinitionError,
    parse_definition,
    parse_definitions,
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
    with pytest.raises(DefinitionError):
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
    with pytest.raises(DefinitionError):
        parse_definitions(items)
