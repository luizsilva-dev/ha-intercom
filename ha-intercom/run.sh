#!/usr/bin/with-contenv bashio

bashio::log.info "Starting HA Intercom add-on"

# Read config options
LOG_LEVEL=$(bashio::config 'log_level')
CALL_TIMEOUT=$(bashio::config 'call_timeout')
MAX_CALL_DURATION=$(bashio::config 'max_call_duration')

# Build go2rtc config from template + options
python3 /app/generate_config.py

# Export env vars for the API
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_URL="http://supervisor/core"
export GO2RTC_URL="http://localhost:1984"
export CALL_TIMEOUT="${CALL_TIMEOUT}"
export MAX_CALL_DURATION="${MAX_CALL_DURATION}"
export LOG_LEVEL="${LOG_LEVEL}"
export OPTIONS_PATH="/data/options.json"

bashio::log.info "Starting go2rtc (log level: ${LOG_LEVEL})"
go2rtc -config /data/go2rtc.yaml &
GO2RTC_PID=$!

# Wait for go2rtc to be ready
sleep 2

bashio::log.info "Starting intercom signaling API"
python3 /app/main.py &
API_PID=$!

# Trap for clean shutdown
trap "kill $GO2RTC_PID $API_PID 2>/dev/null; exit 0" SIGTERM SIGINT

bashio::log.info "HA Intercom is running"
wait $GO2RTC_PID $API_PID
