.PHONY: help build push rc build-test test-app test-container-image test clean

CONTAINER_ENGINE ?= $(shell which podman >/dev/null 2>&1 && echo podman || echo docker)
NETWORK_ARG ?= --add-host=host.docker.internal:host-gateway  ## for docker
ifeq ($(CONTAINER_ENGINE), podman)
  NETWORK_ARG = --network host  ## big hammer here, but just put it on the host network
endif

CONTAINER_UID ?= $(shell id -u)
IMAGE_TEST := reconcile-test

IMAGE_NAME := quay.io/app-sre/qontract-reconcile
COMMIT_AUTHOR_EMAIL := $(shell git show -s --format='%ae' HEAD)
COMMIT_SHA := $(shell git rev-parse HEAD)
IMAGE_TAG := $(shell git rev-parse --short=7 HEAD)
BUILD_TARGET := prod-image

.EXPORT_ALL_VARIABLES:
# TWINE_USERNAME & TWINE_PASSWORD are available in jenkins job
UV_PUBLISH_TOKEN = $(TWINE_PASSWORD)


LOG_LEVEL ?= 'DEBUG'
SLEEP_DURATION_SECS ?= 60

ifneq (,$(wildcard $(CURDIR)/.docker))
	DOCKER_CONF := $(CURDIR)/.docker
else
	DOCKER_CONF := $(HOME)/.docker
endif

CTR_STRUCTURE_IMG := quay.io/app-sre/container-structure-test:latest

help: ## Prints help for targets with comments
	@grep -E '^[a-zA-Z0-9.\ _-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

build:
	@DOCKER_BUILDKIT=1 $(CONTAINER_ENGINE) build -t $(IMAGE_NAME):latest -f dockerfiles/Dockerfile --target $(BUILD_TARGET) . --progress=plain
	@$(CONTAINER_ENGINE) tag $(IMAGE_NAME):latest $(IMAGE_NAME):$(IMAGE_TAG)

build-dev:
	@DOCKER_BUILDKIT=1 $(CONTAINER_ENGINE) build --progress=plain --build-arg CONTAINER_UID=$(CONTAINER_UID) -t $(IMAGE_NAME)-dev:latest -f dockerfiles/Dockerfile --target dev-image .

push:
	@$(CONTAINER_ENGINE) --config=$(DOCKER_CONF) push $(IMAGE_NAME):latest
	@$(CONTAINER_ENGINE) --config=$(DOCKER_CONF) push $(IMAGE_NAME):$(IMAGE_TAG)

rc:
	@$(CONTAINER_ENGINE) build -t $(IMAGE_NAME):$(IMAGE_TAG)-rc --build-arg quay_expiration=3d -f dockerfiles/Dockerfile --target prod-image .
	@$(CONTAINER_ENGINE) --config=$(DOCKER_CONF) push $(IMAGE_NAME):$(IMAGE_TAG)-rc

generate:
	@mkdir -p openshift
	@helm lint helm/qontract-reconcile
	@helm template helm/qontract-reconcile -n qontract-reconcile -f helm/qontract-reconcile/values-manager.yaml > openshift/qontract-manager.yaml
	@helm template helm/qontract-reconcile -n qontract-reconcile -f helm/qontract-reconcile/values-manager-fedramp.yaml > openshift/qontract-manager-fedramp.yaml

test-app: ## Target to test app in a container
	@$(CONTAINER_ENGINE) build --progress=plain -t $(IMAGE_TEST) -f dockerfiles/Dockerfile --target test-image .

print-host-versions:
	@$(CONTAINER_ENGINE) --version
	python3 --version

test-container-image: build ## Target to test the final image
	@CONTAINER_ENGINE=$(CONTAINER_ENGINE) \
	CTR_STRUCTURE_IMG=$(CTR_STRUCTURE_IMG) \
	CURDIR=$(CURDIR) \
	IMAGE_NAME=$(IMAGE_NAME) \
	IMAGE_TAG=$(IMAGE_TAG) \
	$(CURDIR)/run-test-container-image.sh

