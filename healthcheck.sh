#!/usr/bin/env bash

set -eax

curl -f http://localhost:$WEBSERVER_HTTP_PORT/healthcheck || exit 1

if [ "$REGISTRATION_MODE" = "HTTP" ]
then
    # The heartbeat as no impact on the health
    ./heartbeat.sh || true
fi
