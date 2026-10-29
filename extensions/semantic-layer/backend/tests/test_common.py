from datetime import date, datetime

import pytest

from text_to_bi.superset_semantic_layer.common.exceptions import (
    ConflictError,
    SelfApprovalError,
    SemanticLayerError,
    ValidationError,
)
from text_to_bi.superset_semantic_layer.common.utils.type_formatter import (
    canonical_json,
    compact_json,
    iso_date,
    iso_datetime,
    iso_moment,
    sse_event,
)


@pytest.mark.parametrize("abstract_error", [SemanticLayerError, ValidationError, ConflictError, SelfApprovalError])
def test_the_shared_errors_are_abstract(abstract_error):
    with pytest.raises(TypeError, match="abstract"):
        abstract_error("message")


def test_a_module_error_derives_from_the_shared_one_and_carries_its_status_and_message():
    class GlossaryConflictError(ConflictError):
        message = "The glossary term changed."

    error = GlossaryConflictError()
    assert isinstance(error, SemanticLayerError) and not isinstance(error, ValueError)
    assert error.status == 409 and str(error) == "The glossary term changed."
    assert str(GlossaryConflictError("changed")) == "changed"


def test_only_a_validation_error_stays_a_value_error():
    class GlossaryValidationError(ValidationError):
        pass

    error = GlossaryValidationError("Name is required.")
    assert isinstance(error, ValueError) and error.status == 400 and str(error) == "Name is required."


def test_dates_and_moments_format_whatever_the_driver_returns():
    assert iso_datetime(None) is None and iso_datetime(datetime(2026, 10, 29, 8)) == "2026-10-29T08:00:00"
    assert iso_date(1_793_232_000_000) == "2026-10-29" and iso_date("2026-10-29T08:00:00") == "2026-10-29"
    assert iso_date(True) is None and iso_date(date(2026, 10, 29)) == "2026-10-29"
    assert iso_moment(1_793_232_000_000) == "2026-10-29T00:00:00" and iso_moment("") is None


def test_json_texts_are_compact_canonical_and_wrapped_as_sse():
    assert compact_json({"b": 1, "a": [1, 2]}) == '{"b":1,"a":[1,2]}'
    assert canonical_json({"b": "ý", "a": 1}) == '{"a":1,"b":"ý"}'
    assert sse_event("done", {"total": 2}) == 'event: done\ndata: {"total": 2}\n\n'
