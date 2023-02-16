#!/bin/bash

DOCKER_CONF="$PWD/.docker"
mkdir -p "$DOCKER_CONF"
PYPI_PUSH_IMAGE=quay.io/app-sre/qontract-reconcile-builder:0.3.8
docker --config="$DOCKER_CONF" login -u="$QUAY_USER" -p="$QUAY_TOKEN" quay.io

# build images
make test build push

# publish to pypi
docker run -e TWINE_USERNAME -e TWINE_PASSWORD -v $(pwd):/work --rm $PYPI_PUSH_IMAGE ./build_tag.sh
