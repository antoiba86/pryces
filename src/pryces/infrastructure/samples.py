from __future__ import annotations

import csv
import io
from decimal import Decimal

from ..application.interfaces import SampleWriter
from ..domain.portfolio.transactions import Transaction, TransactionType

# Each writer emits the columns its own importer reads, in that importer's
# formats. They are deliberately minimal — a valid input, not a byte-perfect
# replica of the broker's export — and the round-trip tests assert that what
# comes out here goes back in through the matching importer.


def _spanish(value: Decimal) -> str:
    # "1234.56" -> "1.234,56" — thousands dot, comma decimal.
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _csv_bytes(rows: list[list[str]], delimiter: str = ",") -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


class HorosSampleWriter(SampleWriter):
    """The hand-pasted Horos movements table."""

    @property
    def broker_id(self) -> str:
        return "horos"

    @property
    def extension(self) -> str:
        return "csv"

    def write(self, transactions: list[Transaction]) -> bytes:
        rows = [["TIPO DE OPERACIÓN", "PRODUCTO", "VL", "IMPORTE", "FECHA"]]
        for transaction in transactions:
            nav = transaction.price or Decimal("1")
            units = transaction.quantity or Decimal("0")
            rows.append(
                [
                    "SUSCRIPCIÓN" if transaction.type == TransactionType.BUY else "REEMBOLSO",
                    transaction.symbol,
                    f"{_spanish(nav)} €",
                    f"{_spanish(nav * units)} €",
                    transaction.date.strftime("%d/%m/%Y"),
                ]
            )
        return _csv_bytes(rows, delimiter=";")


