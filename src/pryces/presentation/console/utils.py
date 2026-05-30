from __future__ import annotations

import subprocess
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pryces.application.dtos import StockDTO
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.domain.stocks import Currency
from pryces.infrastructure.configs import MonitorStocksConfig, SymbolConfig

_MONITOR_MODULE = "pryces.presentation.scripts.monitor_stocks"


def get_running_monitors() -> list[tuple[str, str]]:
    result = subprocess.run(["ps", "-eo", "pid=,cmd="], capture_output=True, text=True)
    lines = result.stdout.splitlines()

    processes = []
    for line in lines:
        if _MONITOR_MODULE not in line or "/bin/sh" in line:
            continue
        pid, cmd = line.strip().split(None, 1)
        try:
            cmd_parts = cmd.split()
            module_index = cmd_parts.index("-m") + 2
            config_path = cmd_parts[module_index] if module_index < len(cmd_parts) else "unknown"
        except ValueError:
            config_path = "unknown"
        processes.append((pid, config_path))

    return processes


def format_running_monitors(processes: list[tuple[str, str]]) -> str:
    header = f"Found {len(processes)} monitor process(es):"
    entries = [
        f"  {i + 1}. PID {pid} — config: {config_path}"
        for i, (pid, config_path) in enumerate(processes)
    ]
    return "\n".join([header] + entries)


def create_monitor_selection_validator(process_count: int) -> Callable[[str], str | None]:
    def validator(value: str) -> str | None:
        try:
            if 0 <= int(value) <= process_count:
                return None
        except (ValueError, TypeError):
            pass
        return f"Must be a number between 0 and {process_count}."

    return validator


def validate_symbol(value: str) -> str | None:
    if value and value.strip() and len(value.strip()) <= 10:
        return None
    return "Symbol must be 1–10 characters."


def validate_symbols(value: str) -> str | None:
    if not value or not value.strip():
        return "Each symbol must be 1–10 characters, separated by spaces."

    symbols = value.split()
    if all(symbol and len(symbol) <= 10 for symbol in symbols):
        return None
    return "Each symbol must be 1–10 characters, separated by spaces."


def validate_positive_integer(value: str) -> str | None:
    try:
        if int(value) > 0:
            return None
    except (ValueError, TypeError):
        pass
    return "Must be a positive integer."


def validate_non_negative_integer(value: str) -> str | None:
    if not value or not value.strip():
        return None  # empty string → caller defaults to 0
    try:
        if int(value.strip()) >= 0:
            return None
    except (ValueError, TypeError):
        pass
    return "Must be a non-negative integer."


def validate_file_path(value: str) -> str | None:
    if value and value.strip() and Path(value.strip()).is_file():
        return None
    return "File not found or not a file."


def format_config_list(paths: list[Path]) -> str:
    header = f"Found {len(paths)} config(s):"
    entries = [f"  {i + 1}. {p.name}" for i, p in enumerate(paths)]
    return "\n".join([header] + entries) + "\n"


def format_config_details(config: MonitorStocksConfig, name: str, number: int) -> str:
    parts = [f"{number}. Config: {name}", f"  Interval: {config.interval}s", "  Symbols:"]
    for sc in config.symbols:
        if sc.prices:
            prices_str = ", ".join(str(p) for p in sc.prices)
            parts.append(f"    {sc.symbol}: {prices_str}")
        else:
            parts.append(f"    {sc.symbol}")
    return "\n".join(parts)


def create_config_selection_validator(count: int) -> Callable[[str], str | None]:
    def validator(value: str) -> str | None:
        try:
            n = int(value)
            if 1 <= n <= count:
                return None
        except (ValueError, TypeError):
            pass
        return f"Must be a number between 1 and {count}."

    return validator


def create_portfolio_selection_validator(count: int) -> Callable[[str], str | None]:
    return create_config_selection_validator(count)


def validate_currency(value: str) -> str | None:
    if value and value.strip().upper() in Currency.__members__:
        return None
    supported = ", ".join(currency.value for currency in Currency)
    return f"Unsupported currency. Choose one of: {supported}."


