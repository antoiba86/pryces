class StockNotFound(Exception):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(f"Stock not found: {symbol}")


class MessageSendingFailed(Exception):
    def __init__(self, reason: str, retryable: bool = False) -> None:
        self.retryable = retryable
        super().__init__(f"Message sending failed: {reason}")


class PortfolioNotFound(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Portfolio not found: {name}")


class PortfolioAlreadyExists(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Portfolio already exists: {name}")


class UnrecognizedImportFormat(Exception):
    """No importer could read the uploaded file.

    `detail` carries what was actually observed — which importers declined and
    what the file looks like — because brokers change their export format
    without notice and "not a valid import" alone is undiagnosable.
    """

    def __init__(self, broker_id: str, detail: str | None = None) -> None:
        self.broker_id = broker_id
        self.detail = detail
        message = f"Content is not a valid {broker_id} import"
        super().__init__(f"{message}. {detail}" if detail else message)


class PortfolioBrokerMismatch(Exception):
    """A file import would mix brokers in a single-broker portfolio."""

    def __init__(self, existing: str, incoming: str) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            f"Portfolio only accepts {existing} transactions; cannot import {incoming}"
        )


class SampleFormatUnavailable(Exception):
    """No sample writer exists for the portfolio's broker (or it has none)."""

    def __init__(self, broker: str | None, supported: list[str]) -> None:
        self.broker = broker
        self.supported = supported
        if broker is None:
            message = (
                "Portfolio has no broker transactions, so there is no broker format to "
                "produce a sample in. Use the portfolio export instead."
            )
        else:
            message = f"No sample format for {broker}. Supported: {', '.join(supported) or 'none'}"
        super().__init__(message)


class SymbolMappingNotFound(Exception):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"Symbol mapping not found: {key}")


class TransactionNotFound(Exception):
    def __init__(self, transaction_id: str) -> None:
        self.transaction_id = transaction_id
        super().__init__(f"Transaction not found: {transaction_id}")


class InvalidExportDocument(Exception):
    """The content is not a usable pryces export (wrong envelope or version)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Invalid export document: {reason}")
