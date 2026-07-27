DURATION ?= 1
DEBUG_FLAG := $(if $(DEBUG),--debug,)
VERBOSE_FLAG := $(if $(VERBOSE),--verbose,)
EXTRA_DELAY_FLAG := $(if $(EXTRA_DELAY),--extra-delay $(EXTRA_DELAY),)
RUN := uv run
RUN_DEV := uv run --extra dev

WEB_DIST ?= ../caudalnet-web/dist/caudalnet-web/browser
HA_APP_DIR := build/ha-app

.PHONY: cli monitor bot report api test format ha-app

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

# Assembles the Home Assistant app into a single self-contained folder — Supervisor
# builds the Dockerfile with the app folder as its context, so the sources and the
# prebuilt dashboard have to sit inside it. Copy the result to /addons/pryces/.
ha-app:
	@test -f "$(WEB_DIST)/index.html" || { \
		echo "CaudalNet bundle not found at $(WEB_DIST)"; \
		echo "Run 'npm run build' in caudalnet-web first, or pass WEB_DIST=<path>"; \
		exit 1; \
	}
	rm -rf $(HA_APP_DIR)
	mkdir -p $(HA_APP_DIR)
	cp homeassistant/config.yaml homeassistant/Dockerfile homeassistant/run.sh $(HA_APP_DIR)/
	cp homeassistant/DOCS.md $(HA_APP_DIR)/
	cp pyproject.toml uv.lock README.md $(HA_APP_DIR)/
	cp -R src $(HA_APP_DIR)/src
	cp -R $(WEB_DIST) $(HA_APP_DIR)/web
	@echo "Home Assistant app assembled at $(HA_APP_DIR)"
