#!/bin/bash

pip install -r /work/requirements-debugger.txt

if [ "$DEBUGGER" == "debugpy" ]
then
    echo 'Using debugpy: Waiting for remote debugger session to connect ..'
    python3 -m debugpy --listen 0.0.0.0:5678 --wait-for-client /work/dockerfiles/hack/run-integration.py
else
    # No debugger configured
    /work/dockerfiles/hack/run-integration.py
fi
