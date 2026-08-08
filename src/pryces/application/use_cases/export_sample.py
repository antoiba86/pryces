from __future__ import annotations

from dataclasses import dataclass

from ...domain.portfolio.transactions import distinct_brokers
from ..anonymisation import anonymise
from ..exceptions import PortfolioNotFound, SampleFormatUnavailable
from ..interfaces import PortfolioRepository, SampleWriter


@dataclass(frozen=True)
class ExportSampleRequest:
    portfolio_name: str
    user_id: int = 1


@dataclass(frozen=True)
class SampleDocument:
    filename: str
    content: bytes
    broker: str
    rows: int


class ExportSample:
    """Produces an anonymised, re-importable example file for one portfolio.

    Reads the portfolio's transactions, strips every identifying and monetary
    value via `anonymise`, and writes the result in the format of the broker
    that portfolio belongs to — portfolios are single-broker, so that broker is
    unambiguous. The output is a valid input for the matching importer, which
    makes it usable as a test fixture and as a bug report attachment that
    exposes nothing about real holdings.
    """

    def __init__(self, repository: PortfolioRepository, writers: list[SampleWriter]) -> None:
        self._repository = repository
        # Transactions carry the broker *label* ("Renta 4", "Trade Republic")
        # while writers are keyed by `broker_id` ("renta4", "trade_republic").
        # Reducing both to alphanumerics matches them without a second mapping
        # table that could drift out of step with the importers.
        self._writers = {_key(writer.broker_id): writer for writer in writers}
        self._names = sorted(writer.broker_id for writer in writers)

    def handle(self, request: ExportSampleRequest) -> SampleDocument:
        if self._repository.find_summary_by_name(request.portfolio_name, request.user_id) is None:
            raise PortfolioNotFound(request.portfolio_name)

        transactions = self._repository.get_transactions(request.portfolio_name, request.user_id)
        broker = self._broker(transactions)
        writer = self._writers.get(_key(broker))
        if writer is None:
            raise SampleFormatUnavailable(broker, self._names)

        samples = anonymise(transactions)
        return SampleDocument(
            filename=f"{writer.broker_id}_sample.{writer.extension}",
            content=writer.write(samples),
            broker=broker,
            rows=len(samples),
        )

    @staticmethod
    def _broker(transactions) -> str:
        brokers = distinct_brokers(transactions)
        if not brokers:
            # Manual-only or empty: there is no broker format to imitate. The
            # portable JSON export already covers that case.
            raise SampleFormatUnavailable(None, [])
        # The single-broker rule guarantees one, but be explicit rather than
        # silently picking from a set if a portfolio ever slips through mixed.
        return sorted(brokers)[0]


def _key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())
