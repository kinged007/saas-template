#!/usr/bin/env bash
# Manage a local NATS JetStream container for the event bus (plain docker —
# no docker compose required).
#
# Usage:
#   scripts/nats.sh start   # create + start the container (idempotent)
#   scripts/nats.sh stop    # stop + remove the container
#   scripts/nats.sh logs    # show recent container logs (non-blocking)
#   scripts/nats.sh status  # show container + JetStream info
#
# The docker daemon may be remote (DOCKER_HOST set, e.g. a Tailscale host);
# in that case the published ports live on the daemon host, not localhost, so
# the printed client/monitor URLs and the status check use that host.
#
# Branding: APP_SLUG renames the container and the NATS server name;
# NATS_CONTAINER_NAME overrides the container name alone.
set -euo pipefail

NAME="${NATS_CONTAINER_NAME:-${APP_SLUG:-saas-template}-nats}"
SERVER_NAME="${APP_SLUG:-saas-template}"
IMAGE="nats:2.10-alpine"
MONITOR_PORT="${NATS_MONITOR_PORT:-8222}"
CLIENT_PORT="${NATS_CLIENT_PORT:-4222}"

host() {
    case "${DOCKER_HOST:-}" in
        tcp://*)
            echo "${DOCKER_HOST#tcp://}" | cut -d: -f1
            ;;
        *)
            echo "localhost"
            ;;
    esac
}

HOST="$(host)"

running() {
    docker ps --format '{{.Names}}' | grep -qx "$NAME"
}

start() {
    if running; then
        echo "nats already running ($NAME)"
        echo "  client : nats://${HOST}:${CLIENT_PORT}"
        echo "  monitor: http://${HOST}:${MONITOR_PORT}"
        return 0
    fi
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d \
        --name "$NAME" \
        -p "${CLIENT_PORT}:4222" \
        -p "${MONITOR_PORT}:8222" \
        "$IMAGE" \
        -js -m 8222 --server_name "$SERVER_NAME"
    echo "nats started ($NAME)"
    echo "  client : nats://${HOST}:${CLIENT_PORT}"
    echo "  monitor: http://${HOST}:${MONITOR_PORT}"
    echo "Set EVENT_BUS_DRIVER=nats and NATS_URL=nats://${HOST}:${CLIENT_PORT} to use it."
}

stop() {
    if ! running; then
        echo "nats not running ($NAME)"
        return 0
    fi
    docker rm -f "$NAME" >/dev/null 2>&1
    echo "nats stopped ($NAME)"
}

logs() {
    if ! running; then
        echo "nats not running ($NAME)"
        return 1
    fi
    docker logs --tail "${NATS_LOG_LINES:-50}" "$NAME"
}

status() {
    if ! running; then
        echo "nats not running ($NAME)"
        return 1
    fi
    docker ps --filter "name=^${NAME}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    if curl -sf "http://${HOST}:${MONITOR_PORT}/jsz" >/dev/null 2>&1; then
        echo "jetstream: enabled (monitor http://${HOST}:${MONITOR_PORT})"
    else
        echo "monitor endpoint not reachable on ${HOST}:${MONITOR_PORT}"
    fi
}

case "${1:-start}" in
    start) start ;;
    stop) stop ;;
    logs) logs ;;
    status) status ;;
    *)
        echo "usage: $0 [start|stop|logs|status]" >&2
        exit 1
        ;;
esac