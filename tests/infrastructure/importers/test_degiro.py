from datetime import date
from decimal import Decimal

import pytest

from pryces.application.exceptions import UnrecognizedImportFormat
from pryces.domain.portfolio.transactions import TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.importers.degiro import DegiroCsvImporter

_HEADER = (
    "Fecha,Hora,Producto,ISIN,Bolsa de referencia,Centro de ejecución,Número,"
    "Precio,,Valor local,,Valor EUR,Tipo de cambio,Comisión AutoFX,"
    "Costes de transacción y/o externos EUR,Total EUR,ID Orden,"
)

# USD buy — note the trailing empty column before the order id (newer exports).
_USD_BUY = (
    '10-01-2024,15:00,FOO INC,US0000000001,NDQ,XNAS,10,"100,0000",USD,'
    '"-1000,00",USD,"-900,00","1,1000","-0,50","-2,00","-902,50",,order-a'
)
# EUR sell — 17 columns, order id in the last position.
_EUR_SELL = (
    '11-01-2024,10:00,BAR SA,ES0000000002,MAD,GROW,-5,"20,0000",EUR,'
    '"100,00",EUR,"100,00",,"0,00","-2,00","98,00",order-b'
)
# Two fills sharing order-c (partial fill).
_PARTIAL_1 = (
    '12-01-2024,09:30,BAZ INC,US0000000003,NSY,XNYS,6,"50,0000",USD,'
    '"-300,00",USD,"-270,00","1,1000","-0,30","-1,00","-271,30",,order-c'
)
_PARTIAL_2 = (
    '12-01-2024,09:31,BAZ INC,US0000000003,NSY,XNYS,4,"55,0000",USD,'
    '"-220,00",USD,"-198,00","1,1000","-0,20","-1,00","-199,20",,order-c'
)
# GBX (pence) buy.
_GBX_BUY = (
    '13-01-2024,12:00,QUX PLC,GB0000000004,LSE,XLON,100,"500,0000",GBX,'
    '"-50000,00",GBP,"-580,00","0,8600","0,00","-2,00","-582,00",,order-d'
)
# Missing execution venue — a non-trade event that must be skipped.
_NO_VENUE = (
    '14-01-2024,12:00,SPLIT INC,US0000000005,NDQ,,10,"10,0000",USD,'
    '"-100,00",USD,"-90,00","1,1000","0,00","0,00","-90,00",,order-e'
)


def _csv(*rows: str) -> str:
    return "\n".join((_HEADER, *rows)) + "\n"


@pytest.fixture
def importer():
    return DegiroCsvImporter()


class TestCanParse:

    def test_accepts_degiro_header(self, importer):
        assert importer.can_parse(_csv(_USD_BUY)) is True

    def test_rejects_unrelated_csv(self, importer):
        assert importer.can_parse("a,b,c\n1,2,3\n") is False

    def test_rejects_empty(self, importer):
        assert importer.can_parse("") is False


class TestParse:

    def test_parses_usd_buy_with_converted_fee(self, importer):
        result = importer.parse(_csv(_USD_BUY))

        assert result.warnings == ()
        assert len(result.transactions) == 1
        tx = result.transactions[0]
        assert tx.date == date(2024, 1, 10)
        assert tx.type == TransactionType.BUY
        assert tx.symbol == "US0000000001"
        assert tx.quantity == Decimal("10")
        assert tx.price == Decimal("100.0000")
        assert tx.currency == Currency.USD
        # (0.50 + 2.00) EUR * 1.1000 = 2.75 USD
        assert tx.fee == Decimal("2.750000")
        assert tx.broker == "DEGIRO"
        assert tx.raw_id == "order-a"

    def test_parses_eur_sell_without_fee_conversion(self, importer):
        result = importer.parse(_csv(_EUR_SELL))

        tx = result.transactions[0]
        assert tx.type == TransactionType.SELL
        assert tx.quantity == Decimal("5")
        assert tx.currency == Currency.EUR
        assert tx.fee == Decimal("2.00")
        assert tx.raw_id == "order-b"

    def test_merges_partial_fills_sharing_order_id(self, importer):
        result = importer.parse(_csv(_PARTIAL_1, _PARTIAL_2))

        assert len(result.transactions) == 1
        tx = result.transactions[0]
        assert tx.quantity == Decimal("10")
        # quantity-weighted: (50*6 + 55*4) / 10 = 52
        assert tx.price == Decimal("52")
        # (0.30+1.00)*1.1 + (0.20+1.00)*1.1 = 1.43 + 1.32 = 2.75
        assert tx.fee == Decimal("2.750000")
        assert tx.raw_id == "order-c"

    def test_converts_gbx_price_to_gbp(self, importer):
        result = importer.parse(_csv(_GBX_BUY))

        tx = result.transactions[0]
        assert tx.currency == Currency.GBP
        assert tx.price == Decimal("5.000000")
        # (0 + 2.00) EUR * 0.8600 = 1.72 GBP
        assert tx.fee == Decimal("1.720000")

    def test_skips_row_with_missing_venue(self, importer):
        result = importer.parse(_csv(_USD_BUY, _NO_VENUE))

        assert len(result.transactions) == 1
        assert len(result.warnings) == 1
        assert result.warnings[0].affected_rows == (2,)

    def test_emits_instruments_for_resolution(self, importer):
        result = importer.parse(_csv(_USD_BUY, _EUR_SELL))

        by_symbol = {i.symbol: i for i in result.instruments}
        assert by_symbol["US0000000001"].name == "FOO INC"
        assert by_symbol["US0000000001"].exchange == "NDQ"
        assert by_symbol["US0000000001"].isin == "US0000000001"

    def test_raises_on_unrecognized_content(self, importer):
        with pytest.raises(UnrecognizedImportFormat):
            importer.parse("totally,unrelated\n1,2\n")
