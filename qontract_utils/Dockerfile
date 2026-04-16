FROM registry.access.redhat.com/ubi9/python-312-minimal@sha256:ecacdd63283ed3083ddd33c02ab5112d4dbf1fbf2508317bf4d4f6d7d913d2f1 AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a /uv /bin/uv

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

COPY qontract_utils/pyproject.toml ./
RUN uv sync --no-install-project

COPY qontract_utils/Makefile ./
COPY qontract_utils/tests ./tests
COPY qontract_utils/qontract_utils ./qontract_utils
RUN uv sync

#
# Test image
#
FROM base AS test

RUN make test
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
