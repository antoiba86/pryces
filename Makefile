DURATION ?= 1
DEBUG_FLAG := $(if $(DEBUG),--debug,)
VERBOSE_FLAG := $(if $(VERBOSE),--verbose,)
EXTRA_DELAY_FLAG := $(if $(EXTRA_DELAY),--extra-delay $(EXTRA_DELAY),)
RUN := uv run
RUN_DEV := uv run --extra dev

.PHONY: cli monitor bot report api test format

cli:
	$(RUN) python -m pryces.presentation.console.cli $(DEBUG_FLAG)

monitor:
ifndef CONFIG
	$(error CONFIG is required. Usage: make monitor CONFIG=configs/myconfig.json)
endif
	$(RUN) python -m pryces.presentation.scripts.monitor_stocks $(CONFIG) --duration $(DURATION) $(DEBUG_FLAG) $(VERBOSE_FLAG) $(EXTRA_DELAY_FLAG)

bot:
	$(RUN) python -m pryces.presentation.scripts.telegram_bot $(DEBUG_FLAG) $(VERBOSE_FLAG)

report:
	$(RUN) python -m pryces.presentation.scripts.report_stocks_statistics $(DEBUG_FLAG) $(VERBOSE_FLAG)

api:
	$(RUN) python -m uvicorn pryces.presentation.api.main:app --port 8000

test:
	$(RUN_DEV) pytest

format:
	$(RUN_DEV) black src/ tests/ --line-length 100
