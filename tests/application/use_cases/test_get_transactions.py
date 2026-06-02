from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from pryces.application.exceptions import PortfolioNotFound
from pryces.application.interfaces import PortfolioRepository
from pryces.application.use_cases.get_transactions import GetTransactions
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency


def _buy(symbol: str, when: date) -> Transaction:
    return Transaction(
        date=when,
        type=TransactionType.BUY,
        symbol=symbol,
        currency=Currency.EUR,
        quantity=Decimal("1"),
        price=Decimal("10"),
    )


class TestGetTransactions:
    def setup_method(self):
        self.repo = Mock(spec=PortfolioRepository)
        self.use_case = GetTransactions(self.repo)

    def test_for_portfolio_filters_by_symbol_and_sorts(self):
        self.repo.get_transactions.return_value = [
            _buy("VYT.MC", date(2026, 3, 3)),
            _buy("AAPL", date(2026, 1, 1)),
            _buy("VYT.MC", date(2026, 2, 3)),
        ]

        records = self.use_case.for_portfolio("degiro", symbol="vyt.mc")

        assert [r.transaction.symbol for r in records] == ["VYT.MC", "VYT.MC"]
        assert [r.transaction.date for r in records] == [date(2026, 2, 3), date(2026, 3, 3)]
        assert {r.portfolio for r in records} == {"degiro"}

    def test_for_portfolio_propagates_not_found(self):
        self.repo.get_transactions.side_effect = PortfolioNotFound("ghost")

        with pytest.raises(PortfolioNotFound):
            self.use_case.for_portfolio("ghost")

    def test_across_portfolios_tags_and_sorts(self):
        self.repo.list_portfolios.return_value = [
            PortfolioSummary(name="degiro", base_currency="EUR", transaction_count=1),
            PortfolioSummary(name="ibkr", base_currency="EUR", transaction_count=1),
        ]
        by_name = {
            "degiro": [_buy("VYT.MC", date(2026, 3, 3))],
            "ibkr": [_buy("VYT.MC", date(2026, 1, 5)), _buy("AAPL", date(2026, 2, 2))],
        }
        self.repo.get_transactions.side_effect = lambda name, user_id: by_name[name]

        records = self.use_case.across_portfolios(symbol="VYT.MC")

        # Both VYTRUS rows, sorted by date, tagged with their portfolio.
        assert [(r.portfolio, r.transaction.date) for r in records] == [
            ("ibkr", date(2026, 1, 5)),
            ("degiro", date(2026, 3, 3)),
        ]
