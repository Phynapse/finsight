"""Natural-language question endpoint."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import QuestionServiceDep
from app.schemas.question import Answer, QuestionRequest

router = APIRouter(tags=["questions"])


@router.post(
    "/questions",
    response_model=Answer,
    status_code=status.HTTP_200_OK,
    summary="Ask FinSight a financial question",
)
def ask_question(request: QuestionRequest, service: QuestionServiceDep) -> Answer:
    """Answer a business or financial question from the bundled datasets.

    The response carries the interpretation, the analysis plan that was
    executed, every evidence item the answer rests on, the explanation, and the
    caveats. A question FinSight cannot map onto the data returns ``200`` with
    ``status = "unsupported"`` rather than an error.
    """
    return service.ask(request)