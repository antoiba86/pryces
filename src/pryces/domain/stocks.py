from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from pryces.domain.notifications import (
    Notification,
    NotificationFormatter,
    NotificationType,
    StockContext,
)
from pryces.domain.utils import calculate_percentage_change

if TYPE_CHECKING:
    from pryces.domain.target_prices import TargetPrice


@dataclass(frozen=True, slots=True)
class GenerateNotificationsResult:
    messages: list[str]
    fulfilled_targets: list[Decimal]


@dataclass(frozen=True, slots=True)
class StockSnapshot:
    current_price: Decimal
    previous_close_price: Decimal | None
    open_price: Decimal | None
    day_high: Decimal | None
    day_low: Decimal | None
    fifty_day_average: Decimal | None
    two_hundred_day_average: Decimal | None
    fifty_two_week_high: Decimal | None
    fifty_two_week_low: Decimal | None
    market_state: "MarketState | None"
    price_delay_in_minutes: int | None


class MarketState(str, Enum):
    OPEN = "OPEN"
    PRE = "PRE"
    POST = "POST"
    CLOSED = "CLOSED"


class InstrumentType(str, Enum):
    STOCK = "STOCK"
    ETF = "ETF"
    CRYPTO = "CRYPTO"
    INDEX = "INDEX"
    FX = "FX"


