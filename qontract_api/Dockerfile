#
# Base image with defaults for all stages
FROM registry.access.redhat.com/ubi10-minimal:10.2-1788137716@sha256:d801168f5e8b108586c27a4fd5c92e3c1e8d061084383713926e2ca61b8b6c64 AS base
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
FROM registry.access.redhat.com/ubi10/python-314-minimal:10.2-1788191076@sha256:1184f0930506ef3c5d2b6c34d3dee04f5cd82f6960db5ea182f7559763da144d AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /bin/uv

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
# Must use the builder image (python-314-minimal) rather than `base`
# (ubi10-minimal + /usr/bin/python3.14). UV_PROJECT_ENVIRONMENT is /opt/app-root;
# a different interpreter makes uv recreate that directory, which fails as
# UID 1001 with: failed to remove directory `/opt/app-root`: Permission denied.
FROM builder AS test

ENV \
    RUFF_CACHE_DIR=/tmp/.ruff_cache \
    TESTFLAG=/tmp/.tests_passed

USER root
RUN microdnf install -y make diffutils && microdnf clean all
USER 1001

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
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /bin/uv

EXPOSE 5678
RUN uv pip install debugpy watchdog
