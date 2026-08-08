from datetime import date
from decimal import Decimal

from pryces.application.anonymisation import anonymise
from pryces.domain.portfolio.transactions import Transaction, TransactionType
from pryces.domain.stocks import Currency


def _tx(symbol="AAPL", day=1, quantity="10", price="100", amount=None, fee="0", type_=None):
    return Transaction(
        date=date(2026, 6, day),
        type=type_ or TransactionType.BUY,
        symbol=symbol,
        currency=Currency.USD,
        quantity=Decimal(quantity) if quantity is not None else None,
        price=Decimal(price) if price is not None else None,
        amount=Decimal(amount) if amount is not None else None,
        fee=Decimal(fee),
        broker="DEGIRO",
        raw_id="real-id-1234",
    )


class TestPreservesShape:
    """A sample is only useful if it reproduces the portfolio's structure."""

    def test_keeps_the_row_count_and_order(self):
        rows = [_tx(day=1), _tx(day=2), _tx(day=3)]

        result = anonymise(rows)

        assert len(result) == 3
        assert [t.date for t in result] == [t.date for t in rows]

    def test_keeps_dates_types_currency_and_broker(self):
        rows = [_tx(day=5, type_=TransactionType.SELL)]

        result = anonymise(rows)[0]

        assert result.date == date(2026, 6, 5)
        assert result.type == TransactionType.SELL
        assert result.currency == Currency.USD
        assert result.broker == "DEGIRO"

    def test_distinct_instruments_stay_distinct(self):
        rows = [_tx(symbol="AAPL"), _tx(symbol="MSFT"), _tx(symbol="AAPL")]

        symbols = [t.symbol for t in anonymise(rows)]

        assert symbols[0] == symbols[2]
        assert symbols[0] != symbols[1]
        assert len(set(symbols)) == 2

    def test_amount_only_rows_stay_amount_only(self):
        # Importers take different paths for quantity+price versus a bare
        # amount, so the sample has to exercise the same one.
        rows = [_tx(quantity=None, price=None, amount="500")]

        result = anonymise(rows)[0]

        assert result.quantity is None
        assert result.amount is not None


class TestRemovesContent:
    def test_replaces_the_symbol(self):
        assert anonymise([_tx(symbol="0P0001DFE8.F")])[0].symbol != "0P0001DFE8.F"

    def test_replaces_quantity_and_price(self):
        result = anonymise([_tx(quantity="0.916548", price="218.21")])[0]

        assert result.quantity != Decimal("0.916548")
        assert result.price != Decimal("218.21")

    def test_replaces_the_raw_id(self):
        assert anonymise([_tx()])[0].raw_id != "real-id-1234"

    def test_figures_do_not_depend_on_the_real_values(self):
        # The strongest guarantee: two portfolios with identical shape but wildly
        # different amounts must anonymise to exactly the same figures, so nothing
        # about the originals can be inferred from the output.
        cheap = anonymise([_tx(quantity="1", price="2")])
        expensive = anonymise([_tx(quantity="99999", price="123456.78")])

        assert cheap[0].quantity == expensive[0].quantity
        assert cheap[0].price == expensive[0].price

    def test_a_fee_free_row_stays_fee_free(self):
        assert anonymise([_tx(fee="0")])[0].fee == Decimal("0")
        assert anonymise([_tx(fee="1.23")])[0].fee != Decimal("0")


class TestDeterminism:
    def test_same_input_gives_same_output(self):
        rows = [_tx(day=1), _tx(symbol="MSFT", day=2)]

        assert anonymise(rows) == anonymise(rows)

    def test_empty_input(self):
        assert anonymise([]) == []
