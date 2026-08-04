#
# Base image with defaults for all stages
FROM registry.access.redhat.com/ubi10-minimal:10.2-1785778687@sha256:f0ed153f25c9a3df530ccf2c49ec04430efef206083cbbc16ca76a866ef096b5 AS base

COPY LICENSE /licenses/

ENV APP_ROOT=/opt/app-root
ENV \
    # use venv from ubi image
    UV_PROJECT_ENVIRONMENT=${APP_ROOT} \
    # compile bytecode for faster startup
    UV_COMPILE_BYTECODE="true" \
    # disable uv cache. it doesn't make sense in a container
    UV_NO_CACHE=true \
    RUFF_CACHE_DIR=/tmp/.ruff_cache \
    # bypass dynamic versioning (git not available)
    UV_DYNAMIC_VERSIONING_BYPASS="0.1.0" \
    PYTHONUNBUFFERED=1 \
    BASH_ENV="${APP_ROOT}/bin/activate" \
    ENV="${APP_ROOT}/bin/activate" \
    PROMPT_COMMAND=". ${APP_ROOT}/bin/activate" \
    # internal CA bundle path
    REQUESTS_CA_BUNDLE=/etc/pki/tls/cert.pem \
    SSL_CERT_FILE=/etc/pki/tls/cert.pem \
    TESTFLAG=/tmp/.tests_passed

COPY --from=quay.io/redhat-services-prod/app-sre-tenant/container-images-int-master/internal-redhat-ca-master@sha256:889c023a24b52ab735f030202fefc70191417082c3e9f8108ab66db8581ca2dd /etc/pki/ /etc/pki/

# Install base dependencies
RUN microdnf install -y python3.14 make && microdnf clean all
USER 1001

WORKDIR ${APP_ROOT}/src


#
# Builder image
#
FROM registry.access.redhat.com/ubi10/python-314-minimal:10.2-1785806386@sha256:d907e1e16ec2aa81ef53e12e751af3ecc96ec0f9d08df0f6c757e6c95fe20198 AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded /uv /bin/uv

ENV APP_ROOT=/opt/app-root
ENV \
    # use venv from ubi image
    UV_PROJECT_ENVIRONMENT=${APP_ROOT} \
    # compile bytecode for faster startup
    UV_COMPILE_BYTECODE="true" \
    # disable uv cache. it doesn't make sense in a container
    UV_NO_CACHE=true \
    # bypass dynamic versioning (git not available)
    UV_DYNAMIC_VERSIONING_BYPASS="0.1.0"

COPY --chown=1001:root qontract_api qontract_api
COPY --chown=1001:root qontract_api_client qontract_api_client
COPY --chown=1001:root qontract_utils qontract_utils
# TODO move qontract-reconcile dependency to a new dedicated reconcile/pyproject.toml
COPY --chown=1001:root README.md pyproject.toml uv.lock ./

RUN cd qontract_api && uv sync --frozen --no-group dev


#
# Test image
#
FROM base AS test
COPY --from=ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded /uv /bin/uv

USER root
# install dependencies
RUN microdnf install -y diffutils && microdnf clean all
USER 1001

COPY --from=builder /opt/app-root /opt/app-root
RUN cd qontract_api && uv sync --frozen
RUN make -C qontract_api test
RUN echo "true" > $TESTFLAG

#
# Production image
#
FROM base AS prod
COPY --from=builder /opt/app-root /opt/app-root

COPY qontract_api/app.sh ./
EXPOSE 8000
ENTRYPOINT [ "./app.sh" ]

#
# Release image
#
FROM prod AS prod-image
# Ensure tests have passed before allowing prod image to be built
COPY --from=test $TESTFLAG $TESTFLAG

#
# Dev image with debugpy
#
FROM prod AS debug
COPY --from=ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded /uv /bin/uv

EXPOSE 5678
RUN uv pip install debugpy watchdog
