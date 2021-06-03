.PHONY: build push rc build-test test clean

IMAGE_TEST := reconcile-test

IMAGE_NAME := quay.io/app-sre/qontract-reconcile
IMAGE_TAG := $(shell git rev-parse --short=7 HEAD)

ifneq (,$(wildcard $(CURDIR)/.docker))
	DOCKER_CONF := $(CURDIR)/.docker
else
	DOCKER_CONF := $(HOME)/.docker
endif

build:
	@docker build -t $(IMAGE_NAME):latest -f dockerfiles/Dockerfile .
	@docker tag $(IMAGE_NAME):latest $(IMAGE_NAME):$(IMAGE_TAG)

push:
	@docker --config=$(DOCKER_CONF) push $(IMAGE_NAME):latest
	@docker --config=$(DOCKER_CONF) push $(IMAGE_NAME):$(IMAGE_TAG)

rc:
	@docker build -t $(IMAGE_NAME):$(IMAGE_TAG)-rc -f dockerfiles/Dockerfile .
	@docker --config=$(DOCKER_CONF) push $(IMAGE_NAME):$(IMAGE_TAG)-rc

generate:
	@helm3 lint helm/qontract-reconcile
	@helm3 template helm/qontract-reconcile -n qontract-reconcile -f helm/qontract-reconcile/values-external.yaml > openshift/qontract-reconcile.yaml
	@helm3 template helm/qontract-reconcile -n qontract-reconcile -f helm/qontract-reconcile/values-internal.yaml > openshift/qontract-reconcile-internal.yaml

build-test:
	@docker build -t $(IMAGE_TEST) -f dockerfiles/Dockerfile.test .

# test: build-test
# 	@docker run --rm $(IMAGE_TEST)

test:
	@env

clean:
	@rm -rf .tox .eggs reconcile.egg-info build .pytest_cache
	@find . -name "__pycache__" -type d -print0 | xargs -0 rm -rf
	@find . -name "*.pyc" -delete
