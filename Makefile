.PHONY: help build push rc build-test test-app test-container-image test clean

CONTAINER_ENGINE ?= $(shell which podman >/dev/null 2>&1 && echo podman || echo docker)
IMAGE_TEST := reconcile-test

IMAGE_NAME := quay.io/app-sre/qontract-reconcile
IMAGE_TAG := $(shell git rev-parse --short=7 HEAD)

DOCKER_EXEC_VAULT := docker exec vault /bin/sh -c
DEV_CONF := . ./dev/conf &&
APP_INTERFACE_PATH ?= $(shell pwd)/../../app-sre/app-interface
QONTRACT_SCHEMAS_PATH ?= $(shell pwd)/../qontract-schemas
QONTRACT_SERVER_PATH ?= $(shell pwd)/../qontract-server

ifneq (,$(wildcard $(CURDIR)/.docker))
	DOCKER_CONF := $(CURDIR)/.docker
else
	DOCKER_CONF := $(HOME)/.docker
endif

CTR_STRUCTURE_IMG := quay.io/app-sre/container-structure-test:latest

help: ## Prints help for targets with comments
	@grep -E '^[a-zA-Z0-9.\ _-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

build:
	@DOCKER_BUILDKIT=1 $(CONTAINER_ENGINE) build -t $(IMAGE_NAME):latest -f dockerfiles/Dockerfile . --progress=plain
	@$(CONTAINER_ENGINE) tag $(IMAGE_NAME):latest $(IMAGE_NAME):$(IMAGE_TAG)

push:
	@$(CONTAINER_ENGINE) --config=$(DOCKER_CONF) push $(IMAGE_NAME):latest
	@$(CONTAINER_ENGINE) --config=$(DOCKER_CONF) push $(IMAGE_NAME):$(IMAGE_TAG)

rc:
	@$(CONTAINER_ENGINE) build -t $(IMAGE_NAME):$(IMAGE_TAG)-rc -f dockerfiles/Dockerfile .
	@$(CONTAINER_ENGINE) --config=$(DOCKER_CONF) push $(IMAGE_NAME):$(IMAGE_TAG)-rc

generate:
	@helm lint helm/qontract-reconcile
	@helm template helm/qontract-reconcile -n qontract-reconcile -f helm/qontract-reconcile/values-external.yaml > openshift/qontract-reconcile.yaml
	@helm template helm/qontract-reconcile -n qontract-reconcile -f helm/qontract-reconcile/values-internal.yaml > openshift/qontract-reconcile-internal.yaml
	@helm template helm/qontract-reconcile -n qontract-reconcile -f helm/qontract-reconcile/values-fedramp.yaml > openshift/qontract-reconcile-fedramp.yaml

build-test:
	@$(CONTAINER_ENGINE) build -t $(IMAGE_TEST) -f dockerfiles/Dockerfile.test .

test-app: build-test ## Target to test app with tox on docker
	@$(CONTAINER_ENGINE) run --rm $(IMAGE_TEST)

test-container-image: build ## Target to test the final image
	@$(CONTAINER_ENGINE) run --rm \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v $(CURDIR):/work \
		 $(CTR_STRUCTURE_IMG) test \
		--config /work/dockerfiles/structure-test.yaml \
		-i $(IMAGE_NAME):$(IMAGE_TAG)

test: test-app test-container-image

dev-reconcile-loop: build ## Trigger the reconcile loop inside a container for an integration
	@$(CONTAINER_ENGINE) run --rm \
		--add-host=host.docker.internal:host-gateway \
		-v $(CURDIR):/work \
		-e INTEGRATION_NAME=$(INTEGRATION_NAME) \
		-e INTEGRATION_EXTRA_ARGS=$(INTEGRATION_EXTRA_ARGS) \
		-e SLEEP_DURATION_SECS=$(SLEEP_DURATION_SECS) \
		-e DRY_RUN=$(DRY_RUN) \
		-e CONFIG=/work/config.dev.toml \
		$(IMAGE_NAME):$(IMAGE_TAG)

dev-clean:
	$(DEV_CONF) docker-compose down

dev-bootstrap-vault:
	$(DEV_CONF) docker-compose up -d vault
	sleep 1
	@$(DOCKER_EXEC_VAULT) "vault secrets disable secret"
	@$(DOCKER_EXEC_VAULT) "vault secrets enable -version=1 -path=app-sre kv"
	@$(DOCKER_EXEC_VAULT) "vault auth enable approle"
# We need a dedicated policy because: hvac.exceptions.InvalidRequest: auth methods cannot create root tokens
	docker cp ./dev/local-vault-dev-policy.hcl vault:.
	@$(DOCKER_EXEC_VAULT) "vault policy write dev-policy local-vault-dev-policy.hcl"
	@$(DOCKER_EXEC_VAULT) "vault write auth/approle/role/dev-role role_id=dev-role bind_secret_id=false secret_id_bound_cidrs='0.0.0.0/0' token_policies=dev-policy"

dev-bootstrap-qontract-server:
	$(DEV_CONF) $(MAKE) -C $(QONTRACT_SERVER_PATH) bundle
	$(DEV_CONF) docker-compose up -d qontract-server

dev-bootstrap-stack: dev-clean dev-bootstrap-vault dev-bootstrap-qontract-server

dev-run-integration:
	$(DEV_CONf) docker-compose up qontract-reconcile

clean:
	@rm -rf .tox .eggs reconcile.egg-info build .pytest_cache
	@find . -name "__pycache__" -type d -print0 | xargs -0 rm -rf
	@find . -name "*.pyc" -delete
