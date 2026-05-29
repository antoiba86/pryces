# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pryces is a Python project built with clean architecture principles, emphasizing SOLID design, minimal dependencies, and clear separation of concerns.

## Design Principles

All code must follow **SOLID principles**, **hexagonal architecture**, and **clean code** practices:
- **Single Responsibility**: Each class/module has one reason to change
- **Open/Closed**: Extend behavior through new implementations, not modifying existing code
- **Liskov Substitution**: Implementations must be interchangeable through their port interfaces
- **Interface Segregation**: Keep port interfaces focused and minimal
- **Dependency Inversion**: Depend on abstractions (ports), not concretions (adapters)
- **Hexagonal Architecture**: Domain and application layers never depend on infrastructure or presentation; dependencies always point inward
- **Clean Code**: Meaningful names, small focused functions, no duplication, self-documenting structure

## Critical Directives

### Update Documentation After Changes
**IMPORTANT**: Whenever you make significant changes to the codebase (new features, API changes, new fields, renamed parameters, etc.), you MUST update both of the following:

**README.md** (user-facing documentation):
- Update example outputs to match current output format
- Update command examples if CLI arguments change
- Add documentation for new features
- Ensure all examples are accurate and tested

**CLAUDE.md — Architecture Overview** (developer-facing reference):
- Update file/class descriptions when responsibilities change
- Add entries for new files, classes, or exported helpers
- Remove or rename entries when things are deleted or renamed
- Keep the layer descriptions (Domain, Application, Infrastructure, Presentation) accurate

Both must stay synchronized with the actual code behavior.

**Documentation changes must be committed in the same commit as the code they describe** — never in a separate follow-up commit. A commit that changes behavior without updating its documentation is incomplete.

### Prefer Using Subagents for Context Optimization
**IMPORTANT**: Always use specialized subagents (via the Task tool) whenever possible to optimize context usage, unless explicitly instructed not to use subagents.

Use subagents for:
- **Exploration tasks**: Understanding codebase structure, finding patterns, locating functionality
- **Search operations**: Multi-step searches across files, grep operations with follow-up analysis
- **Planning**: Complex implementation plans that require code exploration
- **Research**: Investigating how features work, tracing dependencies
- **Parallel work**: Independent tasks that can run simultaneously

Only work directly (without subagents) when:
- User explicitly requests direct execution
- Task is trivial (single file read/write)
- Already in a subagent context

**Before editing any file you have not already read in this session, use the Explore agent to navigate to it** — do not guess at file paths or class locations from memory alone.

This helps maintain clean context and allows better task delegation.

### Prefer Using Plan Mode for Non-Trivial Tasks
**IMPORTANT**: Always use plan mode (EnterPlanMode) for implementation tasks unless explicitly instructed not to or the task is trivial.

Use plan mode for:
- **New features**: Adding any new functionality beyond single-line changes
- **Code modifications**: Changes affecting multiple files or existing behavior
- **Refactoring**: Restructuring code or changing architecture
- **Multi-step implementations**: Tasks requiring more than 2-3 simple steps
- **Uncertain scope**: When you need to explore before understanding full requirements

Do NOT use plan mode for:
- User explicitly requests direct implementation
- Trivial tasks (typo fixes, single-line changes, obvious bugs)
- Pure research/exploration (use Task tool with Explore agent instead)
- Tasks with very specific, detailed instructions already provided

Plan mode ensures alignment on approach before implementation, preventing wasted effort.

### Always Run and Update Tests After Code Changes
**IMPORTANT**: After making any code changes, you MUST:

1. **Run the full test suite** to verify nothing is broken: `source venv/bin/activate && pytest`
2. **Fix any failing tests** caused by your changes before considering the task done
3. **Add new tests** to cover new behavior — new commands, use cases, services, or non-trivial logic must have corresponding tests
4. **Delete obsolete tests** when removing the code they cover

**Test structure rules:**
- Mirror the `src/` layout under `tests/` — `src/pryces/domain/stocks.py` → `tests/domain/test_stocks.py`
- Use `@pytest.fixture` for shared setup; avoid repeating setup logic across test functions
- Test the public API of each unit, not its internal implementation — if a test breaks on a private rename, the test is wrong
- Prefer many small focused test functions over large tests that check multiple behaviors

Never consider an implementation task complete without a passing test suite.

### Always Use Virtual Environment for Testing
**IMPORTANT**: This project uses a Python virtual environment. You MUST activate it before running any tests or testing code manually.

**Required workflow:**
1. **Before testing**: Activate the virtual environment with `source venv/bin/activate` (or `source .venv/bin/activate` depending on the venv location)
2. **Run tests**: Execute `pytest` or test the CLI manually
3. **After testing**: Deactivate with `deactivate`

