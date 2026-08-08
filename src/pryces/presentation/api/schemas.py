from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from ...application.dtos import ImportDataResultDTO, ImportResultDTO
from ...application.use_cases.manage_symbol_map import SymbolMapEntryDTO
from ...domain.portfolio.portfolio import (
    ClosedPosition,
    ManualAsset,
    Overview,
    Portfolio,
    PortfolioBreakdown,
    PortfolioSummary,
    Position,
)


def _str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class PortfolioSummaryResponse(BaseModel):
    name: str
    base_currency: str
    transaction_count: int

    @classmethod
    def from_summary(cls, summary: PortfolioSummary) -> PortfolioSummaryResponse:
        return cls(
            name=summary.name,
            base_currency=summary.base_currency,
            transaction_count=summary.transaction_count,
        )


class PositionResponse(BaseModel):
    symbol: str
    name: str | None = None
    quantity: str
    avg_cost: str
    price: str
    currency: str
    value_base: str
    cost_base: str
    unrealized_pnl_base: str
    realized_pnl_base: str
    lifetime_pnl_base: str
    total_return_pct: str
    lifetime_return_pct: str | None = None
    broker: str | None = None

    @classmethod
    def from_position(cls, position: Position) -> PositionResponse:
        return cls(
            symbol=position.symbol,
            name=position.name,
            quantity=str(position.quantity),
            avg_cost=str(position.avg_cost),
            price=str(position.price),
            currency=position.currency.value,
            value_base=str(position.value_base),
            cost_base=str(position.cost_base),
            unrealized_pnl_base=str(position.unrealized_pnl_base),
            realized_pnl_base=str(position.realized_pnl_base),
            lifetime_pnl_base=str(position.lifetime_pnl_base),
            total_return_pct=str(position.total_return_pct),
            lifetime_return_pct=_str(position.lifetime_return_pct),
            broker=position.broker,
        )


class ClosedPositionResponse(BaseModel):
    symbol: str
    name: str | None = None
    currency: str
    realized_pnl_base: str
    cost_basis_sold_base: str
    realized_return_pct: str
    hold_period_days: int | None = None
    broker: str | None = None

    @classmethod
    def from_closed(cls, closed: ClosedPosition) -> ClosedPositionResponse:
        return cls(
            symbol=closed.symbol,
            name=closed.name,
            currency=closed.currency.value,
            realized_pnl_base=str(closed.realized_pnl_base),
            cost_basis_sold_base=str(closed.cost_basis_sold_base),
            realized_return_pct=str(closed.realized_return_pct),
            hold_period_days=closed.hold_period_days,
            broker=closed.broker,
        )


class ManualAssetResponse(BaseModel):
    name: str
    asset_type: str
    value_base: str

    @classmethod
    def from_asset(cls, asset: ManualAsset) -> ManualAssetResponse:
        return cls(name=asset.name, asset_type=asset.asset_type, value_base=str(asset.value_base))


class PortfolioResponse(BaseModel):
    base_currency: str
    positions: list[PositionResponse]
    manual_assets: list[ManualAssetResponse]
    closed_positions: list[ClosedPositionResponse]
    positions_value: str
    manual_value: str
    total_value: str
    total_cost: str
    total_unrealized_pnl: str
    total_realized_pnl: str
    total_profit: str
    total_return_pct: str
    xirr_pct: str | None = None
    twr_pct: str | None = None

    @classmethod
    def from_portfolio(cls, portfolio: Portfolio) -> PortfolioResponse:
        return cls(
            base_currency=portfolio.base_currency,
            positions=[PositionResponse.from_position(p) for p in portfolio.unified_positions],
            manual_assets=[ManualAssetResponse.from_asset(a) for a in portfolio.manual_assets],
            closed_positions=[
                ClosedPositionResponse.from_closed(c) for c in portfolio.closed_positions
            ],
            positions_value=str(portfolio.positions_value),
            manual_value=str(portfolio.manual_value),
            total_value=str(portfolio.total_value),
            total_cost=str(portfolio.total_cost),
            total_unrealized_pnl=str(portfolio.total_unrealized_pnl),
            total_realized_pnl=str(portfolio.total_realized_pnl),
            total_profit=str(portfolio.total_profit),
            total_return_pct=str(portfolio.total_return_pct),
            xirr_pct=_str(portfolio.xirr_pct),
            twr_pct=_str(portfolio.twr_pct),
        )


