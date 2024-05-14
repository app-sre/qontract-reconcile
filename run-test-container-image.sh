#!/bin/bash

# Podman support for container-structure-test (CST) is poor.
# See https://github.com/GoogleContainerTools/container-structure-test/issues/271
# This script will try to overcome this running CST using a local binary if it exists or
# use docker to run it from a container if it doesn't.
# There are a few cases to consider:
#
## CST binary exists and version matches
### if engine is docker just run it
### if engine is podman, in Linux we have an easy workaround using podman.sock, not well supported in Mac.
## CST does not exist, we need to run it using the CTR_STRUCTURE_IMG
### if engine is docker, we can run it mounting /var/run/docker.sock
### if engine is podman, we don't support it yet.

# Check variables
CHECK_VARS=0
for VAR in CONTAINER_ENGINE \
           IMAGE_NAME \
           IMAGE_TAG \
           CTR_STRUCTURE_IMG \
           CURDIR; do
    if [ -z ${!VAR:-} ]; then
        echo "$VAR not set"
        CHECK_VARS=1
    fi
done

[ $CHECK_VARS = 1 ] && exit 1

set -euo pipefail

which container-structure-test && CST=$(which container-structure-test) || CST=""
CST_VERSION="v1.17.0"
CST_TEST_FILE=$CURDIR/dockerfiles/structure-test.yaml
PLATFORM=$(uname)

check_cst_binary() {
    [ -x "$CST" ] && [ "$($CST version)" == "$CST_VERSION" ] && return 0 || return 1
}

check_podman_socket_running() {
    local rc
    systemctl --user status podman.socket > /dev/null 2>&1 && rc=0 || rc=1
    echo $rc
}

wait_for_podman_socket() {
    local retry=0
    local max_retries=5
    local rc
    rc=$(check_podman_socket_running)
    while [ "$rc" != 0 ] && [ $retry -le $max_retries ]; do
        retry=$((retry + 1))
        sleep $((retry * 1))
    rc=$(check_podman_socket_running)
    done

    echo "$rc"
}

# For Podman socket activation see
# https://github.com/containers/podman/blob/main/docs/tutorials/socket_activation.md
run_cst_using_binary() {
    if [ "$CONTAINER_ENGINE" = "podman" ]; then
        if [ "$PLATFORM" = "Linux" ]; then
            [ "$(check_podman_socket_running)" -eq 0 ] || systemctl --user start podman.socket
            if [ "$(wait_for_podman_socket)" = 0 ]; then
                export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"
            else
                echo "Failed starting podman.socket service"
                return 1
            fi
        else
            echo "Unsupported $PLATFORM system to use $CST binary."
            return 1
        fi
    fi

    $CST test --config "$CST_TEST_FILE" -i "$IMAGE_NAME:$IMAGE_TAG"
}

run_cst_using_container() {
    if [ "$CONTAINER_ENGINE" = "docker" ]; then
        $CONTAINER_ENGINE run --rm \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v "$CURDIR:/work" \
            "$CTR_STRUCTURE_IMG" test \
            --config /work/dockerfiles/structure-test.yaml \
            -i "$IMAGE_NAME:$IMAGE_TAG"
    else
        echo "Unsupported $CONTAINER_ENGINE to run container structure tests"
        return 1
    fi
}

main() {
    check_cst_binary && run_cst_using_binary || run_cst_using_container
}

if [ "${BASH_SOURCE[0]}" == "$0" ]; then
  main
fi
