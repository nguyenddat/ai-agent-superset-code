import json
from pathlib import Path

import pytest

from text_to_bi.superset_semantic_layer.modules.expert_rules.services.sql_validation import contains_sql_or_control

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "expert_rule_validation_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("text", CASES["benign_prose"])
def test_scanner_keeps_required_natural_language(text):
    assert contains_sql_or_control(text) is False


@pytest.mark.parametrize("text", CASES["sql_or_control"])
def test_scanner_rejects_postgres_sql_and_controls_at_boundaries_and_after_prose(text):
    assert contains_sql_or_control(text) is True
    assert contains_sql_or_control(f"Please review: {text}") is True
