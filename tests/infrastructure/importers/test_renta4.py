import io
from datetime import date
from decimal import Decimal

import pytest
import xlwt

from pryces.application.exceptions import UnrecognizedImportFormat
from pryces.domain.portfolio.transactions import TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.importers.renta4 import Renta4FundsImporter

_HEADER = [
    "Fecha",
    "Tipo operación",
    "Participaciones",
    "Importe bruto Div.",
    "Importe bruto",
    "Comisión.",
    "Retención",
    "Importe NETO",
    "Estado",
]


def _xls(rows: list[list], title: str = "Listado de operaciones en Fondos de Inversión") -> bytes:
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Operaciones")
    layout = [
        ["ANTONIO X", "", "", "", "", "", "", "Código Bolsa", "XX0000"],
        [],
        [],
        [],
        [],
        [title],
        [],
        _HEADER,
    ]
    layout.extend(rows)
    for r, row in enumerate(layout):
        for c, value in enumerate(row):
            sheet.write(r, c, value)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _op(fecha, tipo, units, importe, comision=0.0, estado="Validada"):
    return [fecha, tipo, units, importe, importe, comision, 0.0, importe, estado]


@pytest.fixture
def importer():
    return Renta4FundsImporter()


class TestCanParse:
    def test_accepts_funds_export(self, importer):
        content = _xls([["TEST FUND ALPHA"], _op("05/05/2026", "SUSCRIPCIÓN", 7.0, 200.0)])
        assert importer.can_parse(content) is True

    def test_rejects_pension_export(self, importer):
        # Same columns but a "Planes de Pensiones" title — must not match.
        content = _xls(
            [["TEST PP"], _op("13/10/2025", "APORTACIÓN NUEVA", 37.0, 500.0)],
            title="Listado de operaciones en Planes de Pensiones",
        )
        assert importer.can_parse(content) is False

    def test_rejects_non_xls(self, importer):
        assert importer.can_parse(b"Fecha,Tipo operacion\n1,2\n") is False
        assert importer.can_parse(b"") is False


class TestParse:
    def test_parses_subscriptions_as_buys(self, importer):
        content = _xls(
            [
                ["TEST FUND ALPHA"],
                _op("05/05/2026", "SUSCRIPCIÓN", 7.313357, 200.0),
                _op("25/07/2025", "SUSCRIPCIÓN NUEVA", 41.055528, 1000.0),
            ]
        )

        result = importer.parse(content)

        assert [t.type for t in result.transactions] == [TransactionType.BUY, TransactionType.BUY]
        first = result.transactions[0]
        assert first.date == date(2026, 5, 5)
        assert first.symbol == "TEST FUND ALPHA"
        assert first.currency == Currency.EUR
        assert first.quantity == Decimal("7.313357")
        # price = importe / participaciones
        assert first.price == Decimal("200") / Decimal("7.313357")
        assert first.broker == "Renta 4"

    def test_maps_reembolso_to_sell(self, importer):
        content = _xls(
            [
                ["TEST FUND ALPHA"],
                _op("05/05/2026", "SUSCRIPCIÓN", 10.0, 250.0),
                _op("10/06/2026", "REEMBOLSO PARCIAL", 4.0, 120.0),
            ]
        )

        result = importer.parse(content)

        assert result.transactions[1].type == TransactionType.SELL
        assert result.transactions[1].quantity == Decimal("4")

    def test_passes_commission_as_fee(self, importer):
        content = _xls(
            [["TEST FUND ALPHA"], _op("05/05/2026", "SUSCRIPCIÓN", 10.0, 200.0, comision=1.5)]
        )

        result = importer.parse(content)

        assert result.transactions[0].fee == Decimal("1.5")

    def test_emits_instrument_with_fund_name(self, importer):
        content = _xls([["TEST FUND ALPHA"], _op("05/05/2026", "SUSCRIPCIÓN", 7.0, 200.0)])

        result = importer.parse(content)

        assert len(result.instruments) == 1
        instrument = result.instruments[0]
        assert instrument.symbol == "TEST FUND ALPHA"
        assert instrument.name == "TEST FUND ALPHA"
        assert instrument.currency == Currency.EUR

    def test_groups_operations_under_their_fund(self, importer):
        content = _xls(
            [
                ["FUND ALPHA"],
                _op("05/05/2026", "SUSCRIPCIÓN", 7.0, 200.0),
                ["FUND BETA"],
                _op("06/06/2026", "SUSCRIPCIÓN", 3.0, 90.0),
            ]
        )

        result = importer.parse(content)

        assert {t.symbol for t in result.transactions} == {"FUND ALPHA", "FUND BETA"}
        assert {i.name for i in result.instruments} == {"FUND ALPHA", "FUND BETA"}

    def test_synthesized_raw_id_is_stable_for_dedup(self, importer):
        content = _xls([["TEST FUND ALPHA"], _op("05/05/2026", "SUSCRIPCIÓN", 7.0, 200.0)])

        first = importer.parse(content).transactions[0]
        second = importer.parse(content).transactions[0]

        assert first.raw_id == second.raw_id

    def test_raises_on_unrecognized_content(self, importer):
        with pytest.raises(UnrecognizedImportFormat):
            importer.parse(b"not an xls at all")
