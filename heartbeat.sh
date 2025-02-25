#!/usr/bin/env bash

set -e

# Verify required environment variables
if [ -z "$PROXIED_SERVICE_BASE_URL" ] || [ -z "$PROXIED_SERVICE_HTTP_PORT" ] || [ -z "$GATEWAY_SERVICE_BASE_URL" ] || [ -z "$GATEWAY_PROXY_PATH" ]; then
    echo "Error: PROXIED_SERVICE_BASE_URL, PROXIED_SERVICE_HTTP_PORT, GATEWAY_SERVICE_BASE_URL, GATEWAY_PROXY_PATH must be set." >&2
    exit 1
fi

TEMPLATE_FILE="heartbeat.json"

# Check if the template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "Error: $TEMPLATE_FILE not found." >&2
    exit 1
fi


json_payload=$(envsubst < "$TEMPLATE_FILE")
curl -f -X POST -H "Content-Type: application/json" -d "$json_payload" "${GATEWAY_SERVICE_BASE_URL}/gateway/services?type=transcription"
