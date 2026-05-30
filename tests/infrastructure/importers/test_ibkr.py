from datetime import date
from decimal import Decimal

import pytest

from pryces.application.exceptions import UnrecognizedImportFormat
from pryces.domain.portfolio.transactions import TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.importers.ibkr import IbkrActivityImporter

_HEADER = (
    "Transaction History,Header,Date,Account,Description,Transaction Type,Symbol,"
    "Quantity,Price,Price Currency,Gross Amount ,Commission,Net Amount"
)
# USD buy: commission 0.86 EUR converts to USD via implied rate (notional/gross).
_USD_BUY = (
    "Transaction History,Data,2026-05-21,U***25818,SOFI TECHNOLOGIES INC,Buy,SOFI,"
    "55.0,15.4493,USD,-731.406167855,-0.86091202705,-732.2670798820501"
)
_USD_SELL = (
    "Transaction History,Data,2026-05-20,U***25818,AST SPACEMOBILE INC,Sell,ASTS,"
    "-3.0,92.0,USD,237.4152,-0.86560171192,236.54959828807998"
)
# AUD buy with no commission ("-").
_AUD_BUY_NO_FEE = (
    "Transaction History,Data,2026-05-06,U***25818,TITOMIC LTD,Buy,TTT,"
    "752.0,0.255,AUD,-118.12991279999999,-,-118.12991279999999"
)
_DEPOSIT = (
    "Transaction History,Data,2026-05-28,U***25818,Transferencia,Deposit,-,-,-,-,732.0,-,732.0"
)
_FOREX = (
    "Transaction History,Data,2026-05-21,U***25818,Forex,Forex Trade Component,EUR.USD,"
    "-496.28,1.15772,USD,-1.72,-,-1.72"
)


def _csv(*rows: str) -> str:
    preamble = "Statement,Header,Nombre del campo,Valor del campo\nSummary,Data,Divisa base,EUR"
    return "\n".join((preamble, _HEADER, *rows)) + "\n"


@pytest.fixture
def importer():
    return IbkrActivityImporter()


class TestCanParse:

    def test_accepts_ibkr_activity_statement(self, importer):
        assert importer.can_parse(_csv(_USD_BUY)) is True

    def test_rejects_unrelated_csv(self, importer):
        assert importer.can_parse("a,b,c\n1,2,3\n") is False

    def test_rejects_empty(self, importer):
        assert importer.can_parse("") is False


class TestParse:

    def test_parses_usd_buy_with_converted_commission(self, importer):
        result = importer.parse(_csv(_USD_BUY))

        assert result.warnings == ()
        assert len(result.transactions) == 1
        tx = result.transactions[0]
        assert tx.date == date(2026, 5, 21)
        assert tx.type == TransactionType.BUY
        assert tx.symbol == "SOFI"
        assert tx.quantity == Decimal("55.0")
        assert tx.price == Decimal("15.4493")
        assert tx.currency == Currency.USD
        assert tx.broker == "IBKR"
        # 0.86091 EUR * (55*15.4493 / 731.406) ≈ 1.00 USD
        assert tx.fee.quantize(Decimal("0.01")) == Decimal("1.00")

    def test_parses_sell(self, importer):
        result = importer.parse(_csv(_USD_SELL))

        tx = result.transactions[0]
        assert tx.type == TransactionType.SELL
        assert tx.quantity == Decimal("3.0")

    def test_no_commission_is_zero_fee(self, importer):
        result = importer.parse(_csv(_AUD_BUY_NO_FEE))

        tx = result.transactions[0]
        assert tx.currency == Currency.AUD
        assert tx.fee == Decimal("0")

    def test_skips_deposits_and_forex_legs(self, importer):
        result = importer.parse(_csv(_USD_BUY, _DEPOSIT, _FOREX))

        assert len(result.transactions) == 1
        assert result.transactions[0].symbol == "SOFI"
        assert result.warnings == ()

    def test_emits_instruments_with_description_name(self, importer):
        result = importer.parse(_csv(_USD_BUY))

        instrument = result.instruments[0]
        assert instrument.symbol == "SOFI"
        assert instrument.name == "SOFI TECHNOLOGIES INC"

    def test_synthesized_raw_id_is_stable_for_dedup(self, importer):
        first = importer.parse(_csv(_USD_BUY)).transactions[0]
        second = importer.parse(_csv(_USD_BUY)).transactions[0]

        assert first.raw_id == second.raw_id

    def test_distinct_trades_get_distinct_ids(self, importer):
        result = importer.parse(_csv(_USD_BUY, _USD_SELL))

        ids = {tx.raw_id for tx in result.transactions}
        assert len(ids) == 2

    def test_raises_on_unrecognized_content(self, importer):
        with pytest.raises(UnrecognizedImportFormat):
            importer.parse("totally,unrelated\n1,2\n")
