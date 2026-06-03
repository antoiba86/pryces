from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ....application.use_cases.get_overview import GetOverview, GetOverviewRequest
from ....application.use_cases.get_transactions import GetTransactions
from ..dependencies import current_user_id, get_get_transactions, get_overview
from ..schemas import OverviewResponse, TransactionResponse

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewResponse)
def overview(
    overview_use_case: GetOverview = Depends(get_overview),
    user_id: int = Depends(current_user_id),
) -> OverviewResponse:
    result = overview_use_case.handle(GetOverviewRequest(user_id=user_id))
    return OverviewResponse.from_overview(result)


@router.get("/overview/transactions", response_model=list[TransactionResponse])
def overview_transactions(
    symbol: str | None = Query(default=None),
    transactions_use_case: GetTransactions = Depends(get_get_transactions),
    user_id: int = Depends(current_user_id),
) -> list[TransactionResponse]:
    records = transactions_use_case.across_portfolios(symbol=symbol, user_id=user_id)
    return [TransactionResponse.from_record(r) for r in records]
