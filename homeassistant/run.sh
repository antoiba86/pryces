#!/usr/bin/env bash
set -euo pipefail

OPTIONS=/data/options.json

option() {
    jq -r --arg fallback "$2" ".$1 // \$fallback" "${OPTIONS}"
}

# /data is the app's persistent volume — it survives restarts and updates, and
# Home Assistant sweeps it into its backups.
export PRYCES_DATA_DIR=/data/pryces
export PRYCES_WEB_DIR=/app/web
export LOGS_DIRECTORY=/data/logs
mkdir -p "${PRYCES_DATA_DIR}" "${LOGS_DIRECTORY}"

export MAX_FETCH_WORKERS="$(option max_fetch_workers 2)"
export CACHE_TTL_SECONDS="$(option cache_ttl_seconds 300)"
export CACHE_CLOSED_TTL_SECONDS="$(option cache_closed_ttl_seconds 3600)"
export CACHE_FX_TTL_SECONDS="$(option cache_fx_ttl_seconds 3600)"
export CACHE_HISTORICAL_TTL_SECONDS="$(option cache_historical_ttl_seconds 86400)"

# Only exported when set, so the Telegram adapters stay inactive by default.
telegram_bot_token="$(option telegram_bot_token "")"
telegram_group_id="$(option telegram_group_id "")"
[ -n "${telegram_bot_token}" ] && export TELEGRAM_BOT_TOKEN="${telegram_bot_token}"
[ -n "${telegram_group_id}" ] && export TELEGRAM_GROUP_ID="${telegram_group_id}"

log_level="$(option log_level info)"

echo "[pryces] data=${PRYCES_DATA_DIR} web=${PRYCES_WEB_DIR} log_level=${log_level}"

# Bound to 0.0.0.0 inside the container only; ingress is the sole way in.
exec python -m uvicorn pryces.presentation.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level "${log_level}"
