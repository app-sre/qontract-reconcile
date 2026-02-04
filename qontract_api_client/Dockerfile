FROM registry.access.redhat.com/ubi9/python-312-minimal@sha256:ecacdd63283ed3083ddd33c02ab5112d4dbf1fbf2508317bf4d4f6d7d913d2f1 AS base
COPY --from=ghcr.io/astral-sh/uv:0.9.26@sha256:9a23023be68b2ed09750ae636228e903a54a05ea56ed03a934d00fe9fbeded4b /uv /bin/uv

COPY LICENSE /licenses/

ENV \
    # use venv from ubi image
    UV_PROJECT_ENVIRONMENT=${APP_ROOT} \
    # unbuffered output for easier logging
    PYTHONUNBUFFERED=1 \
    # use venv from ubi image
    UV_PROJECT_ENVIRONMENT=$APP_ROOT \
    # disable uv cache. it doesn't make sense in a container
    UV_NO_CACHE=true \
    RUFF_CACHE_DIR=/tmp/.ruff_cache \
    TESTFLAG=/tmp/.tests_passed

USER root
# install dependencies
RUN microdnf install -y make && microdnf clean all
USER 1001

WORKDIR ${APP_ROOT}/src

COPY qontract_api_client/README.md ./
COPY qontract_api_client/pyproject.toml ./
RUN uv sync --no-install-project

COPY qontract_api_client/openapi_python_client_templates ./openapi_python_client_templates
COPY qontract_api_client/Makefile ./
COPY qontract_api_client/tests ./tests
COPY qontract_api_client/qontract_api_client ./qontract_api_client
RUN uv sync

#
# Test image
#
FROM base AS test

USER root
# install dependencies
RUN microdnf install -y diffutils && microdnf clean all
USER 1001

COPY qontract_api/openapi.json ./openapi.json

RUN make test OPENAPI=./openapi.json
RUN echo "true" > $TESTFLAG

#
# PyPI publish image
#
FROM test AS pypi
# Ensure tests have passed before allowing prod image to be built
COPY --from=test $TESTFLAG $TESTFLAG

# Secrets are owned by root and are not readable by others :(
USER root
RUN --mount=type=secret,id=app-sre-pypi-credentials/token UV_PUBLISH_TOKEN=$(cat /run/secrets/app-sre-pypi-credentials/token) make pypi
USER 1001
