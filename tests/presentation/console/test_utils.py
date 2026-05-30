from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from pryces.presentation.console.utils import (
    create_config_selection_validator,
    create_monitor_selection_validator,
    create_portfolio_selection_validator,
    format_config_details,
    format_config_list,
    format_portfolio_list,
    format_running_monitors,
    format_stock,
    format_stock_list,
    get_running_monitors,
    parse_symbols_input,
    parse_symbols_with_targets,
    validate_currency,
    validate_file_path,
    validate_positive_integer,
    validate_symbol,
    validate_symbols,
    validate_symbols_with_targets,
)
from pryces.domain.portfolio.portfolio import PortfolioSummary
from pryces.infrastructure.configs import MonitorStocksConfig, SymbolConfig
from pryces.domain.stocks import Currency
from tests.fixtures.factories import create_stock_dto


class TestGetRunningMonitors:

    @patch("pryces.presentation.console.utils.subprocess.run")
    def test_returns_empty_list_when_no_monitor_processes(self, mock_run):
        mock_run.return_value = Mock(stdout="    1 /sbin/init\n")

        result = get_running_monitors()

        assert result == []

    @patch("pryces.presentation.console.utils.subprocess.run")
    def test_returns_single_process(self, mock_run):
        mock_run.return_value = Mock(
            stdout=(
                "12345 /usr/bin/python -m"
                " pryces.presentation.scripts.monitor_stocks /path/to/config.json\n"
            )
        )

        result = get_running_monitors()

        assert result == [("12345", "/path/to/config.json")]

    @patch("pryces.presentation.console.utils.subprocess.run")
    def test_returns_multiple_processes(self, mock_run):
        mock_run.return_value = Mock(
            stdout=(
                "11111 /usr/bin/python -m"
                " pryces.presentation.scripts.monitor_stocks /config/a.json\n"
                "22222 /usr/bin/python -m"
                " pryces.presentation.scripts.monitor_stocks /config/b.json\n"
            )
        )

        result = get_running_monitors()

        assert result == [("11111", "/config/a.json"), ("22222", "/config/b.json")]

    @patch("pryces.presentation.console.utils.subprocess.run")
    def test_shows_unknown_config_when_no_args_after_module(self, mock_run):
        mock_run.return_value = Mock(
            stdout=("12345 /usr/bin/python -m" " pryces.presentation.scripts.monitor_stocks\n")
        )

        result = get_running_monitors()

        assert result == [("12345", "unknown")]

    @patch("pryces.presentation.console.utils.subprocess.run")
    def test_calls_ps(self, mock_run):
        mock_run.return_value = Mock(stdout="")

        get_running_monitors()

        mock_run.assert_called_once_with(["ps", "-eo", "pid=,cmd="], capture_output=True, text=True)


class TestFormatRunningMonitors:

    def test_formats_single_process(self):
        processes = [("12345", "/path/to/config.json")]

        result = format_running_monitors(processes)

        assert result == (
            "Found 1 monitor process(es):\n" "  1. PID 12345 — config: /path/to/config.json"
        )

    def test_formats_multiple_processes(self):
        processes = [("11111", "/config/a.json"), ("22222", "/config/b.json")]

        result = format_running_monitors(processes)

        assert result == (
            "Found 2 monitor process(es):\n"
            "  1. PID 11111 — config: /config/a.json\n"
            "  2. PID 22222 — config: /config/b.json"
        )


class TestCreateMonitorSelectionValidator:

    def test_accepts_zero(self):
        validator = create_monitor_selection_validator(3)
        assert validator("0") is None

    def test_accepts_valid_range(self):
        validator = create_monitor_selection_validator(3)
        assert validator("1") is None
        assert validator("2") is None
        assert validator("3") is None

    def test_rejects_out_of_range(self):
        validator = create_monitor_selection_validator(2)
        assert validator("3") is not None
        assert validator("10") is not None

    def test_rejects_negative(self):
        validator = create_monitor_selection_validator(3)
        assert validator("-1") is not None

    def test_rejects_non_numeric(self):
        validator = create_monitor_selection_validator(3)
        assert validator("abc") is not None
        assert validator("") is not None

    def test_error_message_includes_upper_bound(self):
        validator = create_monitor_selection_validator(5)
        assert "5" in validator("99")


