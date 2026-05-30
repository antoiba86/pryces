import json
from datetime import date
from decimal import Decimal

import pytest

from pryces.application.exceptions import UnrecognizedImportFormat
from pryces.domain.portfolio.transactions import TransactionType, WarningLevel
from pryces.domain.stocks import Currency
from pryces.infrastructure.importers.json_ledger import JsonLedgerImporter


@pytest.fixture
def importer():
    return JsonLedgerImporter()


def _ledger(transactions):
    return json.dumps({"base_currency": "EUR", "transactions": transactions})


class TestCanParse:

    def test_accepts_ledger_with_transactions_array(self, importer):
        assert importer.can_parse(_ledger([])) is True

    def test_rejects_non_json(self, importer):
        assert importer.can_parse("not json") is False

    def test_rejects_json_without_transactions_array(self, importer):
        assert importer.can_parse(json.dumps({"base_currency": "EUR"})) is False

    def test_rejects_json_array(self, importer):
        assert importer.can_parse(json.dumps([])) is False


class TestParse:

    def test_parses_buy_transaction(self, importer):
        content = _ledger(
            [
                {
                    "date": "2024-01-10",
                    "type": "buy",
                    "symbol": "AAPL",
                    "currency": "USD",
                    "quantity": "5",
                    "price": "185.00",
                    "fee": "1.0",
                    "broker": "IBKR",
                    "raw_id": "abc",
                }
            ]
        )

        result = importer.parse(content)

        assert result.warnings == ()
        assert len(result.transactions) == 1
        transaction = result.transactions[0]
        assert transaction.date == date(2024, 1, 10)
        assert transaction.type == TransactionType.BUY
        assert transaction.symbol == "AAPL"
        assert transaction.currency == Currency.USD
        assert transaction.quantity == Decimal("5")
        assert transaction.price == Decimal("185.00")
        assert transaction.fee == Decimal("1.0")
        assert transaction.broker == "IBKR"
        assert transaction.raw_id == "abc"

    def test_parses_dividend_transaction(self, importer):
        content = _ledger(
            [
                {
                    "date": "2024-02-12",
                    "type": "dividend",
                    "symbol": "AAPL",
                    "currency": "USD",
                    "amount": "0.24",
                }
            ]
        )

        result = importer.parse(content)

        assert len(result.transactions) == 1
        assert result.transactions[0].amount == Decimal("0.24")

    def test_defaults_missing_fee_to_zero(self, importer):
        content = _ledger(
            [
                {
                    "date": "2024-01-10",
                    "type": "buy",
                    "symbol": "AAPL",
                    "currency": "USD",
                    "quantity": "5",
                    "price": "185.00",
                }
            ]
        )

        result = importer.parse(content)

        assert result.transactions[0].fee == Decimal("0")

    def test_skips_invalid_row_with_warning(self, importer):
        content = _ledger(
            [
                {
                    "date": "2024-01-10",
                    "type": "buy",
                    "symbol": "AAPL",
                    "currency": "USD",
                    "quantity": "-5",
                    "price": "185.00",
                },
                {
                    "date": "2024-01-11",
                    "type": "buy",
                    "symbol": "MSFT",
                    "currency": "USD",
                    "quantity": "3",
                    "price": "400.00",
                },
            ]
        )

        result = importer.parse(content)

        assert len(result.transactions) == 1
        assert result.transactions[0].symbol == "MSFT"
        assert len(result.warnings) == 1
        warning = result.warnings[0]
        assert warning.code == "invalid_row"
        assert warning.level == WarningLevel.WARNING
        assert warning.affected_rows == (0,)

    def test_skips_unknown_currency_with_warning(self, importer):
        content = _ledger(
            [
                {
                    "date": "2024-01-10",
                    "type": "buy",
                    "symbol": "AAPL",
                    "currency": "XYZ",
                    "quantity": "5",
                    "price": "185.00",
                }
            ]
        )

        result = importer.parse(content)

        assert result.transactions == ()
        assert len(result.warnings) == 1

    def test_raises_on_structurally_unrecognized_content(self, importer):
        with pytest.raises(UnrecognizedImportFormat):
            importer.parse("not json")

    def test_raises_when_transactions_key_missing(self, importer):
        with pytest.raises(UnrecognizedImportFormat):
            importer.parse(json.dumps({"base_currency": "EUR"}))
