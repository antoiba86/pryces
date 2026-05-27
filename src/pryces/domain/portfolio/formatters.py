from abc import ABC, abstractmethod

from pryces.domain.portfolio.portfolio import Portfolio


class PortfolioFormatter(ABC):
    @abstractmethod
    def format(self, portfolio: Portfolio) -> list[str]:
        """Render a portfolio into one or more messages.

        Returning a list (rather than a single string) lets infrastructure
        adapters split long output across Telegram's 4096-char limit at
        natural section boundaries without the application layer caring.
        """