class TestValidateSymbol:

    def test_accepts_valid_symbols(self):
        assert validate_symbol("AAPL") is None
        assert validate_symbol("GOOGL") is None
        assert validate_symbol("MSFT") is None
        assert validate_symbol("BRK.B") is None
        assert validate_symbol("TSM") is None

    def test_rejects_invalid_symbols(self):
        assert validate_symbol("") is not None
        assert validate_symbol("   ") is not None
        assert validate_symbol("TOOLONGSYMBOL") is not None

    def test_error_message_describes_constraint(self):
        error = validate_symbol("TOOLONGSYMBOL")
        assert "1" in error and "10" in error


class TestValidateSymbols:

    def test_accepts_valid_single_symbol(self):
        assert validate_symbols("AAPL") is None

    def test_accepts_valid_space_separated_symbols(self):
        assert validate_symbols("AAPL GOOGL MSFT") is None

    def test_rejects_empty_string(self):
        assert validate_symbols("") is not None
        assert validate_symbols("   ") is not None

    def test_rejects_symbols_too_long(self):
        assert validate_symbols("TOOLONGSYMBOL") is not None
        assert validate_symbols("AAPL TOOLONGSYMBOL") is not None


class TestValidatePositiveInteger:

    def test_accepts_positive_integers(self):
        assert validate_positive_integer("1") is None
        assert validate_positive_integer("10") is None
        assert validate_positive_integer("300") is None

    def test_rejects_zero(self):
        assert validate_positive_integer("0") is not None

    def test_rejects_negative_numbers(self):
        assert validate_positive_integer("-1") is not None
        assert validate_positive_integer("-100") is not None

    def test_rejects_non_numeric(self):
        assert validate_positive_integer("abc") is not None
        assert validate_positive_integer("") is not None
        assert validate_positive_integer("1.5") is not None

    def test_rejects_none(self):
        assert validate_positive_integer(None) is not None


class TestValidateFilePath:

    def test_accepts_existing_file(self, tmp_path):
        file = tmp_path / "config.json"
        file.write_text("{}")

        assert validate_file_path(str(file)) is None

    def test_accepts_existing_file_with_whitespace(self, tmp_path):
        file = tmp_path / "config.json"
        file.write_text("{}")

        assert validate_file_path(f"  {file}  ") is None

    def test_rejects_nonexistent_path(self):
        assert validate_file_path("/nonexistent/path/to/file.json") is not None

    def test_rejects_directory(self, tmp_path):
        assert validate_file_path(str(tmp_path)) is not None

    def test_rejects_empty_string(self):
        assert validate_file_path("") is not None

    def test_rejects_whitespace_only(self):
        assert validate_file_path("   ") is not None

    def test_error_message_is_descriptive(self):
        error = validate_file_path("/nonexistent/file.json")
        assert isinstance(error, str) and len(error) > 0


class TestParseSymbolsInput:

    def test_parses_single_symbol(self):
        result = parse_symbols_input("AAPL")
        assert result == ["AAPL"]

    def test_parses_space_separated_symbols(self):
        result = parse_symbols_input("AAPL GOOGL MSFT")
        assert result == ["AAPL", "GOOGL", "MSFT"]

    def test_converts_to_uppercase(self):
        result = parse_symbols_input("aapl googl msft")
        assert result == ["AAPL", "GOOGL", "MSFT"]

    def test_handles_mixed_case(self):
        result = parse_symbols_input("aapl GooGl MsFt")
        assert result == ["AAPL", "GOOGL", "MSFT"]

    def test_handles_extra_whitespace(self):
        result = parse_symbols_input("  AAPL   GOOGL  ")
        assert result == ["AAPL", "GOOGL"]


