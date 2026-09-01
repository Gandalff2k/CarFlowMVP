#!/usr/bin/env bash
set -euo pipefail

DEBEZIUM_URL="${DEBEZIUM_URL:-http://localhost:8083}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for config_file in "$SCRIPT_DIR"/*-connector.json; do
    connector_name="$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "$config_file")"
    echo "Registering ${connector_name} from ${config_file}..."
    status=$(curl -s -o /tmp/debezium-register-response.json -w "%{http_code}" \
        -X PUT "${DEBEZIUM_URL}/connectors/${connector_name}/config" \
        -H "Content-Type: application/json" \
        -d "$(python -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1]))['config']))" "$config_file")")
    if [[ "$status" != "200" && "$status" != "201" ]]; then
        echo "Failed to register ${connector_name} (HTTP ${status}):"
        cat /tmp/debezium-register-response.json
        exit 1
    fi
    echo "  -> OK (HTTP ${status})"
done
