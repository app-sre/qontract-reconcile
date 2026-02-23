#!/bin/bash
echo "Starting Qontract API ..."

# shellcheck disable=SC2154
if [[ "${QAPI_LOG_LEVEL}" == "DEBUG" ]]; then
    set -x
fi

if [[ -n "${QAPI_WORKER_TEMP_DIR}" ]]; then
    PROMETHEUS_MULTIPROC_DIR=$(mktemp -d -p "${QAPI_WORKER_TEMP_DIR}")
else
    PROMETHEUS_MULTIPROC_DIR=$(mktemp -d)
fi
export PROMETHEUS_MULTIPROC_DIR
# shellcheck disable=SC2064
trap "rm -rf ${PROMETHEUS_MULTIPROC_DIR}" INT TERM EXIT

START_MODE="${QAPI_START_MODE:-api}"
APP_PORT="${QAPI_APP_PORT:-8080}"
AUTO_RELOAD="${AUTO_RELOAD:-0}"
UVICORN_OPTS="${QAPI_UVICORN_OPTS:- --host 0.0.0.0 --proxy-headers --forwarded-allow-ips=* --no-access-log}"
UVICORN_OPTS="${UVICORN_OPTS} --port ${APP_PORT}"

# start celery worker with solo pool by default to ensure only one worker is running
# we scale the number of workers using kubernetes pods
# this also ensures prometheus metrics are working
CELERY_OPTS="${QAPI_CELERY_OPTS:- --pool solo}"

# Subscriber runs a separate uvicorn instance
SUBSCRIBER_OPTS="${QAPI_SUBSCRIBER_OPTS:- --host 0.0.0.0 --proxy-headers --forwarded-allow-ips=* --no-access-log}"
SUBSCRIBER_OPTS="${SUBSCRIBER_OPTS} --port ${APP_PORT}"

DEBUGGER_PORT=${DEBUGPY_PORT:-5678}
DEBUGGER_ENABLED="${DEBUGGER_ENABLED:-false}"

if [[ "${AUTO_RELOAD}" == "1" ]]; then
    echo "---> Auto-reload enabled ..."
    CMD_CHAIN=(watchmedo auto-restart -d /opt/app-root/src -p '*.py;*.env*' --recursive --kill-after 1 --debug-force-polling --)
fi

# Enable debugpy for remote debugging
if [[ "${DEBUGGER_ENABLED}" == "true" ]]; then
    # disable pydevd file validation to allow debugging code in mounted volumes
    export PYDEVD_DISABLE_FILE_VALIDATION=1
    echo "---> Debugpy enabled - waiting for debugger on port ${DEBUGGER_PORT} ..."
    CMD_CHAIN=("${CMD_CHAIN[@]}" python -m debugpy --listen 0.0.0.0:"${DEBUGGER_PORT}" -m )
fi

if [[ "${START_MODE}" == "api" ]]; then
    echo "---> Serving application with uvicorn ..."
    # shellcheck disable=SC2086,SC2090
    exec "${CMD_CHAIN[@]}" uvicorn ${UVICORN_OPTS} "$@" qontract_api.main:app
elif [[ "${START_MODE}" == "worker" ]]; then
    echo "---> Starting worker ..."
    # shellcheck disable=SC2086,SC2090
    exec "${CMD_CHAIN[@]}" celery --app=qontract_api.worker worker ${CELERY_OPTS} "$@"
elif [[ "${START_MODE}" == "subscriber" ]]; then
    echo "---> Starting subscriber ..."
    # shellcheck disable=SC2086,SC2090
    exec "${CMD_CHAIN[@]}" uvicorn ${SUBSCRIBER_OPTS} "$@" qontract_api.subscriber:app
else
    echo "unknow mode ${START_MODE} - use 'api', 'worker' or'subscriber' instead"
fi