class TestFormatStock:

    def test_formats_stock_with_all_fields(self):
        dto = create_stock_dto(
            "AAPL",
            Decimal("150.25"),
            name="Apple Inc.",
            currency=Currency.USD,
            previous_close_price=Decimal("148.50"),
            open_price=Decimal("149.00"),
            day_high=Decimal("151.00"),
            day_low=Decimal("148.00"),
            fifty_day_average=Decimal("145.50"),
            two_hundred_day_average=Decimal("140.00"),
            fifty_two_week_high=Decimal("180.00"),
            fifty_two_week_low=Decimal("120.00"),
        )

        result = format_stock(dto)

        assert "AAPL - Apple Inc. (USD)" in result
        assert "Current Price:" in result
        assert "150,25" in result
        assert "Previous Close:" in result
        assert "148,50" in result
        assert "Open:" in result
        assert "149" in result
        assert "Day High:" in result
        assert "151" in result
        assert "Day Low:" in result
        assert "148" in result
        assert "50-Day Average:" in result
        assert "145,50" in result
        assert "200-Day Average:" in result
        assert "140" in result
        assert "52-Week High:" in result
        assert "180" in result
        assert "52-Week Low:" in result
        assert "120" in result

    def test_formats_stock_with_minimal_fields(self):
        dto = create_stock_dto(
            "AAPL",
            Decimal("150.25"),
            name=None,
            currency=None,
            previous_close_price=None,
            open_price=None,
            day_high=None,
            day_low=None,
            fifty_day_average=None,
            two_hundred_day_average=None,
            fifty_two_week_high=None,
            fifty_two_week_low=None,
        )

        result = format_stock(dto)

        assert result.startswith("AAPL\n")
        assert "Current Price:" in result
        assert "150,25" in result
        assert "Previous Close:" not in result
        assert "Open:" not in result

    def test_omits_none_fields(self):
        dto = create_stock_dto(
            "AAPL",
            Decimal("150.25"),
            name="Apple Inc.",
            previous_close_price=Decimal("148.50"),
            open_price=None,
            day_high=None,
            day_low=None,
            fifty_day_average=None,
            two_hundred_day_average=None,
            fifty_two_week_high=None,
            fifty_two_week_low=None,
        )

        result = format_stock(dto)

        assert "AAPL - Apple Inc. (USD)" in result
        assert "Current Price:" in result
        assert "Previous Close:" in result
        assert "Open:" not in result
        assert "Day High:" not in result

    def test_header_without_name(self):
        dto = create_stock_dto("AAPL", Decimal("150.25"), name=None)

        result = format_stock(dto)

        lines = result.split("\n")
        assert lines[0] == "AAPL (USD)"

    def test_header_without_currency(self):
        dto = create_stock_dto("AAPL", Decimal("150.25"), name="Apple Inc.", currency=None)

        result = format_stock(dto)

        lines = result.split("\n")
        assert lines[0] == "AAPL - Apple Inc."

    def test_does_not_include_notifications(self):
        dto = create_stock_dto("AAPL", Decimal("150.25"))

        result = format_stock(dto)

        assert "notification" not in result.lower()

    def test_preserves_decimal_precision(self):
        dto = create_stock_dto(
            "GOOGL",
            Decimal("2847.123456789"),
            name=None,
            currency=None,
            previous_close_price=None,
            open_price=None,
            day_high=None,
            day_low=None,
            fifty_day_average=None,
            two_hundred_day_average=None,
            fifty_two_week_high=None,
            fifty_two_week_low=None,
        )

        result = format_stock(dto)

        assert "2.847,123456789" in result


class TestFormatStockList:

    def test_formats_multiple_stocks_with_separators(self):
        dtos = [
            create_stock_dto("AAPL", Decimal("150.25"), name="Apple Inc."),
            create_stock_dto("GOOGL", Decimal("2847.50"), name="Alphabet Inc."),
        ]

        result = format_stock_list(dtos, requested_count=2)

        assert "AAPL - Apple Inc. (USD)" in result
        assert "GOOGL - Alphabet Inc. (USD)" in result
        assert "------------------------------------------------------------" in result
        assert "============================================================" in result
        assert "Summary: 2 requested, 2 successful, 0 failed" in result

    def test_formats_single_stock_with_summary(self):
        dtos = [create_stock_dto("AAPL", Decimal("150.25"), name="Apple Inc.")]

        result = format_stock_list(dtos, requested_count=1)

        assert "AAPL - Apple Inc. (USD)" in result
        assert "------------------------------------------------------------" not in result
        assert "============================================================" in result
        assert "Summary: 1 requested, 1 successful, 0 failed" in result

    def test_formats_partial_failures(self):
        dtos = [
            create_stock_dto("AAPL", Decimal("150.25"), name="Apple Inc."),
            create_stock_dto("GOOGL", Decimal("2847.50"), name="Alphabet Inc."),
        ]

        result = format_stock_list(dtos, requested_count=3)

        assert "Summary: 3 requested, 2 successful, 1 failed" in result

    def test_formats_all_failures(self):
        result = format_stock_list([], requested_count=3)

        assert "============================================================" not in result
        assert "Summary: 3 requested, 0 successful, 3 failed" in result

    def test_three_stocks_have_two_separators(self):
        dtos = [
            create_stock_dto("AAPL", Decimal("150.25")),
            create_stock_dto("GOOGL", Decimal("2847.50")),
            create_stock_dto("MSFT", Decimal("350.75")),
        ]

        result = format_stock_list(dtos, requested_count=3)

        assert result.count("------------------------------------------------------------") == 2
        assert "Summary: 3 requested, 3 successful, 0 failed" in result


