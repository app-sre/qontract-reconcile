#!/bin/bash

DOCKER_CONF="$PWD/.docker"
mkdir -p "$DOCKER_CONF"
docker --config="$DOCKER_CONF" login -u="$QUAY_USER" -p="$QUAY_TOKEN" quay.io

# build images
make build push

# publish to pypi
set -e

python3 -m pip install --user twine wheel
python3 setup.py bdist_wheel
python3 -m twine upload dist/*
