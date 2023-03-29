#!/bin/bash

pip install -r /work/requirements/requirements-debugger.txt

DEBUGPY_PORT=${DEBUGPY_PORT:-5678}

# for backwards compatibility
if [[ -n "$QONTRACT_CLI_COMMAND" ]]; then
    if [ "$QONTRACT_CLI_COMMAND" == "app-interface-reporter" ]; then
        COMMAND="tools/app_interface_reporter.py"
        COMMAD_EXTRA_ARGS="--gitlab-project-id=app-interface --reports-path=/tmp/report"
    else
        COMMAND="${COMMAND:-tools/qontract_cli.py}"
        COMMAD_EXTRA_ARGS="$QONTRACT_CLI_COMMAND"
    fi
fi
COMMAND="${COMMAND:-dockerfiles/hack/run-integration.py}"
#/ for backwards compatibility

# set default options
if [ "$COMMAND" == "tools/qontract_cli.py" ]; then
    COMMAD_EXTRA_ARGS="--config ${CONFIG} ${COMMAD_EXTRA_ARGS}"
else
    COMMAD_EXTRA_ARGS="--config ${CONFIG} ${DRY_RUN} ${COMMAD_EXTRA_ARGS}"
fi

echo "Running command: $COMMAND $COMMAD_EXTRA_ARGS"
# adding /work to the command so we can it from the root of the repo
COMMAND="/work/$COMMAND"

if [ "$DEBUGGER" == "debugpy" ]; then
    echo "Using debugpy: Waiting for remote debugger session to connect to :$DEBUGPY_PORT ..."
    COMMAND="python3 -m debugpy --listen 0.0.0.0:$DEBUGPY_PORT --wait-for-client $COMMAND"
fi

# shellcheck disable=SC2086
$COMMAND $COMMAD_EXTRA_ARGS
