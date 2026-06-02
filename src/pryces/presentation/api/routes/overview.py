from __future__ import annotations

from fastapi import APIRouter, Depends

from ....application.use_cases.get_overview import GetOverview, GetOverviewRequest
from ..dependencies import current_user_id, get_overview
from ..schemas import OverviewResponse

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewResponse)
def overview(
    overview_use_case: GetOverview = Depends(get_overview),
    user_id: int = Depends(current_user_id),
) -> OverviewResponse:
    result = overview_use_case.handle(GetOverviewRequest(user_id=user_id))
    return OverviewResponse.from_overview(result)