**Why this matters:**
- Running tests without the venv will fail due to missing dependencies
- Attempting to install packages globally wastes time and may cause permission errors
- Always check for the venv before running Python commands

**Never**: Try to install the Python environment from scratch or install packages globally. The virtual environment already exists and contains all required dependencies.

### Working with GitHub Issues
**IMPORTANT**: When interacting with GitHub issues, follow these rules:

**Retrieving issues**: Always use the `--json` flag to avoid a GraphQL error from the deprecated classic Projects API:
```bash
gh issue view <number> --json title,body,labels,assignees
```

**Creating issues**:
- **Labels**: Use `bug` for bug fixes, `enhancement` for everything else (features, improvements, refactors, etc.)
- **Assignee**: Always assign to `phantomarko`
- **Command**: Use `gh issue create --title "..." --body "..." --label <label> --assignee phantomarko`

## Architecture Overview

Pryces is a stock price CLI tool using **Ports & Adapters** (hexagonal) architecture. External dependencies: `yfinance`, `python-dotenv`.

### Layers

```
Presentation → Application → Domain
                   ↑
            Infrastructure (implements application ports)
```

**Domain** (`src/pryces/domain/`) — Core domain model:
- `stocks.py` — `MarketState` enum (OPEN, PRE, POST, CLOSED), `InstrumentType` enum (STOCK, ETF, CRYPTO, INDEX), `Currency` enum (EUR, USD, GBP, JPY, KRW, HKD, CAD, AUD — unknown strings from yfinance map to `None` at the infrastructure boundary), `CapSize` enum (LARGE, MID, SMALL), `GenerateNotificationsResult` frozen dataclass (messages: `list[str]`, fulfilled_targets: `list[Decimal]` — DTO returned by `Stock.generate_notifications()`), `StockSnapshot` frozen dataclass (captures mutable price/market fields), `Stock` entity (symbol, current_price + optional: name, currency: `Currency | None`, market_cap, market_state, kind, and 10 Decimal price fields; computed `cap_size: CapSize | None` — derived from `kind`, `currency`, and `market_cap` via `_compute_cap_size()` (called in `__init__` and after `update()`); classification: LARGE ≥ $10B, MID ≥ $2B, SMALL < $2B; only set when `kind == STOCK`, `currency` in `(Currency.USD, Currency.EUR)`, and `market_cap is not None`; owns `_targets: list[TargetPrice]` and `_fulfilled_targets: list[TargetPrice]` internally; `update(source)` captures current state as `StockSnapshot` then copies fields from source, preserves accumulated notifications and targets; `is_market_state_transition()` checks snapshot vs current market state; `sync_targets(target_values: list[Decimal])` creates `TargetPrice` internally, matches incoming values vs existing by `.target` — keeps existing (preserves entry price), creates new ones (calls `set_entry_price(self)`), removes targets no longer in incoming list; `generate_notifications(now: datetime, formatter: NotificationFormatter) -> GenerateNotificationsResult` three-phase architecture (generate → format → drain) with built-in delay window suppression — if the stock has a positive `price_delay_in_minutes` and is within the delay window after a market state transition, notifications are suppressed entirely (tracks `_transition_time: datetime | None` internally); (1) **generation** — each `_generate_*` method returns `Notification | None` (or `list[Notification]` for targets) based purely on business-logic preconditions, without checking existing notifications; `_collect_market_open_candidates()` calls all generators in order and collects non-None results; (2) **deduplication** — `_deduplicate(candidates)` applies all dedup rules in a single pass: skips candidates whose `NotificationType` exists in historical `_notifications` or already-accepted candidates (intra-cycle), applies cross-type suppression via `_CROSS_TYPE_SUPPRESSIONS` class constant (close-to-SMA suppressed when corresponding SMA crossing exists), applies transient market-open percentage suppression — when `REGULAR_MARKET_OPEN` is accepted, `_compute_market_open_percentage_level()` resolves the open-price percentage to a `LEVEL_*` type via `_resolve_percentage_level()`; if a subsequent percentage-change candidate matches the same level, it is skipped from display but added directly to `_notifications` history (persisted — stays deduped in future cycles until cleared by session gains/losses erased); requires real `_open_price` (not None) to activate; always accepts `TARGET_PRICE_REACHED` (never deduplicated), and triggers `_reset_increase/decrease_percentage_notifications()` when accepting `SESSION_GAINS/LOSSES_ERASED`; removes triggered targets from `_targets` and accumulates them in `_fulfilled_targets`; market open/close notifications are skipped for `InstrumentType.CRYPTO` (crypto markets run 24/7), but all other notifications (SMA, 52-week, percentage, targets) are generated normally for crypto; all notifications (including market open) generate together on the first market-open cycle with no deferral; target notifications only generated when market is OPEN; generation order within a market-open cycle matters: SMA50 crossed → close-to-SMA50 → SMA200 crossed → close-to-SMA200 → 52-week high/low → percentage change → session gains/losses erased → target prices; percentage change thresholds use a level-based system: `_build_thresholds(start, step)` module-level helper generates increase + decrease threshold tuples from start/step Decimal values (descending order); three reusable levels at module scope — Level 1 (start=1%, step=0.875%: 1.0/1.875/2.75/3.625/4.5%), Level 2 (start=2%, step=1.75%: 2.0/3.75/5.5/7.25/9.0%), Level 3 (start=4%, step=3.5%: 4.0/7.5/11.0/14.5/18.0%); `_INSTRUMENT_THRESHOLDS` class-level dict maps `InstrumentType | None` to threshold pairs: STOCK → Level 3, CRYPTO/ETF/None → Level 2, INDEX → Level 1; `_get_percentage_thresholds()` overrides STOCK to Level 2 when `cap_size == CapSize.LARGE` (large-cap stocks have smaller typical swings); mid/small/unknown cap STOCKs fall back to the dict's Level 3; each threshold maps to a level-based `NotificationType` (LEVEL_1..5); `_resolve_percentage_level(change_percentage)` resolves a percentage to its `NotificationType | None` without creating a `Notification` — used by both `_generate_percentage_change_notification` and `_compute_market_open_percentage_level`; percentage change notifications are always added to `_pending_notifications` during generation; 52-week high/low notifications use the common price-change prefix format with percentage change, require `previous_close_price` to generate; after generation phase, `generate_notifications` internally drains pending notifications via `_drain_notifications(formatter)` (delegates formatting to the injected `NotificationFormatter`, moves pending to historical `_notifications`) and fulfilled targets via `_drain_fulfilled_targets()`, returning a `GenerateNotificationsResult(messages: list[str], fulfilled_targets: list[Decimal])` — both drain methods are private, callers interact only through the returned result)
- `notifications.py` — `NotificationType` enum (CLOSE_TO_SMA50, CLOSE_TO_SMA200, SMA50_CROSSED, SMA200_CROSSED, REGULAR_MARKET_OPEN, REGULAR_MARKET_CLOSED, LEVEL_1_INCREASE, LEVEL_2_INCREASE, LEVEL_3_INCREASE, LEVEL_4_INCREASE, LEVEL_5_INCREASE, LEVEL_1_DECREASE, LEVEL_2_DECREASE, LEVEL_3_DECREASE, LEVEL_4_DECREASE, LEVEL_5_DECREASE, SESSION_GAINS_ERASED, SESSION_LOSSES_ERASED, NEW_52_WEEK_HIGH, NEW_52_WEEK_LOW, TARGET_PRICE_REACHED), `Notification` class (factory-based construction with static creators; milestone factories store only the event-specific text as `_message` (e.g., `"Crossed SMA50 at 145.00"`, `"Hit a new 52-week high"`); standalone factories (market open/close, percentage change, target reached) store the full message; `create_percentage_change(notification_type, symbol, current_price, change_percentage)` single factory for all percentage level notifications; `create_plain_header(symbol, current_price)` creates a simple `"{symbol} at {price}"` header notification used as formatter fallback when no `previous_close_price` is available); `STANDALONE_NOTIFICATION_TYPES` frozenset (REGULAR_MARKET_CLOSED, TARGET_PRICE_REACHED), `MILESTONE_NOTIFICATION_TYPES` frozenset (SMA50_CROSSED, SMA200_CROSSED, CLOSE_TO_SMA50, CLOSE_TO_SMA200, NEW_52_WEEK_HIGH, NEW_52_WEEK_LOW, SESSION_GAINS_ERASED, SESSION_LOSSES_ERASED) — module-level constants categorizing notification types for formatting; `StockContext` frozen dataclass (symbol, current_price, previous_close_price — minimal DTO for formatting context), `NotificationFormatter` ABC (`format(notifications: list[Notification], context: StockContext) -> list[str]` — domain port for converting notifications into displayable messages)
- `utils.py` — `calculate_percentage_change(current, reference)` domain utility (computes `(current - reference) / reference * 100`)
- `target_prices.py` — `TargetPrice` entity (target, entry; `set_entry_price(stock)` captures entry price; `is_reached(stock)` returns bool indicating whether target price has been reached)
- `stock_statistics.py` — `StatisticsPeriod` enum (1D, 1W, 3M, 1Y, YTD), `HistoricalClose` frozen dataclass (period, close_price), `PriceChange` class (period, close_price, current_price → computes `change` and `change_percentage` via `calculate_percentage_change()` in `__init__`; all fields exposed as read-only properties), `StockStatisticsFormatter` ABC (`format(stats: StockStatistics) -> str` — domain port for converting statistics into a displayable string), `StockStatistics` entity (symbol, current_price, historical_closes, name: `str | None`, currency: `str | None`; converts `list[HistoricalClose]` to `list[PriceChange]` on construction; `price_changes` returns immutable list; `format(formatter: StockStatisticsFormatter) -> str` delegates to the injected formatter)

**Application** (`src/pryces/application/`) — Use cases, services, and port interfaces:
- `interfaces.py` — all port ABCs: `StockProvider` (get_stocks), `StockRepository` (save_batch, get), `StockStatisticsProvider` (get_stock_statistics(symbols) → list[StockStatistics]), `MessageSender` (send_message), `Logger` (debug, info, warning, error), `LoggerFactory` (get_logger(name) → Logger)
- `dtos.py` — `StockDTO` (maps domain Stock to DTO, includes market_state, kind, cap_size, and currency: all `str | None` — `currency` is converted from `Currency` enum via `.value` in `from_stock()`), `TargetPriceDTO` (symbol + target Decimal)
- `exceptions.py` — `StockNotFound`
- `services.py` — `NotificationService` (sends stock notifications via `MessageSender`; injects `NotificationFormatter` and `clock: Callable[[], datetime]` (default `datetime.now`); `send_stock_notifications(stock) -> list[Decimal]` calls `stock.generate_notifications(now, formatter)`, sends each message from the result, and returns `result.fulfilled_targets`; delay window suppression is handled at the domain level by `Stock`), `StockSynchronizer` (fetches fresh stocks via `StockProvider`, merges with existing state from `StockRepository` via `Stock.update()`, syncs target prices via `Stock.sync_targets()`, persists via `save_batch`; `fetch_and_sync(symbols, targets) -> list[Stock]`, `persist(stocks)`)
- `use_cases/get_stocks_prices.py` — `GetStocksPrices` (batch symbols → list[StockDTO])
- `use_cases/trigger_stocks_statistics.py` — `TriggerStocksStatisticsRequest` (symbols: `list[str]`), `TriggerStocksStatistics` (injects `StockStatisticsProvider`, `StockStatisticsFormatter`, and `MessageSender`; `handle(request) -> None` — fetches stats, formats each via `StockStatistics.format(formatter)`, sends each via `MessageSender.send_message()`; owns the full fetch → format → send pipeline)
- `use_cases/send_messages.py` — `SendMessages` (sends list of messages → success/failed counts)
- `use_cases/list_portfolios.py` — `ListPortfolios` (returns `list[PortfolioSummary]` from `PortfolioRepository.list_portfolios`)
- `use_cases/create_portfolio.py` — `CreatePortfolioRequest` (`base_currency`, optional `name`, `user_id=1`), `CreatePortfolio` (delegates to `PortfolioRepository.create`; propagates `PortfolioAlreadyExists`)
- `use_cases/delete_portfolio.py` — `DeletePortfolioRequest` (`name`, `user_id=1`), `DeletePortfolio` (delegates to `PortfolioRepository.delete`; propagates `PortfolioNotFound`)
- `use_cases/rename_portfolio.py` — `RenamePortfolioRequest` (`old_name`, `new_name`, `user_id=1`), `RenamePortfolio` (delegates to `PortfolioRepository.rename`; propagates `PortfolioNotFound` / `PortfolioAlreadyExists`)
- `use_cases/trigger_stocks_notifications.py` — `TriggerStocksNotifications` + `TriggerStocksNotificationsRequest` (symbols + targets: `dict[str, list[Decimal]]`; delegates stock fetching/merging/target-sync to `StockSynchronizer.fetch_and_sync()`, triggers notifications via `NotificationService.send_stock_notifications(stock)` and collects fulfilled targets from its return value, persists via `StockSynchronizer.persist()`; `handle()` returns `list[TargetPriceDTO]` of fulfilled targets)

**Infrastructure** (`src/pryces/infrastructure/`) — Adapter implementations:
- `providers.py` — `YahooFinanceSettings` frozen dataclass (max_workers, extra_delay_in_minutes), `YahooFinanceMapper` (converts raw yfinance info dicts to domain `Stock` objects — maps MarketState from yfinance values, maps quoteType to InstrumentType (EQUITY→STOCK, ETF→ETF, CRYPTOCURRENCY→CRYPTO, INDEX→INDEX; unknown types map to None), maps currency string to `Currency` enum via `_map_currency()` (unknown/missing strings map to None), handles price fallback chain, adds `extra_delay_in_minutes` to yfinance-reported delay unconditionally; injects `logger_factory: LoggerFactory`), `YahooFinanceProvider` implements `StockProvider` via `yfinance` (delegates mapping to `YahooFinanceMapper`; `_get_stock` handles all yfinance exceptions internally — logs and returns `None` on failure; injects `logger_factory: LoggerFactory`), `YahooFinanceStatisticsMapper` (converts raw yfinance info + 400-day history DataFrame to domain `StockStatistics`; builds `HistoricalClose` list for periods 1D/1W/3M/1Y/YTD; validates symbol data completeness), `YahooFinanceStatisticsProvider` implements `StockStatisticsProvider` (parallelises per-symbol fetching via `ThreadPoolExecutor`; delegates mapping to `YahooFinanceStatisticsMapper`; logs and filters out `None` on any per-symbol exception; injects `logger_factory: LoggerFactory`)
- `senders.py` — `TelegramSettings` frozen dataclass (bot_token, group_id), `TelegramMessageSender` implements `MessageSender` via Telegram Bot API (raises `MessageSendingFailed` on all failure paths: HTTP errors with `retryable=True` for 429/5xx, network errors with `retryable=True`, `ok=false` responses with `retryable` derived from `error_code` (429/5xx → `True`, else `False`); injects `logger_factory: LoggerFactory`), `RetrySettings` frozen dataclass (max_retries, base_delay, backoff_factor), `RetryMessageSender` decorator implementing `MessageSender` (wraps any `MessageSender`; retries on `MessageSendingFailed` with `retryable=True` using exponential backoff; raises immediately on non-retryable failures or when max_retries exceeded; injects `logger_factory: LoggerFactory`), `FireAndForgetMessageSender` decorator implementing `MessageSender` (wraps any `MessageSender`; submits calls to a single-worker `ThreadPoolExecutor` and returns `True` immediately; logs exceptions from the inner sender; `shutdown()` waits for pending messages — used in monitor script only; injects `logger_factory: LoggerFactory`)
- `receivers.py` — `BotUpdate` frozen dataclass (update_id, chat_id, text), `TelegramUpdatePoller` (long-polls Telegram `getUpdates` API with `timeout=30`; returns `list[BotUpdate]`; skips updates without text; returns `[]` on any HTTP/network error; injects `logger_factory: LoggerFactory`)
- `repositories.py` — `InMemoryStockRepository` implements `StockRepository` (in-memory dict store)
- `formatters.py` — `ConsolidatingNotificationFormatter` implements `NotificationFormatter` (two-bucket categorization: standalone (`STANDALONE_NOTIFICATION_TYPES`) vs consolidatable (everything else); all consolidatable notifications are joined into a single message with a header line followed by body lines; header priority via `_pick_header()`: (1) market-open notification, (2) first percentage change notification (non-milestone, non-market-open), (3) fallback generated on demand from `StockContext` via `Notification.create_percentage_change()` or `Notification.create_plain_header()` when no `previous_close_price`; the header notification is excluded from body lines; standalone notifications always emit as separate messages), `RegularStockStatisticsFormatter` implements `StockStatisticsFormatter` (header `📊 {symbol} — {current_price:.2f}`, then one line per price change with period, close price, and percentage change with 📈/📉 icon; fallback "No historical data available" when price_changes is empty)
- `exceptions.py` — `ConfigurationError` (raised by `SettingsFactory` on missing or invalid env vars), `ConfigLoadingFailed` (raised by `ConfigManager.read_monitor_stocks_config()` when a JSON config file is missing, malformed, or invalid)
- `configs.py` — `CONFIGS_DIR: Path` (project root `configs/` directory, used by composition roots only); `SymbolConfig` frozen dataclass (symbol, prices as `list[Decimal]` — no validation), `MonitorStocksConfig` frozen dataclass (interval, symbols as `list[SymbolConfig]` — with validation), `ConfigManager` (loads/writes a single JSON config file, raises `ConfigLoadingFailed` on any read error; per-symbol mutators `replace_symbol_prices(symbol, prices)`, `add_symbol(symbol)`, `remove_symbol(symbol)` re-read the config on disk, rebuild the dataclass, and write it back); `ConfigStore(configs_dir: Path)` owns every directory-scoped concern — `list_paths() -> list[Path]` (sorted `*.json` paths), `list_names() -> list[str]` (sorted file stems), `find_by_name(name) -> tuple[Path, MonitorStocksConfig] | None` (looks up a config by name, returns `None` if not found or load fails), `find_for_symbol(symbol) -> tuple[Path, MonitorStocksConfig] | None` (scans alphabetically, returns the first config containing the upper-cased symbol), `list_tracked_symbols() -> list[str]` (deduplicated sorted symbols across all configs, malformed files skipped), `list_tracked_symbols_with_targets() -> list[tuple[str, list[Decimal]]]` (same but pairs each symbol with its target prices — first-seen config wins for deduplication), `validate_name(name) -> str | None` (rejects empty/whitespace, names containing `/` or `.`, and existing files; returns the error string or `None`), `create(name, config) -> Path` (ensures the directory exists, writes the JSON, returns the path), `delete_by_path(path)` (removes the file). `ConfigStore` is the single source of truth for config-file persistence — both the console commands and the Telegram bot inject one instance built from `CONFIGS_DIR` at the composition root
- `factories.py` — `SettingsFactory` (creates `YahooFinanceSettings` from `MAX_FETCH_WORKERS` env var and optional `extra_delay_in_minutes: int = 0` parameter (no longer from env), creates `TelegramSettings` from Telegram env vars, creates `LoggingSettings` for cli/monitor/bot/report entry points via `create_cli_logging_settings()`, `create_monitor_logging_settings()`, `create_bot_logging_settings()`, `create_report_logging_settings()`; raises `ConfigurationError` on missing vars or non-integer `MAX_FETCH_WORKERS`)
- `logging.py` — `CLI_ENTRY_POINT`, `MONITOR_ENTRY_POINT`, `BOT_ENTRY_POINT`, `REPORT_ENTRY_POINT` constants; `LoggingSettings` frozen dataclass; `setup_logging(settings)` configures root logger per entry point: stderr handler if verbose, file handler (named `pryces_{entry_point}_timestamp.log`) if `LOGS_DIRECTORY` is set, `NullHandler` fallback if no handlers; `debug` scopes DEBUG level to `pryces` logger only; `PythonLogger` implements `Logger` (wraps `logging.Logger`, delegates all level calls); `PythonLoggerFactory` implements `LoggerFactory` (delegates to `logging.getLogger(name)`) — instantiated once at each composition root

**Presentation** (`src/pryces/presentation/console/`) — Interactive CLI:
- `cli.py` — Entry point, composition root (wires dependencies)
- `menu.py` — `InteractiveMenu` (main loop, I/O via injectable streams)
- `commands/base.py` — `Command` ABC, `CommandMetadata`, `InputPrompt` (frozen dataclass: `key`, `prompt`, optional `validator`, optional `preamble: str | None` — displayed before the prompt by the menu), `CommandResult` (frozen dataclass: `message: str`, `success: bool = True`)
- `commands/get_stocks_prices.py` — `GetStocksPricesCommand` (one or multiple symbols → formatted output; injects `logger_factory: LoggerFactory`)
- `commands/list_configs.py` — `ListConfigsCommand` (injects `ConfigStore`; uses `store.list_paths()` to scan, loads each config via `ConfigManager`, displays interval + symbols per config)
- `commands/create_config.py` — `CreateConfigCommand` (injects `ConfigStore`; prompts for name, interval, symbols with optional target prices; uses `store.validate_name` for prompt-time validation and `store.create(name, MonitorStocksConfig(...))` to persist)
- `commands/edit_config.py` — `EditConfigCommand` (injects `ConfigStore`; dynamic prompts: config picker → operation (1=interval, 2=symbols) → new value; lenient prompt-time validator, strict parse in `execute()`; returns `success=False` on bad input; reads/writes via `ConfigManager` per file)
- `commands/delete_config.py` — `DeleteConfigCommand` (injects `ConfigStore`; dynamic prompts: config picker → confirm "yes"/"no"; deletes via `store.delete_by_path(path)`)
- `commands/monitor_stocks.py` — `MonitorStocksCommand` (injects `ConfigStore`; dynamic config picker via `store.list_paths()`; prompts for duration and extra delay; launches the standalone monitor script as a detached background process via `subprocess.Popen`, returns PID; returns `success=False` on `OSError` from `Popen`; returns error if no configs found)
- `commands/list_monitors.py` — `ListMonitorsCommand` (queries `ps aux` for running monitor script processes, extracts PID and config path; displays numbered entries)
- `commands/stop_monitor.py` — `StopMonitorCommand` (uses standard `Command` contract: `get_input_prompts()` fetches running monitors and returns an `InputPrompt` with preamble showing the process list and a selection validator; `execute()` kills the selected process or returns cancellation/no-processes message)
- `commands/check_readiness.py` — `CheckResult` frozen dataclass (`ready: bool`, `message: str`), `Checker` ABC (`check() -> CheckResult`), `EnvVarsChecker` (validates all env vars), `TelegramChecker` (sends test message; injects `SendMessages` + `Logger`), `CheckReadinessCommand` (orchestrates a `list[Checker]`; iterates checkers, aggregates results, appends warning on any failure; injects `logger_factory: LoggerFactory`)
- `commands/registry.py` — `CommandRegistry` (registry pattern)
- `factories.py` — `CommandFactory` (DI + object creation; injects `logger_factory: LoggerFactory` and `config_store: ConfigStore`, threads them to commands that need them)
- `utils.py` — shared validators (`validate_symbol`, `validate_symbols`, `validate_positive_integer`, `validate_non_negative_integer`, `validate_file_path`, `validate_symbols_with_targets`, `create_monitor_selection_validator(process_count) -> Callable`, `create_config_selection_validator(count) -> Callable`); parsers (`parse_symbols_input`, `parse_symbols_with_targets`); formatters (`format_stock`, `format_stock_list`, `format_running_monitors`, `format_config_list`, `format_config_details`); `get_running_monitors() -> list[tuple[str, str]]` (queries `ps -eo pid=,cmd=`). All config-directory access lives on `ConfigStore` in `infrastructure/configs.py`

**Presentation — Scripts** (`src/pryces/presentation/scripts/`) — Standalone scripts for automated execution:
- `config_refresher.py` — `ConfigRefresher` (owns monitor-script config lifecycle: `refresh()` hot-reloads config from disk via `ConfigManager`, `remove_fulfilled_targets(fulfilled)` filters out fulfilled `TargetPriceDTO` prices from config symbols — keeping the symbol entry even when all its prices are removed — and persists via `ConfigManager.write_monitor_stocks_config`, `log_config()` logs monitoring cadence and symbols; holds mutable `config` property; injects `logger_factory: LoggerFactory`). Config dataclasses, `ConfigManager`, query helpers, and `ConfigLoadingFailed` live in `infrastructure/configs.py` and `infrastructure/exceptions.py`.
- `bot_commands.py` — `_MAX_MESSAGE_LENGTH` (256), `_MAX_INTEGER_DIGITS` (7), `_MAX_DECIMAL_DIGITS` (8) module-level constants; `_validate_price(raw) -> Decimal | str` (string-based validation before `Decimal()` conversion — rejects negative/zero values, scientific notation, and oversized digit strings; returns `"❌ Invalid price"` on failure); `BotCommand` ABC (name, usage, description, arg_count, execute), `TargetsCommand` (lists target prices for a symbol), `TargetAddCommand` (adds a target price to a symbol's config; calls `ConfigManager.replace_symbol_prices`), `TargetRemoveCommand` (removes a target price; calls `ConfigManager.replace_symbol_prices`), `SymbolAddCommand` (adds a new symbol entry to a named config via `ConfigManager.add_symbol`; injects `_FindConfigByNameFn`), `SymbolRemoveCommand` (removes a symbol from whichever config contains it via `ConfigManager.remove_symbol`; guards against removing the last symbol; injects `_FindConfigFn`), `SymbolsCommand` (lists all tracked symbols with their target prices as a numbered list; injects `_GetAllSymbolsWithTargetsFn`), `ConfigsCommand` (lists all config file names without path or extension; injects `_GetConfigNamesFn`), `StatsCommand` (triggers statistics delivery for a symbol; injects `_GetStockStatisticsFn = Callable[[str], None]` — the function calls `TriggerStocksStatistics` internally, which sends the formatted message via `MessageSender`; `execute()` returns `""` on success), `HelpCommand` (formats usage for all commands); `_FindConfigFn`, `_FindConfigByNameFn`, `_GetAllSymbolsFn`, `_GetAllSymbolsWithTargetsFn`, `_GetConfigNamesFn`, `_GetStockStatisticsFn` type aliases; `_find_symbol_config` private helper resolves a symbol to its `(path, config, symbol_config)` tuple via the injected `_FindConfigFn`; `BotCommandDispatcher` (routes text to commands by name, silently ignores messages exceeding `_MAX_MESSAGE_LENGTH`, returns empty string for non-commands, ❓-prefixed message for unknown commands or wrong arg count; injects `logger_factory: LoggerFactory`, logs command name and args on execution)
- `monitor_stocks.py` — Standalone monitor script (`MonitorStocksScript` class, argparse CLI, logging). Entry point: `main()`. Args: `config` (required path), `--duration` (int, required — monitoring duration in minutes), `--extra-delay` (int, default 0 — passed to `SettingsFactory.create_yahoo_finance_settings()`), `--debug`, `--verbose`. Single responsibility: orchestrating the monitoring cycle (loop, scheduling, delegation). Delegates config lifecycle to injected `ConfigRefresher`, passes target prices from config into `TriggerStocksNotificationsRequest.targets` on each iteration. Composition root (`_create_script`) creates a single `PythonLoggerFactory` instance and threads it to all infrastructure adapters, `ConfigRefresher`, and `MonitorStocksScript`; `_ScriptContext` groups the script and sender so `main()` calls `shutdown()` in a `finally` block. `MonitorStocksScript` injects `logger_factory: LoggerFactory`.
- `telegram_bot.py` — Standalone Telegram bot script (`TelegramBotScript` class, argparse CLI). Entry point: `main()`. Args: `--debug`, `--verbose`. Long-polls Telegram for commands, filters by `TELEGRAM_GROUP_ID`, dispatches to `BotCommandDispatcher`, sends replies via `TelegramMessageSender`. Composition root (`_create_script`) wires `TelegramUpdatePoller`, `TelegramMessageSender`, bot commands, and dispatcher; instantiates one `ConfigStore(CONFIGS_DIR)` and passes its bound methods (`find_for_symbol`, `find_by_name`, `list_tracked_symbols_with_targets`, `list_names`) to the bot command constructors.
- `report_stocks_statistics.py` — Standalone one-shot script (`ReportStocksStatisticsScript` class, argparse CLI). Entry point: `main()`. Args: `--debug`, `--verbose`. Injects a `list_tracked_symbols: Callable[[], list[str]]` callable; in `run()` it calls the callable and delegates the full fetch → format → send pipeline to `TriggerStocksStatistics`. Exits immediately — designed for scheduled (cron) use. Composition root (`_create_script`) wires `YahooFinanceStatisticsProvider`, `TelegramMessageSender`, `TriggerStocksStatistics` (with `RegularStockStatisticsFormatter`), and `ConfigStore(CONFIGS_DIR).list_tracked_symbols`.

### Key Patterns
- **Ports & Adapters**: Application defines ABCs, infrastructure implements them
- **Command Pattern**: Each CLI action is a `Command` with metadata, input prompts, and execute
- **Factory + Registry**: `CommandFactory` builds commands, `CommandRegistry` stores them
- **Dependency Injection**: Wired at composition root in `cli.py`

### Entry Points
```bash
python -m pryces.presentation.console.cli                         # Interactive CLI
python -m pryces.presentation.scripts.monitor_stocks CONFIG_PATH --duration N  # Monitor script
python -m pryces.presentation.scripts.telegram_bot                # Telegram bot for target management
python -m pryces.presentation.scripts.report_stocks_statistics    # One-shot statistics report
```

## Patterns and Conventions

### Dependency Management
- Minimize use of third-party packages
- Only add external dependencies when:
  - There is no reasonable alternative to implement the functionality
  - The package is secure, well-maintained, and clearly the best option for the use case
- Prefer built-in language/platform features over external libraries

### PEP 8 Compliance

All Python code must follow [PEP 8](https://peps.python.org/pep-0008/) style guidelines:
- **Line length**: Maximum 100 characters (enforced by `black`)
- **Naming**: `snake_case` for variables/functions, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants, `_prefix` for private members
- **Imports**: Standard library → third-party → local; one import per line; no wildcard imports
- **Type hints**: Use built-in generics (`dict`, `list`, `tuple`) over `typing` equivalents (`Dict`, `List`, `Tuple`) — requires Python 3.9+
- **Formatting**: Enforced automatically by the `black` pre-commit hook — never skip it
- **No shadowing built-ins**: Never use built-in names (`type`, `id`, `list`, `dict`, `filter`, etc.) as parameter or variable names — rename to something more specific (e.g. `notification_type` instead of `type`)

### Class Member Ordering

Within every class, members must appear in this order:
1. `__slots__`
2. Class-level constants and attributes
3. `__init__` (then other dunder/magic methods if any)
4. Properties (`@property`)
5. Public instance methods
6. Private/protected methods (`_` prefix)

### Code Comments

**Write self-documenting code.** Use clear names, structure, and type hints. Only add comments when they explain WHY, not WHAT.

**Rules:**
1. **Type hints eliminate documentation**: If a parameter has a type hint, don't document its type in a docstring
2. **Method names should be obvious**: `get_command()`, `register()`, `validate_symbol()` need no docstring
3. **No restating**: `def __init__()` → "Initialize X" adds zero value
4. **Comments explain reasoning**: Use them for business logic, heuristics, or non-obvious constraints

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format: `<type>: <description>`

Common types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

**Commit rules (non-negotiable):**
- **Tests must pass before every commit** — never commit with a failing test suite
- **Never skip pre-commit hooks** (`--no-verify` is forbidden unless the user explicitly instructs it; if a hook fails, fix the root cause)
- **Atomic commits** — one logical change per commit; do not mix unrelated changes
- **Documentation in the same commit** — if the commit changes behavior, CLAUDE.md and/or README.md must be updated in that same commit, not a follow-up
