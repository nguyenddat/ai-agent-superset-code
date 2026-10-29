from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ....common.utils.type_formatter import iso_datetime
from ...superset.services.users import user_names
from ..dependencies import question_handling_repository, question_repository
from ..exceptions import QuestionNotFoundError
from ..models import AgentQuestion, AgentQuestionHandling
from .handling import count_by_handling

REVIEW_LIST_LIMIT = 200


def _handling_status(handling: AgentQuestionHandling | None) -> str:
    return handling.status if handling else "pending"


def serialize_for_review(
    question: AgentQuestion, handling: AgentQuestionHandling | None, user_name: Callable[[int | None], str | None],
) -> dict[str, Any]:
    return {
        "id": question.id,
        "question": question.question,
        "rewritten_question": question.rewritten_question,
        "asked_by": user_name(question.user_id),
        "asked_on": iso_datetime(question.created_on),
        "glossary_terms": question.glossary_terms,
        "metrics": question.metrics,
        "expert_rules": question.expert_rules,
        "missing": question.missing,
        "requires_expert_rule": question.requires_expert_rule,
        "suggestions": question.suggestions or {},
        "handling": {
            "status": _handling_status(handling),
            "note": handling.note if handling else None,
            "handled_by": user_name(handling.handled_by) if handling else None,
            "handled_on": iso_datetime(handling.handled_on) if handling else None,
        },
    }


def questions_for_review(handling_filter: str, missing_filter: str | None) -> dict[str, Any]:
    """The `needs_review` questions, newest first, with their handling and the count per handling status.

    The counts cover every question missing `missing_filter`, before `handling_filter` narrows the list.
    """
    rows = question_repository().needs_review()
    if missing_filter:
        rows = [(question, handling) for question, handling in rows if missing_filter in (question.missing or [])]
    counts = count_by_handling([handling.status if handling else None for _, handling in rows])
    if handling_filter != "all":
        rows = [(question, handling) for question, handling in rows if _handling_status(handling) == handling_filter]
    user_name = user_names()
    questions = [serialize_for_review(question, handling, user_name) for question, handling in rows[:REVIEW_LIST_LIMIT]]
    return {"counts": counts, "questions": questions}


def record_handling(question_id: int, status: str, note: str | None, handled_by: int) -> dict[str, Any]:
    """Record how a `needs_review` question was handled; `pending` removes the decision."""
    question = question_repository().get(question_id)
    if question is None or question.status != "needs_review":
        raise QuestionNotFoundError()
    repository = question_handling_repository()
    handling = repository.get(question_id)
    if status == "pending":
        if handling is not None:
            repository.delete(handling)
        handling = None
    else:
        if handling is None:
            handling = repository.add(AgentQuestionHandling(question_id=question_id), flush=False)
        handling.status = status
        handling.note = note
        handling.handled_by = handled_by
        handling.handled_on = datetime.now(timezone.utc)
    return serialize_for_review(question, handling, user_names())
