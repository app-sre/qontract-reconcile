# Qontract Reconcile Dockerfiles

## Stages

This is a multi-stage Dockerfile. The Dockerfile is used to build the qontract-reconcile
image used to run the qontract-reconcile CLI application.

### Stage 1 - build-image

Builder image for qontract-reconcile

The base image `qontract-reconcile-builder` is used to build the application.
This image uses `qontract-reconcile-base` as the base image.

This [base image](https://github.com/app-sre/container-images/tree/master/qontract-reconcile-builder) installs the necessary packages and sets up the environment for the application to run.

### Stage 2 - dev-image

The [base image](https://github.com/app-sre/container-images/tree/master/qontract-reconcile-base) `qontract-reconcile-base` is used. This image has 2 build stages, the first labeled downloader that
uses `registry.access.redhat.com/ubi8/ubi:8.8` as the base image. The second build stage
uses the base image `registry.access.redhat.com/ubi9/ubi-minimal:9.3`.

This stage copies the `/work` directory from the `build-image` stage and sets
up the environment for development.

### Stage 3 - prod-image

The [base image](https://github.com/app-sre/container-images/tree/master/qontract-reconcile-base) `qontract-reconcile-base` is used.

This stage copies the `/work` directory from the `build-image` stage.

### Stage 4 - fips-prod-image

The base image `prod-image` is used.

This stage uses the external image `qontract-reconcile-oc` to copy a specific `oc` version into the Qontract Reconcile image for use in FIPS environments.

### Stage 5 - test-image

This stage uses the `prod-image` as the base image, adds all required packages for testing and runs the tests.

> Note: The stage needs access to the `.git` directory!

### Stage 6 - pypi

This stage builds and publishes the `qontract-reconcile` package to the PyPi repository.

> Note: The stage needs access to the `.git` directory because the `qontract-reconcile` package version is determined by the git tag.

## ENTRYPOINT and CMD

The ENTRYPOINT for the Dockerfile is the script [run.sh](../dev/run.sh) which is included from
the 2nd build stage labed dev-image.

The `ENTRYPOINT` is set to `/work/run.sh` and is passed the script [run-integration](../reconcile/run_integration.py)
as the `CMD` in the 3rd build stage labeled prod-image.

## Testing

The [Makefile](../Makefile) has the target `test` that runs the tests for the
qontract reconcile.
