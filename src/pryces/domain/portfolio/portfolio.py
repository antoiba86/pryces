from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from pryces.domain.portfolio.returns import total_return
from pryces.domain.stocks import Currency


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    price: Decimal
    currency: Currency
    value_base: Decimal
    cost_base: Decimal
    dividends_base: Decimal
    fees_base: Decimal
    broker: str | None = None

    @property
    def unrealized_pnl_base(self) -> Decimal:
        return self.value_base - self.cost_base

    @property
    def total_return_pct(self) -> Decimal:
        return total_return(self.value_base, self.cost_base, self.dividends_base, self.fees_base)


@dataclass(frozen=True, slots=True)
class ManualAsset:
    name: str
    asset_type: str
    value_base: Decimal


@dataclass(frozen=True, slots=True)
class Portfolio:
    base_currency: str
    positions: tuple[Position, ...] = field(default_factory=tuple)
    manual_assets: tuple[ManualAsset, ...] = field(default_factory=tuple)
    xirr_pct: Decimal | None = None
    twr_pct: Decimal | None = None

    @property
    def positions_value(self) -> Decimal:
        return sum((p.value_base for p in self.positions), Decimal("0"))

    @property
    def manual_value(self) -> Decimal:
        return sum((m.value_base for m in self.manual_assets), Decimal("0"))

    @property
    def total_value(self) -> Decimal:
        return self.positions_value + self.manual_value

    @property
    def total_cost(self) -> Decimal:
        return sum((p.cost_base for p in self.positions), Decimal("0"))

    @property
    def total_dividends(self) -> Decimal:
        return sum((p.dividends_base for p in self.positions), Decimal("0"))

    @property
    def total_fees(self) -> Decimal:
        return sum((p.fees_base for p in self.positions), Decimal("0"))

    @property
    def total_unrealized_pnl(self) -> Decimal:
        return sum((p.unrealized_pnl_base for p in self.positions), Decimal("0"))

    @property
    def total_return_pct(self) -> Decimal:
        return total_return(
            self.positions_value, self.total_cost, self.total_dividends, self.total_fees
        )

    def allocation_for(self, position: Position) -> Decimal:
        total = self.total_value
        if total <= 0:
            return Decimal("0")
        return position.value_base / total * 100

    def manual_allocation(self, asset: ManualAsset) -> Decimal:
        total = self.total_value
        if total <= 0:
            return Decimal("0")
        return asset.value_base / total * 100

    @property
    def unified_positions(self) -> tuple[Position, ...]:
        """Per-symbol positions, collapsing all brokers into one entry.

        Quantities and base-currency amounts sum directly; avg_cost and
        price are weighted by quantity. The broker on the unified entries
        is None, signalling "all brokers".
        """
        by_symbol: dict[str, list[Position]] = {}
        for position in self.positions:
            by_symbol.setdefault(position.symbol, []).append(position)
        unified: list[Position] = []
        for symbol, group in by_symbol.items():
            if len(group) == 1:
                unified.append(_with_broker(group[0], None))
                continue
            unified.append(_merge_positions(symbol, group))
        return tuple(unified)

    def positions_by_broker(self) -> dict[str | None, tuple[Position, ...]]:
        """Group positions by broker for the drill-down view."""
        grouped: dict[str | None, list[Position]] = {}
        for position in self.positions:
            grouped.setdefault(position.broker, []).append(position)
        return {broker: tuple(positions) for broker, positions in grouped.items()}


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    name: str
    base_currency: str
    transaction_count: int


def _with_broker(position: Position, broker: str | None) -> Position:
    return Position(
        symbol=position.symbol,
        quantity=position.quantity,
        avg_cost=position.avg_cost,
        price=position.price,
        currency=position.currency,
        value_base=position.value_base,
        cost_base=position.cost_base,
        dividends_base=position.dividends_base,
        fees_base=position.fees_base,
        broker=broker,
    )


def _merge_positions(symbol: str, group: list[Position]) -> Position:
    total_quantity = sum((p.quantity for p in group), Decimal("0"))
    cost_native = sum((p.avg_cost * p.quantity for p in group), Decimal("0"))
    value_native = sum((p.price * p.quantity for p in group), Decimal("0"))
    avg_cost = cost_native / total_quantity if total_quantity > 0 else Decimal("0")
    weighted_price = value_native / total_quantity if total_quantity > 0 else Decimal("0")
    return Position(
        symbol=symbol,
        quantity=total_quantity,
        avg_cost=avg_cost,
        price=weighted_price,
        currency=group[0].currency,
        value_base=sum((p.value_base for p in group), Decimal("0")),
        cost_base=sum((p.cost_base for p in group), Decimal("0")),
        dividends_base=sum((p.dividends_base for p in group), Decimal("0")),
        fees_base=sum((p.fees_base for p in group), Decimal("0")),
        broker=None,
    )
