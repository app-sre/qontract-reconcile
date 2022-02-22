.PHONY: help build push rc build-test test-app test-container-image test clean

CONTAINER_ENGINE ?= $(shell which podman >/dev/null 2>&1 && echo podman || echo docker)
IMAGE_TEST := reconcile-test

IMAGE_NAME := quay.io/app-sre/qontract-reconcile
IMAGE_TAG := $(shell git rev-parse --short=7 HEAD)

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

build-dev:
	@DOCKER_BUILDKIT=1 $(CONTAINER_ENGINE) build --build-arg CONTAINER_UID=${UID} -t $(IMAGE_NAME)-dev:latest -f dockerfiles/Dockerfile.dev .

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

dev-reconcile-loop: build-dev ## Trigger the reconcile loop inside a container for an integration
	@$(CONTAINER_ENGINE) run --rm -it \
		--add-host=host.docker.internal:host-gateway \
		-v $(CURDIR):/work \
		-p 5678:5678 \
		-e INTEGRATION_NAME=$(INTEGRATION_NAME) \
		-e INTEGRATION_EXTRA_ARGS=$(INTEGRATION_EXTRA_ARGS) \
		-e SLEEP_DURATION_SECS=$(SLEEP_DURATION_SECS) \
		-e DRY_RUN=$(DRY_RUN) \
		-e DEBUGGER=$(DEBUGGER) \
		-e CONFIG=/work/config.dev.toml \
		$(IMAGE_NAME)-dev:latest

clean:
	@rm -rf .tox .eggs reconcile.egg-info build .pytest_cache venv
	@find . -name "__pycache__" -type d -print0 | xargs -0 rm -rf
	@find . -name "*.pyc" -delete

dev-venv: clean ## Create a local venv for your IDE and remote debugging
	python3.9 -m venv venv
	. ./venv/bin/activate && pip install --upgrade pip
	. ./venv/bin/activate && pip install -e .
	. ./venv/bin/activate && pip install -r requirements-debugger.txt
	. ./venv/bin/activate && pip install -r requirements-test.txt
