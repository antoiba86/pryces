from datetime import date
from decimal import Decimal

import pytest

from pryces.application.exceptions import PortfolioNotFound, SampleFormatUnavailable
from pryces.application.use_cases.export_sample import ExportSample, ExportSampleRequest
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency


class _StubWriter:
    def __init__(self, broker_id, extension="csv"):
        self._broker_id = broker_id
        self._extension = extension
        self.received = None

    @property
    def broker_id(self):
        return self._broker_id

    @property
    def extension(self):
        return self._extension

    def write(self, transactions):
        self.received = list(transactions)
        return b"sample-content"


class _StubRepository:
    def __init__(self, transactions, exists=True):
        self._transactions = transactions
        self._exists = exists

    def find_summary_by_name(self, name, user_id=1):
        return (
            PortfolioSummary(name=name, base_currency="EUR", transaction_count=0)
            if self._exists
            else None
        )

    def get_transactions(self, name, user_id=1):
        return self._transactions


def _tx(broker="Horos"):
    return Transaction(
        date=date(2026, 6, 1),
        type=TransactionType.BUY,
        symbol="0P0001DFE8.F",
        currency=Currency.EUR,
        quantity=Decimal("1"),
        price=Decimal("218.21"),
        broker=broker,
        raw_id="real",
    )


def _use_case(transactions, writers=None, exists=True):
    return ExportSample(_StubRepository(transactions, exists), writers or [_StubWriter("horos")])


class TestExportSample:
    def test_writes_in_the_portfolio_broker_format(self):
        writer = _StubWriter("horos")
        document = _use_case([_tx()], [writer]).handle(ExportSampleRequest("Horos Fondo"))

        assert document.content == b"sample-content"
        assert document.filename == "horos_sample.csv"
        assert document.broker == "Horos"
        assert document.rows == 1

    @pytest.mark.parametrize(
        "label,broker_id",
        [
            ("Horos", "horos"),
            ("Renta 4", "renta4"),
            ("Trade Republic", "trade_republic"),
            ("DEGIRO", "degiro"),
            ("IBKR", "ibkr"),
        ],
    )
    def test_matches_the_stored_broker_label_to_its_writer(self, label, broker_id):
        # Transactions carry a display label while writers use an id; the two
        # differ in case, spacing and punctuation for every broker but one.
        writer = _StubWriter(broker_id)
        document = _use_case([_tx(broker=label)], [writer]).handle(ExportSampleRequest("P"))

        assert document.filename.startswith(broker_id)

    def test_the_writer_never_sees_the_real_transactions(self):
        writer = _StubWriter("horos")
        _use_case([_tx()], [writer]).handle(ExportSampleRequest("P"))

        assert writer.received[0].symbol != "0P0001DFE8.F"
        assert writer.received[0].price != Decimal("218.21")
        assert writer.received[0].raw_id != "real"

    def test_unknown_portfolio_raises(self):
        with pytest.raises(PortfolioNotFound):
            _use_case([], exists=False).handle(ExportSampleRequest("Nope"))

    def test_broker_without_a_writer_raises(self):
        with pytest.raises(SampleFormatUnavailable) as raised:
            _use_case([_tx(broker="Some New Broker")], [_StubWriter("horos")]).handle(
                ExportSampleRequest("P")
            )

        assert "horos" in str(raised.value)

    def test_manual_only_portfolio_raises_with_a_helpful_message(self):
        # No broker means no format to imitate; point at the portable export.
        with pytest.raises(SampleFormatUnavailable) as raised:
            _use_case([_tx(broker=None)]).handle(ExportSampleRequest("P"))

        assert "export" in str(raised.value).lower()

    def test_empty_portfolio_raises(self):
        with pytest.raises(SampleFormatUnavailable):
            _use_case([]).handle(ExportSampleRequest("P"))
