from dataclasses import dataclass

from ...domain.portfolio.holdings import active_holdings, replay
from ...domain.portfolio.portfolio import Portfolio, Position
from ...domain.stocks import Currency
from ..exceptions import PortfolioNotFound
from ..interfaces import FxRateProvider, PortfolioRepository, StockProvider


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
    ) -> None:
        self._repository = repository
        self._stock_provider = stock_provider
        self._fx_provider = fx_provider

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
        )
