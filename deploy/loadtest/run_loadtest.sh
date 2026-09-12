#!/usr/bin/env bash
# Orchestrates a full run from the loadgen VM: seed once, then run Locust
# (headless, HTTP paths) and the telemetry WebSocket load concurrently for
# the same window so Grafana shows one coherent traffic period.
set -euo pipefail

KONG_URL="${1:?usage: run_loadtest.sh <kong-url> <postgres-private-ip> [duration-seconds]}"
POSTGRES_HOST="${2:?usage: run_loadtest.sh <kong-url> <postgres-private-ip> [duration-seconds]}"
DURATION="${3:-300}"
# Telemetry deliberately outnumbers Locust users several times over — a
# real fleet's GPS/speed stream volume dwarfs concurrent human bookers, and
# the earlier defaults (200 users / 100 vehicles) were light enough a
# monolith would've shrugged them off, which defeats the point of this
# test. Override any of these via env var without editing the script.
LOCUST_USERS="${LOCUST_USERS:-1500}"
LOCUST_SPAWN_RATE="${LOCUST_SPAWN_RATE:-50}"
TELEMETRY_VEHICLES="${TELEMETRY_VEHICLES:-3000}"
TELEMETRY_RAMP_SECONDS="${TELEMETRY_RAMP_SECONDS:-60}"

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ ! -f seed_data.json ]]; then
  echo "==> seeding (no seed_data.json found)"
  python seed_vehicles.py --kong-url "$KONG_URL" --postgres-host "$POSTGRES_HOST"
else
  echo "==> reusing existing seed_data.json (delete it to reseed)"
fi

echo "==> starting telemetry load in the background (ramping over ${TELEMETRY_RAMP_SECONDS}s)"
python telemetry_load.py --kong-url "$KONG_URL" --vehicles "$TELEMETRY_VEHICLES" \
  --rate-hz 1 --ramp-seconds "$TELEMETRY_RAMP_SECONDS" --duration-seconds "$DURATION" &
TELEMETRY_PID=$!

echo "==> running locust headless for ${DURATION}s (${LOCUST_USERS} users, spawn rate ${LOCUST_SPAWN_RATE}/s)"
locust -f locustfile.py --host "$KONG_URL" \
  --headless --users "$LOCUST_USERS" --spawn-rate "$LOCUST_SPAWN_RATE" \
  --run-time "${DURATION}s" --csv=results --html=report.html

wait "$TELEMETRY_PID"
echo "==> done. results_*.csv and report.html are in $(pwd) — while Jaeger/Grafana still hold the window, go look."
