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
    def __init__(self, broker_id: str) -> None:
        self.broker_id = broker_id
        super().__init__(f"Content is not a valid {broker_id} import")


class PortfolioBrokerMismatch(Exception):
    """A file import would mix brokers in a single-broker portfolio."""

    def __init__(self, existing: str, incoming: str) -> None:
        self.existing = existing
        self.incoming = incoming
        super().__init__(
            f"Portfolio only accepts {existing} transactions; cannot import {incoming}"
        )


class TransactionNotFound(Exception):
    def __init__(self, transaction_id: str) -> None:
        self.transaction_id = transaction_id
        super().__init__(f"Transaction not found: {transaction_id}")
