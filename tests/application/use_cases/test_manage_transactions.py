from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from pryces.application.exceptions import PortfolioNotFound, TransactionNotFound
from pryces.application.interfaces import PortfolioRepository, SymbolResolver
from pryces.application.use_cases.manage_transactions import (
    AddTransaction,
    AddTransactionRequest,
    DeleteTransaction,
    UpdateTransaction,
    UpdateTransactionRequest,
)
from pryces.domain.portfolio.transactions import TransactionType
from pryces.domain.stocks import Currency


def _add_request(**overrides):
    base = dict(
        portfolio_name="main",
        date=date(2024, 1, 10),
        type=TransactionType.BUY,
        symbol="AAPL",
        currency=Currency.USD,
        quantity=Decimal("5"),
        price=Decimal("100"),
    )
    base.update(overrides)
    return AddTransactionRequest(**base)


class TestAddTransaction:
    def setup_method(self):
        self.repo = Mock(spec=PortfolioRepository)
        self.resolver = Mock(spec=SymbolResolver)
        self.use_case = AddTransaction(self.repo, self.resolver)

    def test_resolves_symbol_and_persists_broker_less(self):
        self.resolver.resolve.return_value = "AAPL"
        self.repo.add_transaction.return_value = "new-id"

        result = self.use_case.handle(_add_request(symbol="Apple"))

        assert result == "new-id"
        transaction = self.repo.add_transaction.call_args.args[1]
        assert transaction.symbol == "AAPL"
        assert transaction.broker is None
        assert transaction.raw_id.startswith("manual-")

    def test_falls_back_to_typed_symbol_when_unresolved(self):
        self.resolver.resolve.return_value = None

        self.use_case.handle(_add_request(symbol="WEIRDTICKER"))

        transaction = self.repo.add_transaction.call_args.args[1]
        assert transaction.symbol == "WEIRDTICKER"

    def test_propagates_portfolio_not_found(self):
        self.resolver.resolve.return_value = "AAPL"
        self.repo.add_transaction.side_effect = PortfolioNotFound("ghost")

        with pytest.raises(PortfolioNotFound):
            self.use_case.handle(_add_request())


class TestUpdateTransaction:
    def setup_method(self):
        self.repo = Mock(spec=PortfolioRepository)
        self.use_case = UpdateTransaction(self.repo)

    def test_updates_without_re_resolving_symbol(self):
        self.use_case.handle(
            UpdateTransactionRequest(
                portfolio_name="main",
                transaction_id="abc",
                date=date(2024, 1, 10),
                type=TransactionType.BUY,
                symbol="TTT.AX",
                currency=Currency.AUD,
                quantity=Decimal("10"),
                price=Decimal("2"),
            )
        )

        name, transaction_id, transaction = self.repo.update_transaction.call_args.args[:3]
        assert (name, transaction_id) == ("main", "abc")
        assert transaction.symbol == "TTT.AX"
        assert transaction.quantity == Decimal("10")

    def test_propagates_transaction_not_found(self):
        self.repo.update_transaction.side_effect = TransactionNotFound("abc")

        with pytest.raises(TransactionNotFound):
            self.use_case.handle(
                UpdateTransactionRequest(
                    portfolio_name="main",
                    transaction_id="abc",
                    date=date(2024, 1, 10),
                    type=TransactionType.BUY,
                    symbol="AAPL",
                    currency=Currency.USD,
                    quantity=Decimal("1"),
                    price=Decimal("1"),
                )
            )


class TestDeleteTransaction:
    def test_delegates_to_repository(self):
        repo = Mock(spec=PortfolioRepository)
        DeleteTransaction(repo).handle("main", "abc")
        repo.delete_transaction.assert_called_once_with("main", "abc", 1)

    def test_propagates_not_found(self):
        repo = Mock(spec=PortfolioRepository)
        repo.delete_transaction.side_effect = TransactionNotFound("abc")
        with pytest.raises(TransactionNotFound):
            DeleteTransaction(repo).handle("main", "abc")
