#!/bin/bash
echo "Starting Qontract API ..."

# shellcheck disable=SC2154
if [[ "${QAPI_DEBUG}" == "1" ]]; then
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
AUTO_RELOAD="${QAPI_AUTO_RELOAD:-0}"
UVICORN_OPTS="${QAPI_UVICORN_OPTS:- --host 0.0.0.0 --proxy-headers --forwarded-allow-ips=*}"
UVICORN_OPTS="${UVICORN_OPTS} --port ${APP_PORT}"
# start celery worker with solo pool by default to ensure only one worker is running
# we scale the number of workers using kubernetes pods
# this also ensures prometheus metrics are working
CELERY_OPTS="${QAPI_CELERY_OPTS:- --pool solo}"
DEBUGGER_PORT=${DEBUGPY_PORT:-5678}
DEBUGGER_ENABLED="${DEBUGGER_ENABLED:-false}"

if [[ "${START_MODE}" == "api" ]]; then
    echo "---> Serving application with uvicorn ..."
    if [[ "${AUTO_RELOAD}" == "1" ]]; then
        # Use polling for Docker volume compatibility
        UVICORN_OPTS="${UVICORN_OPTS} --reload --reload-delay 1"
        export WATCHFILES_FORCE_POLLING=true
    fi

    # Enable debugpy for remote debugging
    if [[ "${DEBUGGER_ENABLED}" == "true" ]]; then
        echo "---> Debugpy enabled - waiting for debugger on port ${DEBUGGER_PORT} ..."
        # shellcheck disable=SC2086
        exec python -m debugpy --listen 0.0.0.0:${DEBUGGER_PORT} --wait-for-client -m uvicorn ${UVICORN_OPTS} "$@" qontract_api.main:app
    else
        # shellcheck disable=SC2086
        exec uvicorn ${UVICORN_OPTS} "$@" qontract_api.main:app
    fi
elif [[ "${START_MODE}" == "worker" ]]; then
    if [[ "${AUTO_RELOAD}" == "1" ]]; then
        echo "--> Starting worker with auto-restart enabled"
        # shellcheck disable=SC2086
        watchmedo auto-restart -d /opt/app-root/src/qontract_api \
            -p '*.py' \
            --recursive \
            --kill-after 1 \
            --debug-force-polling \
            -- celery --app=qontract_api.worker worker ${CELERY_OPTS} "$@"
    else
        echo "---> Starting worker ..."
        # shellcheck disable=SC2086
        exec celery --app=qontract_api.worker worker ${CELERY_OPTS} "$@"
    fi

else
    echo "unknow mode ${START_MODE} - use 'api' or 'worker' instead"
fi
