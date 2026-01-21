#!/usr/bin/env bash

set -e

# Verify required environment variables
if [ -z "$PROXIED_SERVICE_BASE_URL" ] || [ -z "$WEBSERVER_HTTP_PORT" ] || [ -z "$GATEWAY_SERVICE_BASE_URL" ] || [ -z "$GATEWAY_PROXY_PATH" ] || [ -z "$LANGUAGE" ] || [ -z "$MODEL_TYPE" ]; then
    echo "Error: PROXIED_SERVICE_BASE_URL, WEBSERVER_HTTP_PORT, GATEWAY_SERVICE_BASE_URL, GATEWAY_PROXY_PATH, LANGUAGE, MODEL_TYPE must be set." >&2
    exit 1
fi

TEMPLATE_FILE="heartbeat.json"

# Check if the template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "Error: $TEMPLATE_FILE not found." >&2
    exit 1
fi

# set default value for api-gateway registry
WEBSERVER_HTTP_PORT="${WEBSERVER_HTTP_PORT:-8080}"
ACCOUSTIC="${ACCOUSTIC:-1}"
MODEL_QUALITY="${MODEL_QUALITY:-1}"
SECURITY_LEVEL="${SECURITY_LEVEL:-0}"

if [ -z "$GATEWAY_DESCRIPTION" ]; then
    export GATEWAY_DESCRIPTION="{\"en\": \"${SERVICE_NAME}\", \"fr\": \"${SERVICE_NAME}\"}"
fi
json_payload=$(envsubst <"$TEMPLATE_FILE")

curl -f -X POST -H "Content-Type: application/json" -d "$json_payload" "${GATEWAY_SERVICE_BASE_URL}/gateway/services?type=transcription"