class Renta4SampleWriter(SampleWriter):
    """The Renta 4 "Operaciones en Fondos de Inversión" binary .xls.

    Reproduces the sheet's structure — preamble, the marker line `can_parse`
    looks for, a header row, then a fund-name group header above its operations.
    """

    @property
    def broker_id(self) -> str:
        return "renta4"

    @property
    def extension(self) -> str:
        return "xls"

    def write(self, transactions: list[Transaction]) -> bytes:
        import xlwt

        book = xlwt.Workbook()
        sheet = book.add_sheet("Operaciones")
        sheet.write(0, 0, "NOMBRE DE EJEMPLO")
        sheet.write(5, 0, "Listado de operaciones en Fondos de Inversión de ejemplo")
        header = [
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
        for column, label in enumerate(header):
            sheet.write(7, column, label)

        row = 8
        for symbol in dict.fromkeys(t.symbol for t in transactions):
            sheet.write(row, 0, symbol)
            row += 1
            for transaction in (t for t in transactions if t.symbol == symbol):
                units = transaction.quantity or Decimal("0")
                gross = (transaction.price or Decimal("0")) * units
                values = [
                    transaction.date.strftime("%d/%m/%Y"),
                    (
                        "SUSCRIPCIÓN"
                        if transaction.type == TransactionType.BUY
                        else "REEMBOLSO TOTAL"
                    ),
                    str(units),
                    str(gross),
                    str(gross),
                    str(transaction.fee),
                    "0",
                    str(gross),
                    "Validada",
                ]
                for column, value in enumerate(values):
                    sheet.write(row, column, value)
                row += 1

        buffer = io.BytesIO()
        book.save(buffer)
        return buffer.getvalue()


class DegiroSampleWriter(SampleWriter):
    @property
    def broker_id(self) -> str:
        return "degiro"

    @property
    def extension(self) -> str:
        return "csv"

    # The DEGIRO importer addresses columns by *position*, not by name
    # (`_COL_FX_RATE = 12` and friends), so this layout has to line up exactly.
    # Getting it wrong is quiet: EUR rows skip the FX-rate parse and look fine
    # while non-EUR rows fail, which is why the tests cover a currency mix.
    _HEADER = [
        "Fecha",  # 0
        "Hora",  # 1
        "Producto",  # 2
        "ISIN",  # 3
        "Bolsa de",  # 4
        "Centro de ejecución",  # 5
        "Número",  # 6
        "Precio",  # 7
        "",  # 8  price currency
        "Valor local",  # 9
        "",  # 10
        "Valor",  # 11
        "Tipo de cambio",  # 12
        "Costes AutoFX",  # 13
        "Costes de transacción",  # 14
        "",  # 15
        "Total",  # 16
        "",  # 17
        "ID Orden",  # 18
    ]

    def write(self, transactions: list[Transaction]) -> bytes:
        rows = [list(self._HEADER)]
        for index, transaction in enumerate(transactions, start=1):
            quantity = transaction.quantity or Decimal("0")
            signed = quantity if transaction.type == TransactionType.BUY else -quantity
            price = transaction.price or Decimal("0")
            currency = transaction.currency.value
            gross = price * quantity
            rows.append(
                [
                    transaction.date.strftime("%d-%m-%Y"),
                    "10:00",
                    f"EXAMPLE PRODUCT {index}",
                    _sample_isin(index),
                    "NDQ",
                    "NDQ",
                    str(signed),
                    _spanish(price),
                    currency,
                    _spanish(gross),
                    currency,
                    _spanish(gross),
                    "1",
                    "0,00",
                    _spanish(transaction.fee),
                    "EUR",
                    _spanish(gross),
                    currency,
                    f"sample-order-{index:04d}",
                ]
            )
        return _csv_bytes(rows)


class TradeRepublicSampleWriter(SampleWriter):
    @property
    def broker_id(self) -> str:
        return "trade_republic"

    @property
    def extension(self) -> str:
        return "csv"

    def write(self, transactions: list[Transaction]) -> bytes:
        rows = [
            [
                "category",
                "asset_class",
                "transaction_id",
                "type",
                "date",
                "symbol",
                "name",
                "shares",
                "price",
                "currency",
                "fee",
                "tax",
            ]
        ]
        for index, transaction in enumerate(transactions, start=1):
            rows.append(
                [
                    "TRADING",
                    "FUND",
                    f"sample-{index:04d}",
                    "BUY" if transaction.type == TransactionType.BUY else "SELL",
                    transaction.date.isoformat(),
                    _sample_isin(index),
                    f"Example Instrument {index}",
                    str(transaction.quantity or Decimal("0")),
                    str(transaction.price or Decimal("0")),
                    transaction.currency.value,
                    str(transaction.fee),
                    "0",
                ]
            )
        return _csv_bytes(rows)


class IbkrSampleWriter(SampleWriter):
    """The Transaction History section of an IBKR Activity Statement."""

    @property
    def broker_id(self) -> str:
        return "ibkr"

    @property
    def extension(self) -> str:
        return "csv"

    def write(self, transactions: list[Transaction]) -> bytes:
        section = "Transaction History"
        header = [
            section,
            "Header",
            "Transaction Type",
            "Symbol",
            "Description",
            "Date",
            "Quantity",
            "Price",
            "Price Currency",
            "Gross",
            "Commission",
            "Net",
        ]
        rows = [header]
        for index, transaction in enumerate(transactions, start=1):
            quantity = transaction.quantity or Decimal("0")
            price = transaction.price or Decimal("0")
            gross = quantity * price
            rows.append(
                [
                    section,
                    "Data",
                    "Buy" if transaction.type == TransactionType.BUY else "Sell",
                    transaction.symbol,
                    f"Example Instrument {index}",
                    transaction.date.strftime("%Y-%m-%d"),
                    str(quantity),
                    str(price),
                    transaction.currency.value,
                    str(gross),
                    str(transaction.fee),
                    str(gross + transaction.fee),
                ]
            )
        return _csv_bytes(rows)


def _sample_isin(index: int) -> str:
    # XX is not an assigned country code, so a sample ISIN can never collide
    # with a real instrument.
    return f"XX{index:09d}0"


def default_sample_writers() -> list[SampleWriter]:
    return [
        HorosSampleWriter(),
        Renta4SampleWriter(),
        DegiroSampleWriter(),
        TradeRepublicSampleWriter(),
        IbkrSampleWriter(),
    ]
