from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from pryces.application.interfaces import FxRateProvider, PortfolioRepository, StockProvider
from pryces.application.use_cases.get_overview import GetOverview, GetOverviewRequest
from pryces.application.use_cases.get_portfolio import GetPortfolio
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency, Stock


def _summary(name: str, base: str = "EUR") -> PortfolioSummary:
    return PortfolioSummary(name=name, base_currency=base, transaction_count=1)


def _buy(symbol: str, quantity: str, price: str, currency: Currency = Currency.EUR) -> Transaction:
    return Transaction(
        date=date(2024, 1, 1),
        type=TransactionType.BUY,
        symbol=symbol,
        currency=currency,
        quantity=Decimal(quantity),
        price=Decimal(price),
    )


def _live(symbol: str, price: str) -> Stock:
    return Stock(symbol=symbol.upper(), current_price=Decimal(price))


class TestGetOverview:
    def setup_method(self):
        self.repo = Mock(spec=PortfolioRepository)
        self.stock = Mock(spec=StockProvider)
        self.fx = Mock(spec=FxRateProvider)
        self.fx.get_rates.side_effect = lambda base, quotes: {q: Decimal("1") for q in quotes}
        self.stock.get_stocks.side_effect = lambda symbols: [_live(s, "100") for s in symbols]
        self.repo.get_manual_assets.return_value = []
        builder = GetPortfolio(self.repo, self.stock, self.fx)
        self.use_case = GetOverview(self.repo, builder)

    def _with_transactions(self, by_name: dict[str, list[Transaction]]):
        self.repo.list_portfolios.return_value = [_summary(name) for name in by_name]
        self.repo.get_transactions.side_effect = lambda name, user_id: by_name[name]

    def test_empty_when_no_portfolios(self):
        self.repo.list_portfolios.return_value = []

        result = self.use_case.handle(GetOverviewRequest())

        assert result.portfolio.positions == ()
        assert result.breakdown == ()
        assert result.portfolio.base_currency == "EUR"

    def test_combines_totals_across_portfolios(self):
        self._with_transactions(
            {
                "degiro": [_buy("AAPL", "10", "100")],  # value 10*100 = 1000
                "ibkr": [_buy("MSFT", "5", "100")],  # value 5*100 = 500
            }
        )

        result = self.use_case.handle(GetOverviewRequest())

        assert {p.symbol for p in result.portfolio.positions} == {"AAPL", "MSFT"}
        assert result.portfolio.total_value == Decimal("1500")
        assert len(result.breakdown) == 2
        assert {b.name for b in result.breakdown} == {"degiro", "ibkr"}

    def test_merges_same_symbol_held_in_two_portfolios(self):
        self._with_transactions(
            {
                "degiro": [_buy("AAPL", "10", "100")],
                "ibkr": [_buy("AAPL", "5", "100")],
            }
        )

        result = self.use_case.handle(GetOverviewRequest())

        assert len(result.portfolio.positions) == 1
        aapl = result.portfolio.positions[0]
        assert aapl.symbol == "AAPL"
        assert aapl.quantity == Decimal("15")
        assert aapl.value_base == Decimal("1500")

    def test_picks_majority_base_currency(self):
        assert GetOverview._pick_base_currency(["EUR", "USD", "EUR"]) == Currency.EUR
        assert GetOverview._pick_base_currency(["USD", "USD", "EUR"]) == Currency.USD

    def test_unknown_base_currency_falls_back_to_eur(self):
        assert GetOverview._pick_base_currency(["XXX"]) == Currency.EUR
