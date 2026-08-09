import io
from datetime import date
from decimal import Decimal

import pytest
import xlwt

from pryces.application.exceptions import UnrecognizedImportFormat
from pryces.domain.portfolio.transactions import TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.importers.renta4 import Renta4FundsImporter, Renta4PensionsImporter

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


_PENSION_HEADER = [
    "Fecha",
    "Tipo operación",
    "Participaciones",
    "Importe bruto",
    "Comisión.",
    "Retención",
    "Importe NETO",
    "Estado",
]

_PENSION_TITLE = "Listado de operaciones en Planes de Pensiones desde 01/08/2026 hasta 09/08/2026"


def _pension_xls(rows: list[list], title: str = _PENSION_TITLE) -> bytes:
    """The pension export: same shape as the funds one, minus the 'Importe bruto
    Div.' column, and a different title line."""
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Operaciones")
    layout = [
        ["ANTONIO X", "", "", "", "", "", "Código Bolsa", "XX0000"],
        [],
        [],
        [],
        [],
        [title],
        [],
        _PENSION_HEADER,
    ]
    layout.extend(rows)
    for r, row in enumerate(layout):
        for c, value in enumerate(row):
            sheet.write(r, c, value)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _pension_op(fecha, tipo, units, importe, comision=0.0):
    return [fecha, tipo, units, importe, comision, 0.0, importe, "Validada"]


_PLAN = "RENTPENSIÓN XVIII F.P.(NUMANTIA PP)"


@pytest.fixture
def pensions():
    return Renta4PensionsImporter()


class TestPensionsDetection:
    """The two exports share a layout, so only the title tells them apart — and
    each importer must refuse the other's file."""

    def test_accepts_the_pension_export(self, pensions):
        content = _pension_xls([[_PLAN], _pension_op("05/08/2026", "APORTACIÓN", 6.463274, 100.0)])

        assert pensions.can_parse(content) is True

    def test_refuses_a_funds_export(self, pensions):
        content = _xls([["TEST FUND ALPHA"], _op("05/05/2026", "SUSCRIPCIÓN", 7.0, 200.0)])

        assert pensions.can_parse(content) is False

    def test_the_funds_importer_refuses_a_pension_export(self, importer):
        content = _pension_xls([[_PLAN], _pension_op("05/08/2026", "APORTACIÓN", 6.463274, 100.0)])

        assert importer.can_parse(content) is False

    def test_can_parse_does_not_raise_on_non_xls(self, pensions):
        assert pensions.can_parse(b"not an xls at all") is False


class TestPensionsParse:
    def test_aportacion_becomes_a_buy_at_the_derived_nav(self, pensions):
        # The export gives units and gross amount but no NAV, so the unit price
        # is amount / units — 100 / 6.463274 = 15.4720, which matches the plan's
        # published NAV for that day.
        content = _pension_xls([[_PLAN], _pension_op("05/08/2026", "APORTACIÓN", 6.463274, 100.0)])

        result = pensions.parse(content)

        assert len(result.transactions) == 1
        t = result.transactions[0]
        assert t.type == TransactionType.BUY
        assert t.date == date(2026, 8, 5)
        assert t.symbol == _PLAN
        assert t.currency == Currency.EUR
        assert t.quantity == Decimal("6.463274")
        assert round(t.price, 4) == Decimal("15.4720")

    def test_accepts_the_aportacion_nueva_variant(self, pensions):
        # Real exports use both spellings.
        content = _pension_xls(
            [[_PLAN], _pension_op("13/10/2025", "APORTACIÓN NUEVA", 37.256708, 500.0)]
        )

        assert pensions.parse(content).transactions[0].type == TransactionType.BUY

    def test_payout_verbs_become_sells(self, pensions):
        for verb in ("PRESTACIÓN", "RESCATE TOTAL", "DISPOSICIÓN ANTICIPADA"):
            content = _pension_xls([[_PLAN], _pension_op("05/08/2026", verb, 1.0, 20.0)])

            assert pensions.parse(content).transactions[0].type == TransactionType.SELL, verb

    def test_an_unrecognized_operation_is_reported_not_dropped(self, pensions):
        # No export with a payout has been seen, so the sell verbs are a guess.
        # Silently skipping an unknown one would lose a real movement.
        content = _pension_xls([[_PLAN], _pension_op("05/08/2026", "MOVIMIENTO RARO", 1.0, 20.0)])

        result = pensions.parse(content)

        assert result.transactions == ()
        assert any("MOVIMIENTO RARO" in w.message for w in result.warnings)

    def test_carries_its_own_broker_label_so_it_gets_its_own_portfolio(self, pensions):
        # A pension is locked and taxed differently from a fund; the label is what
        # the single-broker rule uses to keep them apart.
        content = _pension_xls([[_PLAN], _pension_op("05/08/2026", "APORTACIÓN", 6.463274, 100.0)])

        assert pensions.parse(content).transactions[0].broker == "Renta 4 Pensiones"

    def test_emits_the_plan_name_as_its_own_instrument(self, pensions):
        # The plan is a different instrument from the manager's fund of the same
        # name, so it must key separately in the symbol map.
        content = _pension_xls([[_PLAN], _pension_op("05/08/2026", "APORTACIÓN", 6.463274, 100.0)])

        result = pensions.parse(content)

        assert [i.symbol for i in result.instruments] == [_PLAN]
        assert result.instruments[0].currency == Currency.EUR

    def test_raw_id_is_stable_across_reimports(self, pensions):
        content = _pension_xls([[_PLAN], _pension_op("05/08/2026", "APORTACIÓN", 6.463274, 100.0)])

        assert (
            pensions.parse(content).transactions[0].raw_id
            == pensions.parse(content).transactions[0].raw_id
        )

    def test_groups_operations_under_the_preceding_plan_name(self, pensions):
        content = _pension_xls(
            [
                [_PLAN],
                _pension_op("13/10/2025", "APORTACIÓN NUEVA", 37.256708, 500.0),
                _pension_op("05/08/2026", "APORTACIÓN", 6.463274, 100.0),
            ]
        )

        result = pensions.parse(content)

        assert len(result.transactions) == 2
        assert {t.symbol for t in result.transactions} == {_PLAN}

    def test_raises_on_a_funds_export(self, pensions):
        with pytest.raises(UnrecognizedImportFormat):
            pensions.parse(
                _xls([["TEST FUND ALPHA"], _op("05/05/2026", "SUSCRIPCIÓN", 7.0, 200.0)])
            )