class TestFormatConfigList:

    def test_formats_single_config(self, tmp_path):
        paths = [tmp_path / "portfolio.json"]
        result = format_config_list(paths)
        assert result == "Found 1 config(s):\n  1. portfolio.json\n"

    def test_formats_multiple_configs(self, tmp_path):
        paths = [tmp_path / "a.json", tmp_path / "b.json"]
        result = format_config_list(paths)
        assert "Found 2 config(s):" in result
        assert "1. a.json" in result
        assert "2. b.json" in result


class TestFormatConfigDetails:

    def test_formats_config_with_target_prices(self):
        config = MonitorStocksConfig(
            interval=60,
            symbols=[
                SymbolConfig(symbol="AAPL", prices=[Decimal("150"), Decimal("160")]),
                SymbolConfig(symbol="GOOG", prices=[]),
            ],
        )
        result = format_config_details(config, "portfolio.json", 1)
        assert "1. Config: portfolio.json" in result
        assert "60" in result
        assert "AAPL" in result
        assert "150" in result
        assert "160" in result
        assert "GOOG" in result


class TestCreateConfigSelectionValidator:

    def test_accepts_valid_range(self):
        validator = create_config_selection_validator(3)
        assert validator("1") is None
        assert validator("2") is None
        assert validator("3") is None

    def test_rejects_zero(self):
        validator = create_config_selection_validator(3)
        assert validator("0") is not None

    def test_rejects_out_of_range(self):
        validator = create_config_selection_validator(2)
        assert validator("3") is not None

    def test_rejects_non_numeric(self):
        validator = create_config_selection_validator(3)
        assert validator("abc") is not None
        assert validator("") is not None

    def test_error_message_includes_bounds(self):
        validator = create_config_selection_validator(5)
        error = validator("99")
        assert "1" in error and "5" in error


class TestValidateSymbolsWithTargets:

    def test_accepts_plain_symbols(self):
        assert validate_symbols_with_targets("AAPL MSFT GOOG") is None

    def test_accepts_symbols_with_prices(self):
        assert validate_symbols_with_targets("AAPL:150,160 MSFT:200") is None

    def test_accepts_mixed(self):
        assert validate_symbols_with_targets("AAPL MSFT:150,155.50 GOOG") is None

    def test_rejects_empty(self):
        assert validate_symbols_with_targets("") is not None
        assert validate_symbols_with_targets("   ") is not None

    def test_rejects_invalid_symbol(self):
        assert validate_symbols_with_targets("TOOLONGSYMBOL") is not None

    def test_rejects_invalid_price(self):
        assert validate_symbols_with_targets("AAPL:notaprice") is not None


class TestParseSymbolsWithTargets:

    def test_parses_plain_symbols(self):
        result = parse_symbols_with_targets("AAPL MSFT")
        assert len(result) == 2
        assert result[0].symbol == "AAPL"
        assert result[0].prices == []
        assert result[1].symbol == "MSFT"

    def test_parses_symbols_with_prices(self):
        result = parse_symbols_with_targets("AAPL:150,160")
        assert result[0].symbol == "AAPL"
        assert result[0].prices == [Decimal("150"), Decimal("160")]

    def test_converts_to_uppercase(self):
        result = parse_symbols_with_targets("aapl")
        assert result[0].symbol == "AAPL"

    def test_parses_mixed_input(self):
        result = parse_symbols_with_targets("AAPL MSFT:200,210 GOOG")
        assert result[0].symbol == "AAPL"
        assert result[0].prices == []
        assert result[1].symbol == "MSFT"
        assert result[1].prices == [Decimal("200"), Decimal("210")]
        assert result[2].symbol == "GOOG"


class TestValidateCurrency:

    def test_accepts_supported_currency_case_insensitive(self):
        assert validate_currency("eur") is None

    def test_rejects_unknown_currency(self):
        assert validate_currency("XYZ") is not None

    def test_rejects_blank(self):
        assert validate_currency("") is not None


class TestCreatePortfolioSelectionValidator:

    def test_accepts_in_range(self):
        validator = create_portfolio_selection_validator(3)
        assert validator("2") is None

    def test_rejects_out_of_range(self):
        validator = create_portfolio_selection_validator(3)
        assert validator("4") is not None

    def test_rejects_non_numeric(self):
        validator = create_portfolio_selection_validator(3)
        assert validator("x") is not None


class TestFormatPortfolioList:

    def test_includes_name_currency_and_count(self):
        summaries = [PortfolioSummary(name="main", base_currency="EUR", transaction_count=4)]

        output = format_portfolio_list(summaries)

        assert "main" in output
        assert "EUR" in output
        assert "4" in output
