from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status

from ....application.exceptions import (
    PortfolioAlreadyExists,
    PortfolioBrokerMismatch,
    PortfolioNotFound,
    TransactionNotFound,
    UnrecognizedImportFormat,
)
from ....application.use_cases.create_portfolio import CreatePortfolio, CreatePortfolioRequest
from ....application.use_cases.delete_portfolio import DeletePortfolio, DeletePortfolioRequest
from ....application.use_cases.get_portfolio import GetPortfolio, GetPortfolioRequest
from ....application.use_cases.import_transactions import (
    ImportTransactions,
    ImportTransactionsRequest,
)
from ....application.use_cases.get_transactions import GetTransactions
from ....application.use_cases.list_portfolios import ListPortfolios
from ....application.use_cases.manage_transactions import (
    AddTransaction,
    AddTransactionRequest,
    DeleteTransaction,
    UpdateTransaction,
    UpdateTransactionRequest,
)
from ....domain.portfolio.transactions import TransactionType, TransactionValidationError
from ....domain.stocks import Currency
from ..dependencies import (
    current_user_id,
    get_add_transaction,
    get_create_portfolio,
    get_delete_portfolio,
    get_delete_transaction,
    get_get_portfolio,
    get_get_transactions,
    get_import_transactions,
    get_list_portfolios,
    get_update_transaction,
)
from ..schemas import (
    CreatePortfolioBody,
    ImportResultResponse,
    PortfolioResponse,
    PortfolioSummaryResponse,
    TransactionBody,
    TransactionResponse,
)

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        raise HTTPException(status_code=422, detail=f"Invalid decimal: {value}")


def _parse_transaction_fields(body: TransactionBody) -> dict:
    """Converts a TransactionBody's string/enum fields to domain types, raising 422
    on anything unparseable. Shared by the manual-add and edit routes."""
    try:
        transaction_type = TransactionType(body.type)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid transaction type: {body.type}")
    try:
        currency = Currency(body.currency)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid currency: {body.currency}")
    return {
        "date": body.date,
        "type": transaction_type,
        "symbol": body.symbol,
        "currency": currency,
        "quantity": _parse_decimal(body.quantity),
        "price": _parse_decimal(body.price),
        "amount": _parse_decimal(body.amount),
        "fee": _parse_decimal(body.fee) or Decimal("0"),
    }


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


@router.get("/{name}/transactions", response_model=list[TransactionResponse])
def get_portfolio_transactions(
    name: str,
    symbol: str | None = Query(default=None),
    transactions_use_case: GetTransactions = Depends(get_get_transactions),
    user_id: int = Depends(current_user_id),
) -> list[TransactionResponse]:
    try:
        records = transactions_use_case.for_portfolio(name, symbol=symbol, user_id=user_id)
    except PortfolioNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    return [TransactionResponse.from_record(r) for r in records]


@router.post("/{name}/transactions/manual", status_code=status.HTTP_201_CREATED)
def add_manual_transaction(
    name: str,
    body: TransactionBody,
    add_use_case: AddTransaction = Depends(get_add_transaction),
    user_id: int = Depends(current_user_id),
) -> dict:
    fields = _parse_transaction_fields(body)
    try:
        transaction_id = add_use_case.handle(
            AddTransactionRequest(portfolio_name=name, user_id=user_id, **fields)
        )
    except PortfolioNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except TransactionValidationError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"id": transaction_id}


@router.patch("/{name}/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_transaction(
    name: str,
    transaction_id: str,
    body: TransactionBody,
    update_use_case: UpdateTransaction = Depends(get_update_transaction),
    user_id: int = Depends(current_user_id),
) -> Response:
    fields = _parse_transaction_fields(body)
    try:
        update_use_case.handle(
            UpdateTransactionRequest(
                portfolio_name=name,
                transaction_id=transaction_id,
                user_id=user_id,
                **fields,
            )
        )
    except (PortfolioNotFound, TransactionNotFound) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except TransactionValidationError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{name}/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    name: str,
    transaction_id: str,
    delete_use_case: DeleteTransaction = Depends(get_delete_transaction),
    user_id: int = Depends(current_user_id),
) -> Response:
    try:
        delete_use_case.handle(name, transaction_id, user_id=user_id)
    except (PortfolioNotFound, TransactionNotFound) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    content = await file.read()
    try:
        result = import_use_case.handle(
            ImportTransactionsRequest(
                portfolio_name=name, content=content, broker=broker, user_id=user_id
            )
        )
    except PortfolioNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except PortfolioBrokerMismatch as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    except UnrecognizedImportFormat as error:
        raise HTTPException(status_code=422, detail=str(error))
    return ImportResultResponse.from_dto(result)
