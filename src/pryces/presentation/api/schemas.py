from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from ...application.dtos import ImportResultDTO
from ...domain.portfolio.portfolio import ManualAsset, Portfolio, PortfolioSummary, Position


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
    quantity: str
    avg_cost: str
    price: str
    currency: str
    value_base: str
    cost_base: str
    unrealized_pnl_base: str
    total_return_pct: str
    broker: str | None = None

    @classmethod
    def from_position(cls, position: Position) -> PositionResponse:
        return cls(
            symbol=position.symbol,
            quantity=str(position.quantity),
            avg_cost=str(position.avg_cost),
            price=str(position.price),
            currency=position.currency.value,
            value_base=str(position.value_base),
            cost_base=str(position.cost_base),
            unrealized_pnl_base=str(position.unrealized_pnl_base),
            total_return_pct=str(position.total_return_pct),
            broker=position.broker,
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
    positions_value: str
    manual_value: str
    total_value: str
    total_cost: str
    total_unrealized_pnl: str
    total_return_pct: str
    xirr_pct: str | None = None
    twr_pct: str | None = None

    @classmethod
    def from_portfolio(cls, portfolio: Portfolio) -> PortfolioResponse:
        return cls(
            base_currency=portfolio.base_currency,
            positions=[PositionResponse.from_position(p) for p in portfolio.unified_positions],
            manual_assets=[ManualAssetResponse.from_asset(a) for a in portfolio.manual_assets],
            positions_value=str(portfolio.positions_value),
            manual_value=str(portfolio.manual_value),
            total_value=str(portfolio.total_value),
            total_cost=str(portfolio.total_cost),
            total_unrealized_pnl=str(portfolio.total_unrealized_pnl),
            total_return_pct=str(portfolio.total_return_pct),
            xirr_pct=_str(portfolio.xirr_pct),
            twr_pct=_str(portfolio.twr_pct),
        )


class CreatePortfolioBody(BaseModel):
    base_currency: str
    name: str | None = None


class ImportResultResponse(BaseModel):
    broker: str
    parsed: int
    inserted: int
    duplicates: int
    unresolved_symbols: list[str]
    warnings: list[str]

    @classmethod
    def from_dto(cls, dto: ImportResultDTO) -> ImportResultResponse:
        return cls(
            broker=dto.broker,
            parsed=dto.parsed,
            inserted=dto.inserted,
            duplicates=dto.duplicates,
            unresolved_symbols=list(dto.unresolved_symbols),
            warnings=list(dto.warnings),
        )
