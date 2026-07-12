from datetime import date
from decimal import Decimal

import pytest

from pryces.application.exceptions import UnrecognizedImportFormat
from pryces.domain.portfolio.transactions import TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.importers.trade_republic import TradeRepublicCsvImporter

_HEADER = (
    '"datetime","date","account_type","category","type","asset_class","name",'
    '"symbol","shares","price","amount","fee","tax","currency","original_amount",'
    '"original_currency","fx_rate","description","transaction_id","counterparty_name",'
    '"counterparty_iban","payment_reference","mcc_code"'
)

# A fractional savings-plan BUY (EUR), like the real export.
_BUY = (
    '"2026-06-02T08:00:00.000000Z","2026-06-02","DEFAULT","TRADING","BUY","FUND",'
    '"MSCI World USD (Acc)","IE00B60SX394","0.3759680000","132.9900000000","-50.00",'
    '"","","EUR","","","","Savings plan execution","tx-buy-1","","","",""'
)
# A SELL with explicit fee and tax (summed into the cost).
_SELL = (
    '"2026-06-03T09:00:00.000000Z","2026-06-03","DEFAULT","TRADING","SELL","STOCK",'
    '"Some Stock","US0000000001","2.0000000000","100.0000000000","198.00","1.00","0.50",'
    '"EUR","","","","Sell order","tx-sell-1","","","",""'
)
# A CASH row (incoming transfer) — must be ignored.
_CASH = (
    '"2026-04-22T17:15:08.028593Z","2026-04-22","DEFAULT","CASH","TRANSFER_INSTANT_INBOUND",'
    '"","","","","","2620.680000","","","EUR","","","","Incoming transfer","tx-cash-1","","","",""'
)
# A TRADING row with an unsupported type — skipped with a warning.
_UNKNOWN_TYPE = (
    '"2026-06-04T09:00:00.000000Z","2026-06-04","DEFAULT","TRADING","SPLIT","STOCK",'
    '"Split Co","US0000000002","1.0000000000","10.0000000000","0.00","","","EUR","","","",'
    '"Corporate action","tx-split-1","","","",""'
)


def _csv(*rows: str) -> bytes:
    return ("\n".join((_HEADER, *rows)) + "\n").encode("utf-8")


@pytest.fixture
def importer():
    return TradeRepublicCsvImporter()


class TestCanParse:
    def test_accepts_trade_republic_header(self, importer):
        assert importer.can_parse(_csv(_BUY)) is True

    def test_rejects_unrelated_csv(self, importer):
        assert importer.can_parse(b"a,b,c\n1,2,3\n") is False

    def test_rejects_degiro_csv(self, importer):
        degiro = b"Fecha,Hora,Producto,ISIN,Bolsa de referencia\n01-01-2024,10:00,FOO,X,Y\n"
        assert importer.can_parse(degiro) is False

    def test_rejects_empty(self, importer):
        assert importer.can_parse(b"") is False


class TestParse:
    def test_broker_id(self, importer):
        assert importer.broker_id == "trade_republic"

    def test_parses_a_fractional_buy(self, importer):
        result = importer.parse(_csv(_BUY))

        assert result.warnings == ()
        assert len(result.transactions) == 1
        tx = result.transactions[0]
        assert tx.date == date(2026, 6, 2)
        assert tx.type == TransactionType.BUY
        assert tx.symbol == "IE00B60SX394"
        assert tx.quantity == Decimal("0.3759680000")
        assert tx.price == Decimal("132.9900000000")
        assert tx.currency == Currency.EUR
        assert tx.fee == Decimal("0")
        assert tx.broker == "Trade Republic"
        assert tx.raw_id == "tx-buy-1"

    def test_emits_instrument_with_isin_and_name(self, importer):
        result = importer.parse(_csv(_BUY))

        assert len(result.instruments) == 1
        instrument = result.instruments[0]
        assert instrument.symbol == "IE00B60SX394"
        assert instrument.isin == "IE00B60SX394"
        assert instrument.name == "MSCI World USD (Acc)"
        assert instrument.currency == Currency.EUR

    def test_sums_fee_and_tax_into_cost(self, importer):
        result = importer.parse(_csv(_SELL))

        tx = result.transactions[0]
        assert tx.type == TransactionType.SELL
        assert tx.quantity == Decimal("2.0000000000")
        assert tx.fee == Decimal("1.50")  # 1.00 fee + 0.50 tax

    def test_ignores_non_trading_rows(self, importer):
        result = importer.parse(_csv(_BUY, _CASH, _SELL))

        assert len(result.transactions) == 2
        assert {tx.symbol for tx in result.transactions} == {"IE00B60SX394", "US0000000001"}

    def test_skips_unsupported_trade_type_with_warning(self, importer):
        result = importer.parse(_csv(_BUY, _UNKNOWN_TYPE))

        assert len(result.transactions) == 1
        assert len(result.warnings) == 1
        assert "unsupported trade type" in result.warnings[0].message

    def test_deduplicates_instruments_across_rows(self, importer):
        second_buy = _BUY.replace("tx-buy-1", "tx-buy-2").replace("0.3759680000", "0.0069170000")
        result = importer.parse(_csv(_BUY, second_buy))

        assert len(result.transactions) == 2  # distinct transaction ids
        assert len(result.instruments) == 1  # same ISIN collapses

    def test_raises_on_unrecognized_content(self, importer):
        with pytest.raises(UnrecognizedImportFormat):
            importer.parse(b"not,a,trade republic,file\n1,2,3,4\n")
