from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ...domain.portfolio.holdings import (
    Holding,
    HoldingKey,
    active_holdings,
    closed_holdings,
    replay,
)
from ...domain.portfolio.portfolio import ClosedPosition, ManualAsset, Portfolio, Position
from ...domain.portfolio.returns import XirrConvergenceError, build_xirr_cashflows, twr, xirr
from ...domain.portfolio.transactions import Transaction
from ...domain.stocks import Currency
from ..exceptions import PortfolioNotFound
from ..interfaces import (
    FxRateProvider,
    HistoricalFxRateProvider,
    HistoricalPriceProvider,
    PortfolioRepository,
    StockProvider,
)


class _MissingRate(Exception):
    pass


class _MissingData(Exception):
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
        historical_price_provider: HistoricalPriceProvider | None = None,
        clock: Callable[[], date] | None = None,
    ) -> None:
        self._repository = repository
        self._stock_provider = stock_provider
        self._fx_provider = fx_provider
        # Optional: when supplied, the use case computes a money-weighted XIRR
        # from the full transaction history (date-accurate FX conversion).
        self._historical_fx = historical_fx_provider
        # Optional: with both historical FX and historical prices, the use case
        # also computes a time-weighted return (TWR) by revaluing the portfolio
        # at each cashflow boundary.
        self._historical_price = historical_price_provider
        self._clock = clock if clock is not None else date.today

    def handle(self, request: GetPortfolioRequest) -> Portfolio:
        summary = self._repository.find_summary_by_name(request.name, user_id=request.user_id)
        if summary is None:
            raise PortfolioNotFound(request.name)

        transactions = self._repository.get_transactions(request.name, user_id=request.user_id)
        manual_assets = self._repository.get_manual_assets(request.name, user_id=request.user_id)
        return self.build(transactions, manual_assets, Currency(summary.base_currency))

    def build(
        self,
        transactions: list[Transaction],
        manual_assets: list[ManualAsset],
        base_currency: Currency,
    ) -> Portfolio:
        """Build a Portfolio aggregate from a transaction log + manual assets in
        the given base currency. Shared by GetPortfolio (one portfolio) and
        GetOverview (the union of all portfolios)."""
        all_holdings = replay(transactions)
        active = active_holdings(all_holdings)
        closed = closed_holdings(all_holdings)
        if not active and not closed:
            return Portfolio(
                base_currency=base_currency.value,
                manual_assets=tuple(manual_assets),
            )

        # Date-accurate FX rates for every non-base transaction date, used both
        # for XIRR and to convert realized P&L at each sell's own trade date.
        historical_rates = (
            self._gather_rates(transactions, base_currency) if self._historical_fx else {}
        )

        quote_currencies = list({holding.currency for holding in active.values()})
        rates = (
            self._fx_provider.get_rates(base_currency, quote_currencies) if quote_currencies else {}
        )

        def rate_at(currency: Currency, on: date | None) -> Decimal | None:
            if currency == base_currency:
                return Decimal("1")
            historical = historical_rates.get((currency, on)) if on is not None else None
            return historical if historical is not None else rates.get(currency)

        # Fetch quotes for open AND closed symbols — closed positions need only
        # the instrument name (price is irrelevant once sold).
        symbols = list(
            {holding.symbol for holding in active.values()}
            | {holding.symbol for holding in closed.values()}
        )
        stocks = (
            {stock.symbol: stock for stock in self._stock_provider.get_stocks(symbols)}
            if symbols
            else {}
        )

        positions: list[Position] = []
        for holding in active.values():
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
                    realized_pnl_base=self._realized_base(holding, rate_at),
                    name=stock.name,
                )
            )

        closed_positions = [
            self._build_closed(holding, rate_at, stocks) for holding in closed.values()
        ]
        terminal_value = sum((position.value_base for position in positions), Decimal("0"))

        return Portfolio(
            base_currency=base_currency.value,
            positions=tuple(positions),
            manual_assets=tuple(manual_assets),
            closed_positions=tuple(closed_positions),
            xirr_pct=self._compute_xirr(
                transactions, base_currency, terminal_value, historical_rates
            ),
            twr_pct=self._compute_twr(transactions, base_currency, terminal_value),
        )

    def compute_returns(
        self,
        transactions: list[Transaction],
        base_currency: Currency,
        terminal_value: Decimal,
    ) -> tuple[Decimal | None, Decimal | None]:
        """(xirr_pct, twr_pct) for an arbitrary transaction set and terminal
        value — lets GetOverview reuse the return math over the union of all
        portfolios' transactions."""
        historical_rates = (
            self._gather_rates(transactions, base_currency) if self._historical_fx else {}
        )
        xirr_pct = self._compute_xirr(transactions, base_currency, terminal_value, historical_rates)
        twr_pct = self._compute_twr(transactions, base_currency, terminal_value)
        return xirr_pct, twr_pct

    def _realized_base(
        self,
        holding: Holding,
        rate_at: Callable[[Currency, date | None], Decimal | None],
    ) -> Decimal:
        total = Decimal("0")
        for sale in holding.realized_sales:
            rate = rate_at(sale.currency, sale.date)
            if rate is not None:
                total += sale.pnl_native * rate
        return total

    def _build_closed(
        self,
        holding: Holding,
        rate_at: Callable[[Currency, date | None], Decimal | None],
        stocks: dict,
    ) -> ClosedPosition:
        realized_base = Decimal("0")
        basis_base = Decimal("0")
        for sale in holding.realized_sales:
            rate = rate_at(sale.currency, sale.date)
            if rate is None:
                continue
            realized_base += sale.pnl_native * rate
            basis_base += sale.basis_native * rate

        # Return % is computed in native currency so FX moves don't distort it.
        realized_native = sum((sale.pnl_native for sale in holding.realized_sales), Decimal("0"))
        basis_native = holding.cost_basis_sold
        return_pct = realized_native / basis_native * 100 if basis_native > 0 else Decimal("0")

        first_buy = holding.first_buy_date
        last_sell = holding.last_sell_date
        hold_days = (last_sell - first_buy).days if first_buy and last_sell else None

        stock = stocks.get(holding.symbol.upper())
        return ClosedPosition(
            symbol=holding.symbol,
            currency=holding.currency,
            realized_pnl_base=realized_base,
            cost_basis_sold_base=basis_base,
            realized_return_pct=return_pct,
            hold_period_days=hold_days,
            broker=holding.broker,
            name=stock.name if stock is not None else None,
        )

    def _compute_xirr(
        self,
        transactions: list[Transaction],
        base_currency: Currency,
        terminal_value: Decimal,
        historical_rates: dict[tuple[Currency, date], Decimal],
    ) -> Decimal | None:
        if self._historical_fx is None or not transactions:
            return None

        def convert(on: date, currency: Currency, amount: Decimal) -> Decimal:
            if currency == base_currency:
                return amount
            rate = historical_rates.get((currency, on))
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

    def _compute_twr(
        self,
        transactions: list[Transaction],
        base_currency: Currency,
        terminal_value: Decimal,
    ) -> Decimal | None:
        # TWR needs the portfolio's market value at each cashflow boundary, so
        # it requires both historical prices and historical FX.
        if self._historical_price is None or self._historical_fx is None or not transactions:
            return None

        cashflow_dates = sorted({transaction.date for transaction in transactions})
        prices = self._gather_prices(transactions, cashflow_dates)
        rates = self._historical_rates_by_date(transactions, base_currency, cashflow_dates)
        current_value = terminal_value
        today = self._clock()

        def value_at(holdings: dict[HoldingKey, Holding], on: date) -> Decimal:
            total = Decimal("0")
            for holding in holdings.values():
                price = prices.get((holding.symbol, on))
                rate = (
                    Decimal("1")
                    if holding.currency == base_currency
                    else rates.get((holding.currency, on))
                )
                if price is None or rate is None:
                    raise _MissingData()
                total += holding.quantity * price * rate
            return total

        try:
            sub_periods: list[tuple[Decimal, Decimal]] = []
            for index, start_date in enumerate(cashflow_dates):
                # Holdings are constant between consecutive cashflows, so the
                # sub-period return is pure price/FX movement of the same basket.
                held = active_holdings(replay([t for t in transactions if t.date <= start_date]))
                if not held:
                    continue
                start_value = value_at(held, start_date)
                is_last = index + 1 == len(cashflow_dates)
                end_value = current_value if is_last else value_at(held, cashflow_dates[index + 1])
                sub_periods.append((start_value, end_value))
            return twr(sub_periods) if sub_periods else None
        except (ValueError, _MissingData):
            return None

    def _gather_prices(
        self, transactions: list[Transaction], dates: list[date]
    ) -> dict[tuple[str, date], Decimal]:
        symbols = {transaction.symbol for transaction in transactions}
        lookup: dict[tuple[str, date], Decimal] = {}
        for symbol in symbols:
            for on, price in self._historical_price.get_prices(symbol, dates).items():
                lookup[(symbol, on)] = price
        return lookup

    def _historical_rates_by_date(
        self, transactions: list[Transaction], base_currency: Currency, dates: list[date]
    ) -> dict[tuple[Currency, date], Decimal]:
        currencies = {t.currency for t in transactions if t.currency != base_currency}
        lookup: dict[tuple[Currency, date], Decimal] = {}
        for currency in currencies:
            for on, rate in self._historical_fx.get_rates(base_currency, currency, dates).items():
                lookup[(currency, on)] = rate
        return lookup
