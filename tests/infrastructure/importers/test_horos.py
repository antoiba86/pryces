from datetime import date
from decimal import Decimal

import pytest

from pryces.application.exceptions import UnrecognizedImportFormat
from pryces.domain.portfolio.transactions import TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.importers.horos import HorosFundsImporter

_HEADER = "TIPO DE OPERACIÓN;PRODUCTO;VL;IMPORTE;FECHA;;"


def _csv(*rows: str) -> bytes:
    return ("\r\n".join([_HEADER, *rows]) + "\r\n").encode("utf-8")


@pytest.fixture
def importer():
    return HorosFundsImporter()


class TestCanParse:
    def test_accepts_horos_movements(self, importer):
        content = _csv("SUSCRIPCIÓN;HOROS VALUE INTERNACIONAL, FI;218,21 €;200,00 €;01/06/2026;;")
        assert importer.can_parse(content) is True

    def test_rejects_unrelated_csv(self, importer):
        assert importer.can_parse(b"a;b;c\n1;2;3\n") is False
        assert importer.can_parse(b"") is False


class TestParse:
    def test_subscription_becomes_buy_with_units_from_amount_over_nav(self, importer):
        content = _csv("SUSCRIPCIÓN;HOROS VALUE INTERNACIONAL, FI;218,21 €;200,00 €;01/06/2026;;")

        result = importer.parse(content)

        assert len(result.transactions) == 1
        t = result.transactions[0]
        assert t.type == TransactionType.BUY
        assert t.date == date(2026, 6, 1)
        assert t.symbol == "HOROS VALUE INTERNACIONAL, FI"
        assert t.currency == Currency.EUR
        assert t.price == Decimal("218.21")
        assert t.quantity == Decimal("200.00") / Decimal("218.21")  # units = importe / VL
        assert t.fee == Decimal("0")

    def test_reembolso_becomes_sell(self, importer):
        content = _csv("REEMBOLSO;HOROS VALUE INTERNACIONAL, FI;220,00 €;110,00 €;10/06/2026;;")

        result = importer.parse(content)

        assert result.transactions[0].type == TransactionType.SELL

    def test_parses_spanish_thousands_and_decimals(self, importer):
        content = _csv(
            "SUSCRIPCIÓN;HOROS VALUE INTERNACIONAL, FI;1.234,56 €;1.000,00 €;01/06/2026;;"
        )

        t = importer.parse(content).transactions[0]

        assert t.price == Decimal("1234.56")
        assert t.quantity == Decimal("1000.00") / Decimal("1234.56")

    def test_emits_instrument_with_product_name(self, importer):
        content = _csv("SUSCRIPCIÓN;HOROS VALUE INTERNACIONAL, FI;218,21 €;200,00 €;01/06/2026;;")

        result = importer.parse(content)

        assert len(result.instruments) == 1
        assert result.instruments[0].name == "HOROS VALUE INTERNACIONAL, FI"
        assert result.instruments[0].currency == Currency.EUR

    def test_synthesized_raw_id_is_stable(self, importer):
        content = _csv("SUSCRIPCIÓN;HOROS VALUE INTERNACIONAL, FI;218,21 €;200,00 €;01/06/2026;;")

        first = importer.parse(content).transactions[0]
        second = importer.parse(content).transactions[0]

        assert first.raw_id == second.raw_id

    def test_raises_on_unrecognized_content(self, importer):
        with pytest.raises(UnrecognizedImportFormat):
            importer.parse(b"totally;unrelated\n1;2\n")
