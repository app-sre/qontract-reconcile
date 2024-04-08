#!/bin/bash

# We want jenkins to fail hard
set -e

DOCKER_CONF="$PWD/.docker"
mkdir -p "$DOCKER_CONF"
docker --config="$DOCKER_CONF" login -u="$QUAY_USER" -p="$QUAY_TOKEN" quay.io

# build images for commercial
make test build push

# and a fips version
make IMAGE_NAME=quay.io/app-sre/qontract-reconcile-fips BUILD_TARGET=fips-prod-image build push

make pypi-release
