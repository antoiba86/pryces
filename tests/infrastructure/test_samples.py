from datetime import date
from decimal import Decimal

import pytest

from pryces.application.anonymisation import anonymise
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency
from pryces.infrastructure.importers.degiro import DegiroCsvImporter
from pryces.infrastructure.importers.horos import HorosFundsImporter
from pryces.infrastructure.importers.ibkr import IbkrActivityImporter
from pryces.infrastructure.importers.renta4 import Renta4FundsImporter
from pryces.infrastructure.importers.trade_republic import TradeRepublicCsvImporter
from pryces.infrastructure.samples import default_sample_writers

_IMPORTERS = {
    "degiro": DegiroCsvImporter,
    "horos": HorosFundsImporter,
    "ibkr": IbkrActivityImporter,
    "renta4": Renta4FundsImporter,
    "trade_republic": TradeRepublicCsvImporter,
}

# Deliberately real-looking: a ticker, a fund code, distinctive prices and
# fractional units. The no-leak test asserts none of it reaches the output.
_REAL = [
    Transaction(
        date=date(2026, 6, 1),
        type=TransactionType.BUY,
        symbol="0P0001DFE8.F",
        currency=Currency.EUR,
        quantity=Decimal("0.916548"),
        price=Decimal("218.21"),
        fee=Decimal("0"),
        broker="Horos",
        raw_id="8af5e3758b60b17a",
    ),
    Transaction(
        date=date(2026, 7, 2),
        type=TransactionType.BUY,
        symbol="0P0001DFE8.F",
        currency=Currency.EUR,
        quantity=Decimal("0.929195"),
        price=Decimal("215.24"),
        fee=Decimal("1.5"),
        broker="Horos",
        raw_id="e2f5db9b27ba778b",
    ),
    Transaction(
        date=date(2026, 8, 4),
        type=TransactionType.SELL,
        symbol="ASTS",
        currency=Currency.EUR,
        quantity=Decimal("3"),
        price=Decimal("40.125"),
        fee=Decimal("0"),
        broker="Horos",
        raw_id="4c51dd403f9cbfd3",
    ),
    # A non-EUR row on purpose. DEGIRO's importer reads columns by position and
    # only parses the FX-rate column for foreign-currency trades, so an all-EUR
    # fixture silently passes on a misaligned layout.
    Transaction(
        date=date(2026, 9, 9),
        type=TransactionType.BUY,
        symbol="IONQ",
        currency=Currency.USD,
        quantity=Decimal("7"),
        price=Decimal("33.44"),
        fee=Decimal("0.5"),
        broker="Horos",
        raw_id="ffffffffffffffff",
    ),
]

_SECRETS = [
    "0P0001DFE8",
    "ASTS",
    "218.21",
    "218,21",
    "215.24",
    "215,24",
    "0.916548",
    "40.125",
    "8af5e3758b60b17a",
]


@pytest.fixture
def samples():
    return anonymise(_REAL)


@pytest.mark.parametrize("writer", default_sample_writers(), ids=lambda w: w.broker_id)
class TestSampleWriters:
    def test_output_is_importable_by_the_matching_importer(self, writer, samples):
        # The property that keeps writers and importers in step: a sample is not
        # a mock-up, it is a valid input for the broker it imitates.
        content = writer.write(samples)
        importer = _IMPORTERS[writer.broker_id]()

        assert importer.can_parse(content) is True
        result = importer.parse(content)
        assert len(result.transactions) == len(samples)
        assert result.warnings == ()

    def test_output_leaks_nothing_from_the_real_portfolio(self, writer, samples):
        content = writer.write(samples)

        for secret in _SECRETS:
            assert secret.encode() not in content, f"{writer.broker_id} leaked {secret}"

    def test_output_is_deterministic(self, writer, samples):
        # A fixture that changes on every export is useless for comparing runs.
        assert writer.write(samples) == writer.write(samples)

    def test_empty_portfolio_still_writes_a_readable_header(self, writer):
        content = writer.write([])

        assert _IMPORTERS[writer.broker_id]().can_parse(content) is True

    def test_round_trip_preserves_dates_and_sides(self, writer, samples):
        parsed = _IMPORTERS[writer.broker_id]().parse(writer.write(samples)).transactions

        assert [t.date for t in sorted(parsed, key=lambda t: t.date)] == [
            t.date for t in sorted(samples, key=lambda t: t.date)
        ]
        assert sorted(t.type for t in parsed) == sorted(t.type for t in samples)
