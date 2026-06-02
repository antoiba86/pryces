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
    # Realized P&L already booked on this still-open holding via partial sells
    # (base currency, converted at each sell's own trade-date FX rate).
    realized_pnl_base: Decimal = Decimal("0")
    # Human-readable instrument name from the live quote (e.g. "Apple Inc.").
    name: str | None = None
    # Money-weighted (XIRR) return over this holding's whole history (all
    # buys/sells/dividends + current value). None when it can't be computed or
    # when the position is a cross-source merge (XIRR isn't averageable).
    lifetime_return_pct: Decimal | None = None

    @property
    def unrealized_pnl_base(self) -> Decimal:
        return self.value_base - self.cost_base

    @property
    def total_return_pct(self) -> Decimal:
        return total_return(self.value_base, self.cost_base, self.dividends_base, self.fees_base)

    @property
    def lifetime_pnl_base(self) -> Decimal:
        """Total result for this stock: paper gain on what's held now + realized
        gains already booked + dividends received (all base currency)."""
        return self.unrealized_pnl_base + self.realized_pnl_base + self.dividends_base


@dataclass(frozen=True, slots=True)
class ClosedPosition:
    """A symbol fully sold out of the portfolio. Carries the realized result so
    past performance stays visible after the holding leaves the open book."""

    symbol: str
    currency: Currency
    realized_pnl_base: Decimal
    cost_basis_sold_base: Decimal
    realized_return_pct: Decimal
    hold_period_days: int | None = None
    broker: str | None = None
    name: str | None = None


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
    closed_positions: tuple[ClosedPosition, ...] = field(default_factory=tuple)
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
    def total_realized_pnl(self) -> Decimal:
        """Realized capital gains across closed positions and partial sells of
        still-open positions."""
        from_open = sum((p.realized_pnl_base for p in self.positions), Decimal("0"))
        from_closed = sum((c.realized_pnl_base for c in self.closed_positions), Decimal("0"))
        return from_open + from_closed

    @property
    def total_profit(self) -> Decimal:
        """Lifetime profit: unrealized gains on current holdings + realized
        capital gains + dividends received."""
        return self.total_unrealized_pnl + self.total_realized_pnl + self.total_dividends

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
        """Per-symbol positions, collapsing the same symbol held at multiple
        brokers into one entry.

        Quantities and base-currency amounts sum directly; avg_cost and price
        are weighted by quantity. A symbol held at a single broker keeps that
        broker; only a genuinely cross-broker merge clears it to None
        (signalling "multiple brokers").
        """
        by_symbol: dict[str, list[Position]] = {}
        for position in self.positions:
            by_symbol.setdefault(position.symbol, []).append(position)
        unified: list[Position] = []
        for symbol, group in by_symbol.items():
            if len(group) == 1:
                unified.append(group[0])
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


@dataclass(frozen=True, slots=True)
class PortfolioBreakdown:
    """A single portfolio's contribution to the unified overview (values in the
    overview's base currency; `base_currency` is the portfolio's own, for display)."""

    name: str
    base_currency: str
    total_value: Decimal
    total_profit: Decimal
    total_return_pct: Decimal


@dataclass(frozen=True, slots=True)
class Overview:
    """Unified net-worth rollup: one combined Portfolio (positions merged across
    all portfolios) plus a per-portfolio breakdown for drill-down."""

    portfolio: Portfolio
    breakdown: tuple[PortfolioBreakdown, ...] = ()


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
        realized_pnl_base=sum((p.realized_pnl_base for p in group), Decimal("0")),
        name=group[0].name,
    )
