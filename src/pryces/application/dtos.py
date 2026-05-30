from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pryces.domain.stocks import Stock


@dataclass(frozen=True, slots=True)
class StockDTO:
    symbol: str
    current_price: Decimal
    name: str | None = None
    currency: str | None = None
    previous_close_price: Decimal | None = None
    open_price: Decimal | None = None
    day_high: Decimal | None = None
    day_low: Decimal | None = None
    fifty_day_average: Decimal | None = None
    two_hundred_day_average: Decimal | None = None
    fifty_two_week_high: Decimal | None = None
    fifty_two_week_low: Decimal | None = None
    market_cap: Decimal | None = None
    market_state: str | None = None
    price_delay_in_minutes: int | None = None
    kind: str | None = None
    cap_size: str | None = None

    @staticmethod
    def from_stock(stock: Stock) -> StockDTO:
        return StockDTO(
            symbol=stock.symbol,
            current_price=stock.current_price,
            name=stock.name,
            currency=stock.currency.value if stock.currency is not None else None,
            previous_close_price=stock.previous_close_price,
            open_price=stock.open_price,
            day_high=stock.day_high,
            day_low=stock.day_low,
            fifty_day_average=stock.fifty_day_average,
            two_hundred_day_average=stock.two_hundred_day_average,
            fifty_two_week_high=stock.fifty_two_week_high,
            fifty_two_week_low=stock.fifty_two_week_low,
            market_cap=stock.market_cap,
            market_state=stock.market_state.value if stock.market_state else None,
            price_delay_in_minutes=stock.price_delay_in_minutes,
            kind=stock.kind.value if stock.kind else None,
            cap_size=stock.cap_size.value if stock.cap_size else None,
        )


@dataclass(frozen=True, slots=True)
class TargetPriceDTO:
    symbol: str
    target: Decimal


@dataclass(frozen=True, slots=True)
class ImportResultDTO:
    broker: str
    parsed: int
    inserted: int
    unresolved_symbols: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def duplicates(self) -> int:
        return self.parsed - self.inserted
