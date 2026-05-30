from __future__ import annotations

from .interfaces import LoggerFactory, TransactionImporter


class ImporterRegistry:
    """Holds the available transaction importers and resolves which one to use.

    Auto-detection runs each importer's `can_parse` in registration order and
    returns the first match, so importers must be registered most-specific
    first (broker CSVs before the generic JSON ledger). Depends only on the
    `TransactionImporter` port, so it lives in the application layer; concrete
    importers are injected at the composition root.
    """

    def __init__(
        self,
        importers: list[TransactionImporter],
        logger_factory: LoggerFactory,
    ) -> None:
        self._importers = list(importers)
        self._logger = logger_factory.get_logger(__name__)

    @property
    def importers(self) -> list[TransactionImporter]:
        return list(self._importers)

    def auto_detect(self, content: str) -> TransactionImporter | None:
        for importer in self._importers:
            if importer.can_parse(content):
                self._logger.info(f"Auto-detected importer: {importer.broker_id}")
                return importer
        self._logger.warning("No importer could parse the supplied content")
        return None

    def get(self, broker_id: str) -> TransactionImporter | None:
        for importer in self._importers:
            if importer.broker_id == broker_id:
                return importer
        return None
