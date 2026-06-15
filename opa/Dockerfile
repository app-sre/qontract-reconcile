FROM registry.access.redhat.com/ubi10/ubi-minimal@sha256:2c20ac20ca1ecbbbd583603feabd9cc51e7e8ea5a82e5088e20a9494794b2574 AS base
COPY --from=openpolicyagent/opa:1.17.1-static /opa /opa

ENV PATH=${PATH}:/ \
    IS_TESTED_FLAG="/tmp/is_tested"

USER 1000:1000

COPY LICENSE /licenses/
COPY opa/authz /authz

#
# Test image
#
FROM base AS test
COPY --from=ghcr.io/styrainc/regal:0.35.1@sha256:7caf9953f1c49054c94030ec7be087b46ae501fc347cdaace9557a57abd3f4ff /ko-app/regal /bin/regal

USER 0
RUN microdnf install -y make
USER 1000:1000

COPY opa/Makefile /
RUN make -C / test
RUN touch ${IS_TESTED_FLAG}

#
# Prod image
#
FROM base AS prod
COPY --from=test ${IS_TESTED_FLAG} ${IS_TESTED_FLAG}

ENTRYPOINT ["/opa"]
CMD ["run"]
