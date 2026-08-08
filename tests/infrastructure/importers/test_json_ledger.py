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


def _export(portfolios, version=1):
    return json.dumps(
        {
            "format": "pryces-export",
            "version": version,
            "exported_at": "2026-08-08T00:00:00+00:00",
            "portfolios": portfolios,
        }
    ).encode()


def _entry(name="Horos Fondo", transactions=None, manual_assets=None):
    entry = {
        "name": name,
        "base_currency": "EUR",
        "transactions": transactions if transactions is not None else [],
    }
    if manual_assets is not None:
        entry["manual_assets"] = manual_assets
    return entry


_ROW = {
    "date": "2026-06-01",
    "type": "buy",
    "symbol": "0P0001DFE8.F",
    "currency": "EUR",
    "quantity": "0.916548",
    "price": "218.21",
    "fee": "0",
    "broker": "Horos",
    "raw_id": "abc123",
}


class TestExportDocument:
    """The dashboard's Export button writes an envelope, not a raw ledger. A
    portfolio has to accept its own export back, or export and import are not
    symmetric."""

    def test_accepts_a_single_portfolio_export(self, importer):
        content = _export([_entry(transactions=[_ROW])])

        assert importer.can_parse(content) is True
        result = importer.parse(content)

        assert len(result.transactions) == 1
        assert result.transactions[0].symbol == "0P0001DFE8.F"
        assert result.transactions[0].raw_id == "abc123"

    def test_preserves_raw_ids_so_a_reimport_dedupes(self, importer):
        content = _export([_entry(transactions=[_ROW])])

        first = importer.parse(content).transactions[0]
        second = importer.parse(content).transactions[0]

        assert first.raw_id == second.raw_id == "abc123"

    def test_an_empty_export_yields_no_transactions(self, importer):
        assert importer.parse(_export([])).transactions == ()

    def test_refuses_a_multi_portfolio_backup_and_says_why(self, importer):
        # Flattening several portfolios into one destroys the split silently.
        content = _export([_entry(name="Horos Fondo"), _entry(name="Numantia")])

        assert importer.can_parse(content) is True
        with pytest.raises(UnrecognizedImportFormat) as raised:
            importer.parse(content)

        assert "2 portfolios" in str(raised.value)
        assert "Horos Fondo" in str(raised.value)
        assert "Numantia" in str(raised.value)

    def test_refuses_an_unsupported_version(self, importer):
        with pytest.raises(UnrecognizedImportFormat) as raised:
            importer.parse(_export([_entry()], version=99))

        assert "99" in str(raised.value)

    def test_warns_that_manual_assets_are_ignored(self, importer):
        content = _export(
            [_entry(transactions=[_ROW], manual_assets=[{"name": "Flat", "value_base": "1"}])]
        )

        result = importer.parse(content)

        assert len(result.transactions) == 1
        assert any(w.code == "manual_assets_ignored" for w in result.warnings)

    def test_no_warning_when_there_are_no_manual_assets(self, importer):
        result = importer.parse(_export([_entry(transactions=[_ROW], manual_assets=[])]))

        assert result.warnings == ()

    def test_malformed_rows_still_warn_rather_than_abort(self, importer):
        content = _export([_entry(transactions=[_ROW, {"date": "nope"}])])

        result = importer.parse(content)

        assert len(result.transactions) == 1
        assert len(result.warnings) == 1

    def test_a_plain_object_is_still_rejected(self, importer):
        assert importer.can_parse(b'{"format": "something-else"}') is False