test: print-host-versions test-app test-container-image

dev-reconcile-loop: build-dev ## Trigger the reconcile loop inside a container for an integration
	@$(CONTAINER_ENGINE) run --rm -it \
		-v "$(CURDIR)":/work:Z \
		$(NETWORK_ARG) \
		-p 5678:5678 \
		-e INTEGRATION_NAME="$(INTEGRATION_NAME)" \
		-e INTEGRATION_EXTRA_ARGS="$(INTEGRATION_EXTRA_ARGS)" \
		-e SLEEP_DURATION_SECS="$(SLEEP_DURATION_SECS)" \
		-e APP_INTERFACE_STATE_BUCKET="$(APP_INTERFACE_STATE_BUCKET)" \
		-e APP_INTERFACE_STATE_BUCKET_ACCOUNT="$(APP_INTERFACE_STATE_BUCKET_ACCOUNT)" \
		-e gitlab_pr_submitter_queue_url="$(gitlab_pr_submitter_queue_url)" \
		-e LOG_LEVEL="$(LOG_LEVEL)" \
		-e DRY_RUN="$(DRY_RUN)" \
		-e DEBUGGER="$(DEBUGGER)" \
		-e CONFIG=/work/config.dev.toml \
		$(IMAGE_NAME)-dev:latest

clean: ## Clean up the local development environment
	@rm -rf .tox .eggs reconcile.egg-info build .pytest_cache venv .venv GIT_VERSION
	@find . -name "__pycache__" -type d -print0 | xargs -0 rm -rf
	@find . -name "*.pyc" -delete

pypi-release:
	@$(CONTAINER_ENGINE) build --progress=plain --build-arg TWINE_USERNAME --build-arg TWINE_PASSWORD --target pypi -f dockerfiles/Dockerfile .

pypi:
	uv build --sdist --wheel
	uv publish

dev-venv: clean ## Create a local venv for your IDE and remote debugging
	uv sync --python 3.11

print-files-modified-in-last-30-days:
	@git log --since '$(shell date --date='-30 day' +"%m/%d/%y")' --until '$(shell date +"%m/%d/%y")' --oneline --name-only --pretty=format: | sort | uniq | grep -E '.py$$'

format:
	@uv run ruff format
	@uv run ruff check

gql-introspection:
	# TODO: make url configurable
	@uv run qenerate introspection http://localhost:4000/graphql > reconcile/gql_definitions/introspection.json

gql-query-classes:
	@uv run qenerate code -i reconcile/gql_definitions/introspection.json reconcile/gql_definitions
	@find reconcile/gql_definitions -path '*/__pycache__' -prune -o -type d -exec touch "{}/__init__.py" \;

qenerate: gql-introspection gql-query-classes

localstack:
	@$(CONTAINER_ENGINE) compose -f dev/localstack/docker-compose.yml up

sqs:
	@AWS_ACCESS_KEY_ID=$(APP_INTERFACE_SQS_AWS_ACCESS_KEY_ID) \
	AWS_SECRET_ACCESS_KEY=$(APP_INTERFACE_SQS_AWS_SECRET_ACCESS_KEY) \
	AWS_REGION=$(APP_INTERFACE_SQS_AWS_REGION) \
	aws sqs send-message --queue-url $(APP_INTERFACE_SQS_QUEUE_URL) --message-body "{\"pr_type\": \"promote_qontract_reconcile\", \"version\": \"$(IMAGE_TAG)\", \"commit_sha\": \"$(COMMIT_SHA)\", \"author_email\": \"$(COMMIT_AUTHOR_EMAIL)\"}"

all-tests: linter-test types-test qenerate-test helm-test unittest

linter-test:
	uv run ruff check --no-fix
	uv run ruff format --check

types-test:
	uv run mypy

qenerate-test: gql-query-classes
	git diff --exit-code reconcile/gql_definitions

helm-test: generate
	git diff --exit-code helm openshift

unittest: ## Run unit tests
	uv run pytest --cov=reconcile --cov-report=term-missing --cov-report xml
