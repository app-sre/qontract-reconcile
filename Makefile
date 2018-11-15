.PHONY: build-test test clean

IMAGE_TEST := reconcile-test

build-test:
	@docker build -t $(IMAGE_TEST) -f dockerfiles/Dockerfile.test .

test: build-test
	@docker run --rm $(IMAGE_TEST)

clean:
	@rm -rf venv .tox .eggs reconcile.egg-info buid .pytest_cache
	@find . -name "__pycache__" -type d -print0 | xargs -0 rm -rf
	@find . -name "*.pyc" -delete
