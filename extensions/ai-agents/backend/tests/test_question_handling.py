import pytest

from text_to_bi.superset_ai_agent.modules.questions.exceptions import QuestionHandlingValidationError
from text_to_bi.superset_ai_agent.modules.questions.services.handling import (
    count_by_handling,
    parse_handling,
    parse_review_filters,
)


def test_a_valid_decision_keeps_its_status_and_trims_the_note():
    assert parse_handling({"status": "created", "note": "  Đã thêm thuật ngữ Mưa lớn.  "}) == (
        "created", "Đã thêm thuật ngữ Mưa lớn.",
    )
    assert parse_handling({"status": "ignored", "note": "   "}) == ("ignored", None)
    assert parse_handling({"status": "pending"}) == ("pending", None)


@pytest.mark.parametrize("body", [None, [], {"status": "done"}, {"status": "created", "note": 5}, {"note": "x"}])
def test_an_invalid_decision_is_rejected(body):
    with pytest.raises(QuestionHandlingValidationError):
        parse_handling(body)


def test_a_note_longer_than_the_limit_is_rejected():
    with pytest.raises(QuestionHandlingValidationError):
        parse_handling({"status": "to_create", "note": "x" * 1001})


def test_questions_without_a_handling_row_count_as_pending():
    assert count_by_handling([None, "created", None, "ignored", "to_create", "created"]) == {
        "pending": 2, "to_create": 1, "created": 2, "ignored": 1,
    }


def test_the_review_list_filters_by_a_handling_status_and_a_missing_kind():
    assert parse_review_filters("all", None) == ("all", None)
    assert parse_review_filters("to_create", "metric") == ("to_create", "metric")


@pytest.mark.parametrize("handling, missing", [("done", None), ("all", "dataset")])
def test_an_unknown_review_filter_is_rejected(handling, missing):
    with pytest.raises(QuestionHandlingValidationError):
        parse_review_filters(handling, missing)
