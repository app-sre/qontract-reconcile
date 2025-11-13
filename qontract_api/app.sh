#!/bin/bash
echo "Starting qontract-api ..."

if [[ "${QAPI_DEBUG}" == "1" ]]; then
    set -x
fi

if [ -r "settings.conf" ]; then
    set -a
    # shellcheck source=/dev/null
    . settings.conf
    set +a
fi

START_MODE="${QAPI_START_MODE:-api}"
APP_PORT="${QAPI_APP_PORT:-8000}"
QAPI_AUTO_RELOAD="${QAPI_AUTO_RELOAD:-0}"
UVICORN_OPTS="${QAPI_UVICORN_OPTS:- --host 0.0.0.0 --proxy-headers --forwarded-allow-ips=*}"
UVICORN_OPTS="${UVICORN_OPTS} --port ${APP_PORT}"
# start celery worker with solo pool by default to ensure only one worker is running
# we scale the number of workers using kubernetes pods
# this also ensures prometheus metrics are working
CELERY_OPTS="${QAPI_CELERY_OPTS:- --pool solo}"

if [[ "${START_MODE}" == "api" ]]; then
    echo "---> Serving application with uvicorn ..."
    [[ "${QAPI_AUTO_RELOAD}" == "1" ]] && UVICORN_OPTS="${UVICORN_OPTS} --reload"
    # shellcheck disable=SC2086
    exec uv run --directory qontract_api uvicorn $UVICORN_OPTS "$@" qontract_api.main:app
elif [[ "${START_MODE}" == "worker" ]]; then
    echo "---> Starting worker ..."
    # shellcheck disable=SC2086
    exec uv run --directory qontract_api celery --app=qontract_api.tasks worker $CELERY_OPTS "$@"
else
    echo "unknow mode $START_MODE - use 'api' or 'worker' instead"
fi
