#!/usr/bin/env bash

set -eax

curl -f http://localhost:80/healthcheck || exit 1

if [ "$REGISTRATION_MODE" = "HTTP" ]
then
    # The heartbeat as no impact on the health
    ./heartbeat.sh || true
fi