class Currency(str, Enum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"
    JPY = "JPY"
    KRW = "KRW"
    HKD = "HKD"
    CAD = "CAD"
    AUD = "AUD"


class CapSize(str, Enum):
    LARGE = "LARGE"
    MID = "MID"
    SMALL = "SMALL"


_LARGE_CAP_THRESHOLD = Decimal("10_000_000_000")
_MID_CAP_THRESHOLD = Decimal("2_000_000_000")


_INCREASE_LEVELS = (
    NotificationType.LEVEL_1_INCREASE,
    NotificationType.LEVEL_2_INCREASE,
    NotificationType.LEVEL_3_INCREASE,
    NotificationType.LEVEL_4_INCREASE,
    NotificationType.LEVEL_5_INCREASE,
)
_DECREASE_LEVELS = (
    NotificationType.LEVEL_1_DECREASE,
    NotificationType.LEVEL_2_DECREASE,
    NotificationType.LEVEL_3_DECREASE,
    NotificationType.LEVEL_4_DECREASE,
    NotificationType.LEVEL_5_DECREASE,
)

_ThresholdTuple = tuple[tuple[Decimal, NotificationType], ...]


def _build_thresholds(start: Decimal, step: Decimal) -> tuple[_ThresholdTuple, _ThresholdTuple]:
    last = len(_INCREASE_LEVELS) - 1
    inc = tuple((start + step * (last - i), level) for i, level in enumerate(_INCREASE_LEVELS))
    dec = tuple((-(start + step * (last - i)), level) for i, level in enumerate(_DECREASE_LEVELS))
    return inc, dec


_LEVEL_1_INCREASE_THRESHOLDS, _LEVEL_1_DECREASE_THRESHOLDS = _build_thresholds(
    Decimal("1"), Decimal("0.875")
)
_LEVEL_2_INCREASE_THRESHOLDS, _LEVEL_2_DECREASE_THRESHOLDS = _build_thresholds(
    Decimal("2"), Decimal("1.75")
)
_LEVEL_3_INCREASE_THRESHOLDS, _LEVEL_3_DECREASE_THRESHOLDS = _build_thresholds(
    Decimal("4"), Decimal("3.5")
)


class Stock:
    __slots__ = (
        "_symbol",
        "_current_price",
        "_name",
        "_currency",
        "_previous_close_price",
        "_open_price",
        "_day_high",
        "_day_low",
        "_fifty_day_average",
        "_two_hundred_day_average",
        "_fifty_two_week_high",
        "_fifty_two_week_low",
        "_market_cap",
        "_market_state",
        "_price_delay_in_minutes",
        "_kind",
        "_cap_size",
        "_snapshot",
        "_transition_time",
        "_notifications",
        "_pending_notifications",
        "_targets",
        "_fulfilled_targets",
    )

    _INCREASE_LEVEL_TYPES = frozenset(_INCREASE_LEVELS)
    _DECREASE_LEVEL_TYPES = frozenset(_DECREASE_LEVELS)
    _CLOSE_TO_SMA_THRESHOLD = Decimal("2.5")

    _INSTRUMENT_THRESHOLDS: dict[InstrumentType | None, tuple[_ThresholdTuple, _ThresholdTuple]] = {
        InstrumentType.STOCK: (_LEVEL_3_INCREASE_THRESHOLDS, _LEVEL_3_DECREASE_THRESHOLDS),
        InstrumentType.CRYPTO: (_LEVEL_2_INCREASE_THRESHOLDS, _LEVEL_2_DECREASE_THRESHOLDS),
        InstrumentType.ETF: (_LEVEL_2_INCREASE_THRESHOLDS, _LEVEL_2_DECREASE_THRESHOLDS),
        InstrumentType.INDEX: (_LEVEL_1_INCREASE_THRESHOLDS, _LEVEL_1_DECREASE_THRESHOLDS),
        None: (_LEVEL_2_INCREASE_THRESHOLDS, _LEVEL_2_DECREASE_THRESHOLDS),
    }

    _CROSS_TYPE_SUPPRESSIONS: ClassVar[dict[NotificationType, NotificationType]] = {
        NotificationType.CLOSE_TO_SMA50: NotificationType.SMA50_CROSSED,
        NotificationType.CLOSE_TO_SMA200: NotificationType.SMA200_CROSSED,
    }

    def __init__(
        self,
        *,
        symbol: str,
        current_price: Decimal,
        name: str | None = None,
        currency: Currency | None = None,
        previous_close_price: Decimal | None = None,
        open_price: Decimal | None = None,
        day_high: Decimal | None = None,
        day_low: Decimal | None = None,
        fifty_day_average: Decimal | None = None,
        two_hundred_day_average: Decimal | None = None,
        fifty_two_week_high: Decimal | None = None,
        fifty_two_week_low: Decimal | None = None,
        market_cap: Decimal | None = None,
        market_state: MarketState | None = None,
        price_delay_in_minutes: int | None = None,
        kind: InstrumentType | None = None,
    ):
        self._symbol = symbol
        self._current_price = current_price
        self._name = name
        self._currency = currency
        self._previous_close_price = previous_close_price
        self._open_price = open_price
        self._day_high = day_high
        self._day_low = day_low
        self._fifty_day_average = fifty_day_average
        self._two_hundred_day_average = two_hundred_day_average
        self._fifty_two_week_high = fifty_two_week_high
        self._fifty_two_week_low = fifty_two_week_low
        self._market_cap = market_cap
        self._market_state = market_state
        self._price_delay_in_minutes = price_delay_in_minutes
        self._kind = kind
        self._cap_size: CapSize | None = self._compute_cap_size()
        self._snapshot: StockSnapshot | None = None
        self._transition_time: datetime | None = None
        self._notifications: list[Notification] = []
        self._pending_notifications: list[Notification] = []
        self._targets: list[TargetPrice] = []
        self._fulfilled_targets: list[TargetPrice] = []

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def current_price(self) -> Decimal:
        return self._current_price

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def currency(self) -> Currency | None:
        return self._currency

    @property
    def previous_close_price(self) -> Decimal | None:
        return self._previous_close_price

    @property
    def open_price(self) -> Decimal | None:
        return self._open_price

    @property
    def day_high(self) -> Decimal | None:
        return self._day_high

    @property
    def day_low(self) -> Decimal | None:
        return self._day_low

    @property
    def fifty_day_average(self) -> Decimal | None:
        return self._fifty_day_average

    @property
    def two_hundred_day_average(self) -> Decimal | None:
        return self._two_hundred_day_average

    @property
    def fifty_two_week_high(self) -> Decimal | None:
        return self._fifty_two_week_high

    @property
    def fifty_two_week_low(self) -> Decimal | None:
        return self._fifty_two_week_low

    @property
    def market_cap(self) -> Decimal | None:
        return self._market_cap

    @property
    def market_state(self) -> MarketState | None:
        return self._market_state

    @property
    def price_delay_in_minutes(self) -> int | None:
        return self._price_delay_in_minutes

    @property
    def kind(self) -> "InstrumentType | None":
        return self._kind

    @property
    def cap_size(self) -> "CapSize | None":
        return self._cap_size

    @property
    def snapshot(self) -> StockSnapshot | None:
        return self._snapshot

    def _drain_fulfilled_targets(self) -> list[Decimal]:
        fulfilled = [t.target for t in self._fulfilled_targets]
        self._fulfilled_targets = []
        return fulfilled

    def _drain_notifications(self, formatter: NotificationFormatter) -> list[str]:
        context = StockContext(self._symbol, self._current_price, self._previous_close_price)
        result = formatter.format(list(self._pending_notifications), context)
        self._notifications.extend(self._pending_notifications)
        self._pending_notifications = []
        return result

    def sync_targets(self, target_values: list[Decimal]) -> None:
        from pryces.domain.target_prices import TargetPrice

        existing_by_value = {t.target: t for t in self._targets}

        synced: list[TargetPrice] = []
        for value in target_values:
            existing = existing_by_value.get(value)
            if existing is not None:
                synced.append(existing)
            else:
                target = TargetPrice(target=value, entry_price=self.current_price)
                synced.append(target)

        self._targets = synced

    def update(self, source: "Stock") -> None:
        self._snapshot = self._capture_snapshot()
        self._current_price = source._current_price
        self._name = source._name
        self._currency = source._currency
        self._previous_close_price = source._previous_close_price
        self._open_price = source._open_price
        self._day_high = source._day_high
        self._day_low = source._day_low
        self._fifty_day_average = source._fifty_day_average
        self._two_hundred_day_average = source._two_hundred_day_average
        self._fifty_two_week_high = source._fifty_two_week_high
        self._fifty_two_week_low = source._fifty_two_week_low
        self._market_cap = source._market_cap
        self._market_state = source._market_state
        self._price_delay_in_minutes = source._price_delay_in_minutes
        self._kind = source._kind
        self._cap_size = self._compute_cap_size()

    def is_market_state_transition(self) -> bool:
        return (
            self._snapshot is not None
            and self._snapshot.market_state != self._market_state
            and self._market_state in (MarketState.OPEN, MarketState.POST)
        )

    def generate_notifications(
        self, now: datetime, formatter: NotificationFormatter
    ) -> GenerateNotificationsResult:
        if not self._is_in_delay_window(now):
            if self._is_market_state_open():
                self._generate_market_open_notifications()
            elif self._is_market_state_post():
                self._generate_market_closed_notifications()
        messages = self._drain_notifications(formatter)
        fulfilled_targets = self._drain_fulfilled_targets()
        return GenerateNotificationsResult(messages=messages, fulfilled_targets=fulfilled_targets)

    def _compute_cap_size(self) -> CapSize | None:
        if (
            self._kind != InstrumentType.STOCK
            or self._currency not in (Currency.USD, Currency.EUR)
            or self._market_cap is None
        ):
            return None
        if self._market_cap >= _LARGE_CAP_THRESHOLD:
            return CapSize.LARGE
        if self._market_cap >= _MID_CAP_THRESHOLD:
            return CapSize.MID
        return CapSize.SMALL

    def _capture_snapshot(self) -> StockSnapshot:
        return StockSnapshot(
            current_price=self._current_price,
            previous_close_price=self._previous_close_price,
            open_price=self._open_price,
            day_high=self._day_high,
            day_low=self._day_low,
            fifty_day_average=self._fifty_day_average,
            two_hundred_day_average=self._two_hundred_day_average,
            fifty_two_week_high=self._fifty_two_week_high,
            fifty_two_week_low=self._fifty_two_week_low,
            market_state=self._market_state,
            price_delay_in_minutes=self._price_delay_in_minutes,
        )

    def _is_close_to_sma(self, sma: Decimal | None) -> bool:
        if sma is None or self.previous_close_price is None:
            return False

        change_percentage = calculate_percentage_change(sma, self.current_price)

        return (
            self.previous_close_price < sma
            and self.current_price < sma
            and change_percentage <= self._CLOSE_TO_SMA_THRESHOLD
        ) or (
            self.previous_close_price > sma
            and self.current_price > sma
            and change_percentage >= -self._CLOSE_TO_SMA_THRESHOLD
        )

    def _has_crossed_sma(self, sma: Decimal | None) -> bool:
        if self.previous_close_price is None or sma is None:
            return False

        crossed_above = self.previous_close_price < sma and self.current_price >= sma
        crossed_below = self.previous_close_price > sma and self.current_price <= sma

        return crossed_above or crossed_below

    def _change_percentage_from_previous_close(self) -> Decimal | None:
        if self.previous_close_price is None:
            return None

        return calculate_percentage_change(self.current_price, self.previous_close_price)

    def _is_market_state_open(self) -> bool:
        return self._market_state == MarketState.OPEN

    def _is_market_state_post(self) -> bool:
        return self._market_state == MarketState.POST

    def _is_crypto(self) -> bool:
        return self._kind == InstrumentType.CRYPTO

    def _is_in_delay_window(self, now: datetime) -> bool:
        if not self._price_delay_in_minutes:
            return False
        if self.is_market_state_transition():
            self._transition_time = now
            return True
        if self._transition_time is None:
            return False
        elapsed_minutes = (now - self._transition_time).total_seconds() / 60
        if elapsed_minutes < self._price_delay_in_minutes:
            return True
        self._transition_time = None
        return False

    def _get_percentage_thresholds(self) -> tuple[_ThresholdTuple, _ThresholdTuple]:
        if self._kind == InstrumentType.STOCK and self.cap_size == CapSize.LARGE:
            return _LEVEL_2_INCREASE_THRESHOLDS, _LEVEL_2_DECREASE_THRESHOLDS
        return self._INSTRUMENT_THRESHOLDS[self._kind]

    def _resolve_percentage_level(self, change_percentage: Decimal) -> NotificationType | None:
        inc, dec = self._get_percentage_thresholds()
        if change_percentage > 0:
            for threshold, notification_type in inc:
                if change_percentage >= threshold:
                    return notification_type
        elif change_percentage < 0:
            for threshold, notification_type in dec:
                if change_percentage <= threshold:
                    return notification_type
        return None

    def _compute_market_open_percentage_level(self) -> NotificationType | None:
        if self._open_price is None or self._previous_close_price is None:
            return None
        change = calculate_percentage_change(self._open_price, self._previous_close_price)
        return self._resolve_percentage_level(change)

    def _generate_percentage_change_notification(
        self, change_percentage: Decimal
    ) -> Notification | None:
        notification_type = self._resolve_percentage_level(change_percentage)
        if notification_type is None:
            return None
        return Notification.create_percentage_change(
            notification_type, self.symbol, self.current_price, change_percentage
        )

    def _generate_new_52_week_high_notification(self) -> Notification | None:
        if (
            self._snapshot is not None
            and self._snapshot.fifty_two_week_high is not None
            and self.previous_close_price is not None
            and self.current_price > self._snapshot.fifty_two_week_high
        ):
            return Notification.create_new_52_week_high()
        return None

    def _generate_new_52_week_low_notification(self) -> Notification | None:
        if (
            self._snapshot is not None
            and self._snapshot.fifty_two_week_low is not None
            and self.previous_close_price is not None
            and self.current_price < self._snapshot.fifty_two_week_low
        ):
            return Notification.create_new_52_week_low()
        return None

    def _generate_regular_market_open_notification(self) -> Notification | None:
        if self._is_crypto():
            return None
        return Notification.create_regular_market_open(
            self.symbol,
            self.open_price if self.open_price is not None else self.current_price,
            self.previous_close_price,
        )

    def _generate_close_to_fifty_day_average_notification(self) -> Notification | None:
        if self._is_close_to_sma(self.fifty_day_average):
            return Notification.create_close_to_fifty_day_average(
                self.current_price, self.fifty_day_average
            )
        return None

    def _generate_fifty_day_average_crossed_notification(self) -> Notification | None:
        if self._has_crossed_sma(self.fifty_day_average):
            return Notification.create_fifty_day_average_crossed(self.fifty_day_average)
        return None

    def _generate_close_to_two_hundred_day_average_notification(self) -> Notification | None:
        if self._is_close_to_sma(self.two_hundred_day_average):
            return Notification.create_close_to_two_hundred_day_average(
                self.current_price, self.two_hundred_day_average
            )
        return None

    def _generate_two_hundred_day_average_crossed_notification(self) -> Notification | None:
        if self._has_crossed_sma(self.two_hundred_day_average):
            return Notification.create_two_hundred_day_average_crossed(self.two_hundred_day_average)
        return None

    def _generate_percentage_change_from_previous_close_notification(self) -> Notification | None:
        change_percentage = self._change_percentage_from_previous_close()
        if change_percentage is None:
            return None
        return self._generate_percentage_change_notification(change_percentage)

    def _has_any_increase_percentage_notification(self) -> bool:
        return any(n.type in self._INCREASE_LEVEL_TYPES for n in self._notifications)

    def _has_any_decrease_percentage_notification(self) -> bool:
        return any(n.type in self._DECREASE_LEVEL_TYPES for n in self._notifications)

    def _generate_session_gains_erased_notification(self) -> Notification | None:
        change_percentage = self._change_percentage_from_previous_close()
        if (
            change_percentage is not None
            and change_percentage < 0
            and self._has_any_increase_percentage_notification()
        ):
            return Notification.create_session_gains_erased()
        return None

    def _generate_session_losses_erased_notification(self) -> Notification | None:
        change_percentage = self._change_percentage_from_previous_close()
        if (
            change_percentage is not None
            and change_percentage > 0
            and self._has_any_decrease_percentage_notification()
        ):
            return Notification.create_session_losses_erased()
        return None

    def _generate_target_price_notifications(self) -> list[Notification]:
        notifications: list[Notification] = []
        remaining: list[TargetPrice] = []
        for target in self._targets:
            if target.is_reached(self):
                notifications.append(
                    Notification.create_target_price_reached(self._symbol, target.target)
                )
                self._fulfilled_targets.append(target)
            else:
                remaining.append(target)
        self._targets = remaining
        return notifications

    def _collect_market_open_candidates(self) -> list[Notification]:
        candidates = [
            n
            for n in (
                self._generate_regular_market_open_notification(),
                self._generate_percentage_change_from_previous_close_notification(),
                self._generate_fifty_day_average_crossed_notification(),
                self._generate_close_to_fifty_day_average_notification(),
                self._generate_two_hundred_day_average_crossed_notification(),
                self._generate_close_to_two_hundred_day_average_notification(),
                self._generate_new_52_week_high_notification(),
                self._generate_new_52_week_low_notification(),
                self._generate_session_gains_erased_notification(),
                self._generate_session_losses_erased_notification(),
            )
            if n is not None
        ]
        candidates.extend(self._generate_target_price_notifications())
        return candidates

    def _deduplicate(self, candidates: list[Notification]) -> list[Notification]:
        accepted: list[Notification] = []
        accepted_types: set[NotificationType] = set()
        historical_types = {n.type for n in self._notifications}
        market_open_percentage_level: NotificationType | None = None

        for candidate in candidates:
            if candidate.type == NotificationType.TARGET_PRICE_REACHED:
                accepted.append(candidate)
                continue

            if candidate.type in historical_types or candidate.type in accepted_types:
                continue

            suppressor = self._CROSS_TYPE_SUPPRESSIONS.get(candidate.type)
            if suppressor is not None and (
                suppressor in historical_types or suppressor in accepted_types
            ):
                continue

            if (
                market_open_percentage_level is not None
                and candidate.type == market_open_percentage_level
            ):
                self._notifications.append(candidate)
                historical_types.add(candidate.type)
                continue

            accepted.append(candidate)
            accepted_types.add(candidate.type)

            if candidate.type == NotificationType.REGULAR_MARKET_OPEN:
                market_open_percentage_level = self._compute_market_open_percentage_level()

            if candidate.type == NotificationType.SESSION_GAINS_ERASED:
                self._reset_increase_percentage_notifications()
                historical_types -= self._INCREASE_LEVEL_TYPES
            elif candidate.type == NotificationType.SESSION_LOSSES_ERASED:
                self._reset_decrease_percentage_notifications()
                historical_types -= self._DECREASE_LEVEL_TYPES

        return accepted

    def _generate_market_open_notifications(self) -> None:
        candidates = self._collect_market_open_candidates()
        self._pending_notifications.extend(self._deduplicate(candidates))

    def _generate_regular_market_closed_notification(self) -> Notification | None:
        if self._is_crypto():
            return None
        return Notification.create_regular_market_closed(
            self.symbol, self.current_price, self.previous_close_price
        )

    def _reset_increase_percentage_notifications(self) -> None:
        self._notifications = [
            n for n in self._notifications if n.type not in self._INCREASE_LEVEL_TYPES
        ]

    def _reset_decrease_percentage_notifications(self) -> None:
        self._notifications = [
            n for n in self._notifications if n.type not in self._DECREASE_LEVEL_TYPES
        ]

    def _generate_market_closed_notifications(self) -> None:
        notification = self._generate_regular_market_closed_notification()
        if notification is None:
            return
        self._pending_notifications.extend(self._deduplicate([notification]))
