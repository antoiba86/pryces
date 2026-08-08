from __future__ import annotations

from decimal import Decimal

from ..domain.portfolio.transactions import Transaction
from ..domain.stocks import Currency

# Deterministic stand-ins. The point of a sample is to keep the *shape* of a
# portfolio — row count, ordering, dates, buy/sell mix, how many distinct
# instruments — while carrying none of its content. Every value below is
# derived from the instrument's position in the file, never from the real
# figure, so nothing about actual holdings can be recovered from the output.
_EXAMPLE_ISIN_PREFIX = "XX000000"
_BASE_PRICE = Decimal("100")
_PRICE_STEP = Decimal("1.5")
_UNITS = Decimal("10")
_FEE = Decimal("1")


def anonymise(transactions: list[Transaction]) -> list[Transaction]:
    """Replaces every identifying and monetary field with a deterministic stand-in.

    Preserved: date, type, currency, broker, and the grouping of rows by
    instrument. Replaced: symbol, quantity, price, amount, fee, raw_id.
    """
    aliases = _aliases(transactions)
    result: list[Transaction] = []
    for index, transaction in enumerate(transactions):
        alias = aliases[transaction.symbol]
        price = _price(index)
        # Rows carry either quantity+price or a bare amount; mirror whichever
        # the original used so the sample exercises the same importer path.
        quantity = _UNITS if transaction.quantity is not None else None
        amount = (
            (price * _UNITS)
            if transaction.amount is not None or transaction.quantity is None
            else None
        )
        result.append(
            Transaction(
                date=transaction.date,
                type=transaction.type,
                symbol=alias.symbol,
                currency=transaction.currency,
                quantity=quantity,
                price=price if transaction.price is not None or quantity is not None else None,
                amount=amount,
                fee=_FEE if transaction.fee else Decimal("0"),
                broker=transaction.broker,
                raw_id=f"sample-{index + 1:04d}",
            )
        )
    return result


class InstrumentAlias:
    """The fake identity standing in for one real instrument."""

    def __init__(self, position: int, currency: Currency | None) -> None:
        self.position = position
        self.symbol = f"EXAMPLE FUND {position}"
        self.name = f"Example Fund {position}"
        # A syntactically valid ISIN shape (2 letters + 9 alphanumerics + check
        # digit) so importers that validate it still accept the sample. XX is
        # not an assigned country code, so it can never collide with a real one.
        self.isin = f"{_EXAMPLE_ISIN_PREFIX}{position:03d}"[:11] + "0"
        self.currency = currency


def aliases_for(transactions: list[Transaction]) -> dict[str, InstrumentAlias]:
    return _aliases(transactions)


def _aliases(transactions: list[Transaction]) -> dict[str, InstrumentAlias]:
    # dict.fromkeys keeps first-seen order, so the same portfolio always
    # produces the same sample — a fixture that changes on every export is
    # useless for comparing runs.
    mapping: dict[str, InstrumentAlias] = {}
    currencies = {t.symbol: t.currency for t in transactions}
    for position, symbol in enumerate(dict.fromkeys(t.symbol for t in transactions), start=1):
        mapping[symbol] = InstrumentAlias(position, currencies.get(symbol))
    return mapping


def _price(index: int) -> Decimal:
    return _BASE_PRICE + _PRICE_STEP * (index % 20)
