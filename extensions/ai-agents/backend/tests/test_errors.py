import pytest

from text_to_bi.superset_ai_agent.common.exceptions import NotFoundError, ValidationError
from text_to_bi.superset_ai_agent.modules.chat.exceptions import QueryPlanError
from text_to_bi.superset_ai_agent.modules.semantic_layer.exceptions import SemanticLayerUnavailableError


@pytest.mark.parametrize("abstract_error", [ValidationError, NotFoundError])
def test_a_root_error_cannot_be_raised_directly(abstract_error):
    with pytest.raises(TypeError):
        abstract_error()


def test_a_module_error_carries_its_status_and_default_message():
    error = SemanticLayerUnavailableError()

    assert (error.status, str(error)) == (503, "Không kết nối được tới Semantic Layer.")


def test_a_validation_error_is_still_a_value_error():
    assert isinstance(QueryPlanError("Cột không có trong dataset."), ValueError)