def format_portfolio_list(summaries: list[PortfolioSummary]) -> str:
    header = f"Found {len(summaries)} portfolio(s):"
    entries = [
        f"  {i + 1}. {s.name} ({s.base_currency}, {s.transaction_count} txns)"
        for i, s in enumerate(summaries)
    ]
    return "\n".join([header] + entries) + "\n"


def validate_symbols_with_targets(value: str) -> str | None:
    if not value or not value.strip():
        return "Enter at least one symbol."

    tokens = value.strip().split()
    for token in tokens:
        if ":" in token:
            symbol, prices_str = token.split(":", 1)
            if validate_symbol(symbol.upper()) is not None:
                return f"Invalid symbol '{symbol}'."
            for p in prices_str.split(","):
                try:
                    Decimal(p.strip())
                except InvalidOperation:
                    return f"Invalid price '{p}' for symbol '{symbol}'."
        else:
            if validate_symbol(token.upper()) is not None:
                return f"Invalid symbol '{token}'."

    return None


def parse_symbols_with_targets(value: str) -> list[SymbolConfig]:
    result = []
    for token in value.strip().split():
        if ":" in token:
            symbol, prices_str = token.split(":", 1)
            prices = [Decimal(p.strip()) for p in prices_str.split(",") if p.strip()]
        else:
            symbol = token
            prices = []
        result.append(SymbolConfig(symbol=symbol.upper(), prices=prices))
    return result


def parse_symbols_input(value: str) -> list[str]:
    return [s.upper() for s in value.split() if s]


FIELD_LABELS = [
    ("market_state", "Market State"),
    ("kind", "Type"),
    ("cap_size", "Cap Size"),
    ("current_price", "Current Price"),
    ("previous_close_price", "Previous Close"),
    ("open_price", "Open"),
    ("day_high", "Day High"),
    ("day_low", "Day Low"),
    ("fifty_day_average", "50-Day Average"),
    ("two_hundred_day_average", "200-Day Average"),
    ("fifty_two_week_high", "52-Week High"),
    ("fifty_two_week_low", "52-Week Low"),
    ("market_cap", "Market Cap"),
    ("price_delay_in_minutes", "Price delay (min)"),
]

LABEL_WIDTH = max(len(label) for _, label in FIELD_LABELS)
SEPARATOR = "-" * 60
DOUBLE_SEPARATOR = "=" * 60


def _format_european_number(value: Decimal) -> str:
    integer_part = int(value)
    decimal_part = value % 1

    formatted_integer = f"{integer_part:_}".replace("_", ".")

    if decimal_part:
        decimal_str = str(decimal_part)[2:]
        return f"{formatted_integer},{decimal_str}"
    return formatted_integer


def format_stock(dto: StockDTO) -> str:
    parts: list[str] = []

    header = dto.symbol
    if dto.name:
        header += f" - {dto.name}"
    if dto.currency:
        header += f" ({dto.currency})"
    parts.append(header)

    for attr, label in FIELD_LABELS:
        value = getattr(dto, attr)
        if value is not None:
            display_value = _format_european_number(value) if isinstance(value, Decimal) else value
            parts.append(f"  {label + ':':<{LABEL_WIDTH + 1}}  {display_value}")

    return "\n".join(parts)


def format_stock_list(dtos: list[StockDTO], requested_count: int) -> str:
    parts: list[str] = []

    for i, dto in enumerate(dtos):
        parts.append(format_stock(dto))
        if i < len(dtos) - 1:
            parts.append("")
            parts.append(SEPARATOR)
            parts.append("")

    successful_count = len(dtos)
    failed_count = requested_count - successful_count

    if parts:
        parts.append("")
        parts.append(DOUBLE_SEPARATOR)

    summary = f"Summary: {requested_count} requested, {successful_count} successful, {failed_count} failed"
    parts.append(summary)

    return "\n".join(parts)
