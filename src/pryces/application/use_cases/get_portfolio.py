from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ...domain.portfolio.holdings import active_holdings, replay
from ...domain.portfolio.portfolio import Portfolio, Position
from ...domain.portfolio.returns import XirrConvergenceError, build_xirr_cashflows, xirr
from ...domain.portfolio.transactions import Transaction
from ...domain.stocks import Currency
from ..exceptions import PortfolioNotFound
from ..interfaces import (
    FxRateProvider,
    HistoricalFxRateProvider,
    PortfolioRepository,
    StockProvider,
)


class _MissingRate(Exception):
    pass


@dataclass(frozen=True)
class GetPortfolioRequest:
    name: str
    user_id: int = 1


class GetPortfolio:
    def __init__(
        self,
        repository: PortfolioRepository,
        stock_provider: StockProvider,
        fx_provider: FxRateProvider,
        historical_fx_provider: HistoricalFxRateProvider | None = None,
        clock: Callable[[], date] | None = None,
    ) -> None:
        self._repository = repository
        self._stock_provider = stock_provider
        self._fx_provider = fx_provider
        # Optional: when supplied, the use case computes a money-weighted XIRR
        # from the full transaction history (date-accurate FX conversion).
        self._historical_fx = historical_fx_provider
        self._clock = clock if clock is not None else date.today

    def handle(self, request: GetPortfolioRequest) -> Portfolio:
        summary = self._repository.find_summary_by_name(request.name, user_id=request.user_id)
        if summary is None:
            raise PortfolioNotFound(request.name)

        transactions = self._repository.get_transactions(request.name, user_id=request.user_id)
        manual_assets = self._repository.get_manual_assets(request.name, user_id=request.user_id)
        base_currency = Currency(summary.base_currency)

        holdings = active_holdings(replay(transactions))
        if not holdings:
            return Portfolio(
                base_currency=summary.base_currency,
                manual_assets=tuple(manual_assets),
            )

        symbols = list({holding.symbol for holding in holdings.values()})
        stocks = {stock.symbol: stock for stock in self._stock_provider.get_stocks(symbols)}

        quote_currencies = list({holding.currency for holding in holdings.values()})
        rates = self._fx_provider.get_rates(base_currency, quote_currencies)

        positions: list[Position] = []
        for holding in holdings.values():
            stock = stocks.get(holding.symbol.upper())
            if stock is None:
                continue
            rate = rates.get(holding.currency)
            if rate is None:
                continue
            price = stock.current_price
            positions.append(
                Position(
                    symbol=holding.symbol,
                    quantity=holding.quantity,
                    avg_cost=holding.avg_cost,
                    price=price,
                    currency=holding.currency,
                    value_base=holding.quantity * price * rate,
                    cost_base=holding.cost_total * rate,
                    dividends_base=holding.dividends * rate,
                    fees_base=holding.fees * rate,
                    broker=holding.broker,
                )
            )

        return Portfolio(
            base_currency=summary.base_currency,
            positions=tuple(positions),
            manual_assets=tuple(manual_assets),
            xirr_pct=self._compute_xirr(transactions, base_currency, positions),
        )

    def _compute_xirr(
        self,
        transactions: list[Transaction],
        base_currency: Currency,
        positions: list[Position],
    ) -> Decimal | None:
        if self._historical_fx is None or not transactions:
            return None

        rates = self._gather_rates(transactions, base_currency)
        terminal_value = sum((position.value_base for position in positions), Decimal("0"))

        def convert(on: date, currency: Currency, amount: Decimal) -> Decimal:
            if currency == base_currency:
                return amount
            rate = rates.get((currency, on))
            if rate is None:
                raise _MissingRate()
            return amount * rate

        try:
            cashflows = build_xirr_cashflows(transactions, convert, terminal_value, self._clock())
            return xirr(cashflows)
        except (ValueError, XirrConvergenceError, _MissingRate):
            return None

    def _gather_rates(
        self, transactions: list[Transaction], base_currency: Currency
    ) -> dict[tuple[Currency, date], Decimal]:
        dates_by_currency: dict[Currency, set[date]] = defaultdict(set)
        for transaction in transactions:
            if transaction.currency != base_currency:
                dates_by_currency[transaction.currency].add(transaction.date)

        lookup: dict[tuple[Currency, date], Decimal] = {}
        for currency, dates in dates_by_currency.items():
            rates = self._historical_fx.get_rates(base_currency, currency, sorted(dates))
            for on, rate in rates.items():
                lookup[(currency, on)] = rate
        return lookup
