#!/bin/bash

pip install -r /work/requirements/requirements-debugger.txt

if [ "$DEBUGGER" == "debugpy" ] && [[ -z "$QONTRACT_CLI_COMMAND" ]]; then
    echo 'Using debugpy: Waiting for remote debugger session to connect ..'
    python3 -m debugpy --listen 0.0.0.0:5678 --wait-for-client /work/dockerfiles/hack/run-integration.py
elif [[ -z "$QONTRACT_CLI_COMMAND" ]]; then
    # No debugger configured
    /work/dockerfiles/hack/run-integration.py
elif [ "$DEBUGGER" == "debugpy" ]; then
    echo 'Using debugpy: Waiting for remote debugger session to connect ..'
    python3 -m debugpy --listen 0.0.0.0:5678 --wait-for-client /work/tools/qontract_cli.py --config ${CONFIG} ${QONTRACT_CLI_COMMAND}
else
    # No debugger configured
    python3 /work/tools/qontract_cli.py --config ${CONFIG} ${QONTRACT_CLI_COMMAND}
fi
