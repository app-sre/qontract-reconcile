#!/bin/sh

set -o pipefail

while true; do
    qontract-reconcile --config /config/config.toml $DRY_RUN $INTEGRATION_NAME $INTEGRATION_EXTRA_ARGS 2>&1 | tee -a $LOG_FILE
    STATUS=$?

    if [ -n "${RUN_ONCE}" ]; then
        exit $STATUS
    fi

    if [ $STATUS -ne 3 ]; then
        [ $STATUS -ne 0 ] && exit $STATUS
        sleep ${SLEEP_DURATION_SECS}
    fi
done
