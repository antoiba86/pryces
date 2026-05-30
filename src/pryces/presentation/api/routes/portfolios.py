from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status

from ....application.exceptions import (
    PortfolioAlreadyExists,
    PortfolioNotFound,
    UnrecognizedImportFormat,
)
from ....application.use_cases.create_portfolio import CreatePortfolio, CreatePortfolioRequest
from ....application.use_cases.delete_portfolio import DeletePortfolio, DeletePortfolioRequest
from ....application.use_cases.get_portfolio import GetPortfolio, GetPortfolioRequest
from ....application.use_cases.import_transactions import (
    ImportTransactions,
    ImportTransactionsRequest,
)
from ....application.use_cases.list_portfolios import ListPortfolios
from ..dependencies import (
    current_user_id,
    get_create_portfolio,
    get_delete_portfolio,
    get_get_portfolio,
    get_import_transactions,
    get_list_portfolios,
)
from ..schemas import (
    CreatePortfolioBody,
    ImportResultResponse,
    PortfolioResponse,
    PortfolioSummaryResponse,
)

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


@router.get("", response_model=list[PortfolioSummaryResponse])
def list_portfolios(
    list_use_case: ListPortfolios = Depends(get_list_portfolios),
    user_id: int = Depends(current_user_id),
) -> list[PortfolioSummaryResponse]:
    summaries = list_use_case.handle(user_id=user_id)
    return [PortfolioSummaryResponse.from_summary(summary) for summary in summaries]


@router.post("", response_model=PortfolioSummaryResponse, status_code=status.HTTP_201_CREATED)
def create_portfolio(
    body: CreatePortfolioBody,
    create_use_case: CreatePortfolio = Depends(get_create_portfolio),
    user_id: int = Depends(current_user_id),
) -> PortfolioSummaryResponse:
    try:
        summary = create_use_case.handle(
            CreatePortfolioRequest(
                base_currency=body.base_currency, name=body.name, user_id=user_id
            )
        )
    except PortfolioAlreadyExists as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return PortfolioSummaryResponse.from_summary(summary)


@router.get("/{name}", response_model=PortfolioResponse)
def get_portfolio(
    name: str,
    get_use_case: GetPortfolio = Depends(get_get_portfolio),
    user_id: int = Depends(current_user_id),
) -> PortfolioResponse:
    try:
        portfolio = get_use_case.handle(GetPortfolioRequest(name=name, user_id=user_id))
    except PortfolioNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    return PortfolioResponse.from_portfolio(portfolio)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(
    name: str,
    delete_use_case: DeletePortfolio = Depends(get_delete_portfolio),
    user_id: int = Depends(current_user_id),
) -> Response:
    try:
        delete_use_case.handle(DeletePortfolioRequest(name=name, user_id=user_id))
    except PortfolioNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{name}/transactions", response_model=ImportResultResponse)
async def import_transactions(
    name: str,
    file: UploadFile = File(...),
    broker: str | None = Query(default=None),
    import_use_case: ImportTransactions = Depends(get_import_transactions),
    user_id: int = Depends(current_user_id),
) -> ImportResultResponse:
    content = (await file.read()).decode("utf-8")
    try:
        result = import_use_case.handle(
            ImportTransactionsRequest(
                portfolio_name=name, content=content, broker=broker, user_id=user_id
            )
        )
    except PortfolioNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except UnrecognizedImportFormat as error:
        raise HTTPException(status_code=422, detail=str(error))
    return ImportResultResponse.from_dto(result)