class TransactionResponse(BaseModel):
    id: str
    date: str
    type: str
    symbol: str
    quantity: str | None = None
    price: str | None = None
    amount: str | None = None
    fee: str
    currency: str
    broker: str | None = None
    portfolio: str | None = None

    @classmethod
    def from_record(cls, record) -> TransactionResponse:
        transaction = record.transaction
        return cls(
            id=record.id,
            date=transaction.date.isoformat(),
            type=transaction.type.value,
            symbol=transaction.symbol,
            quantity=_str(transaction.quantity),
            price=_str(transaction.price),
            amount=_str(transaction.amount),
            fee=str(transaction.fee),
            currency=transaction.currency.value,
            broker=transaction.broker,
            portfolio=record.portfolio,
        )


class TransactionBody(BaseModel):
    """Manual add / edit payload. Decimals arrive as strings to preserve precision
    (the API's money convention); the route converts and validates them."""

    date: date
    type: str
    symbol: str
    currency: str
    quantity: str | None = None
    price: str | None = None
    amount: str | None = None
    fee: str = "0"


class PortfolioBreakdownItem(BaseModel):
    name: str
    base_currency: str
    total_value: str
    total_profit: str
    total_return_pct: str

    @classmethod
    def from_breakdown(cls, item: PortfolioBreakdown) -> PortfolioBreakdownItem:
        return cls(
            name=item.name,
            base_currency=item.base_currency,
            total_value=str(item.total_value),
            total_profit=str(item.total_profit),
            total_return_pct=str(item.total_return_pct),
        )


class OverviewResponse(BaseModel):
    portfolio: PortfolioResponse
    breakdown: list[PortfolioBreakdownItem]

    @classmethod
    def from_overview(cls, overview: Overview) -> OverviewResponse:
        return cls(
            portfolio=PortfolioResponse.from_portfolio(overview.portfolio),
            breakdown=[PortfolioBreakdownItem.from_breakdown(b) for b in overview.breakdown],
        )


class CreatePortfolioBody(BaseModel):
    base_currency: str
    name: str | None = None


class ImportDataResultResponse(BaseModel):
    portfolios_created: int
    portfolios_merged: int
    portfolios_skipped: int
    transactions_added: int
    transactions_skipped: int
    manual_assets_replaced: int
    warnings: list[str]

    @classmethod
    def from_dto(cls, dto: ImportDataResultDTO) -> ImportDataResultResponse:
        return cls(
            portfolios_created=dto.portfolios_created,
            portfolios_merged=dto.portfolios_merged,
            portfolios_skipped=dto.portfolios_skipped,
            transactions_added=dto.transactions_added,
            transactions_skipped=dto.transactions_skipped,
            manual_assets_replaced=dto.manual_assets_replaced,
            warnings=list(dto.warnings),
        )


class ImportResultResponse(BaseModel):
    broker: str
    parsed: int
    inserted: int
    duplicates: int
    skipped_unresolved: int
    unresolved_symbols: list[str]
    warnings: list[str]

    @classmethod
    def from_dto(cls, dto: ImportResultDTO) -> ImportResultResponse:
        return cls(
            broker=dto.broker,
            parsed=dto.parsed,
            inserted=dto.inserted,
            duplicates=dto.duplicates,
            skipped_unresolved=dto.skipped_unresolved,
            unresolved_symbols=list(dto.unresolved_symbols),
            warnings=list(dto.warnings),
        )


class SymbolMappingBody(BaseModel):
    ticker: str


class SymbolMappingResponse(BaseModel):
    key: str
    ticker: str
    # None when no verification ran (Yahoo unavailable, or verification off).
    verified: bool | None = None
    name: str | None = None
    currency: str | None = None

    @classmethod
    def from_dto(cls, dto: SymbolMapEntryDTO) -> SymbolMappingResponse:
        return cls(
            key=dto.key,
            ticker=dto.ticker,
            verified=dto.verified,
            name=dto.name,
            currency=dto.currency,
        )
