from __future__ import annotations

from ...application.interfaces import TransactionImporter
from ...domain.portfolio.transactions import ImportResult

_BROKER_ID = "ibkr"


class IbkrFlexImporter(TransactionImporter):
    """Skeleton for Interactive Brokers Flex Query statements.

    Registered to stamp the importer abstraction as multi-broker, but the
    Flex format (section splitter, corporate actions, options, forex events)
    is deferred to Phase 2. Until then it never auto-detects and `parse`
    raises, so it is inert in the registry.
    """

    @property
    def broker_id(self) -> str:
        return _BROKER_ID

    def can_parse(self, content: str) -> bool:
        return False

    def parse(self, content: str) -> ImportResult:
        raise NotImplementedError("IBKR Flex import is not implemented yet")
