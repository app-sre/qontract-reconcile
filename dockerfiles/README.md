## Qontract Reconcile Dockerfiles

### Stages

This is a multi-stage Dockerfile. The Dockerfile is used to build the qontract-reconcile
image used to run the qontract-reconcile CLI application.

The Dockerfile has 4 build stages:

```
build-image
dev-image
prod-image
fips-prod-image
```

#### Stage 1 - build-image

Builder image for qontract-reconcile

The base image `qontract-reconcile-builder` is used to build the application.
This image uses `qontract-reconcile-base` as the base image. 

This [base image](https://github.com/app-sre/container-images/tree/master/qontract-reconcile-builder) installs the necessary packages and sets up the environment for the application to run.

#### Stage 2 - dev-image

The [base image](https://github.com/app-sre/container-images/tree/master/qontract-reconcile-base) `qontract-reconcile-base` is used. This image has 2 build stages, the first labeled downloader that
uses `registry.access.redhat.com/ubi8/ubi:8.8` as the base image. The second build stage
uses the base image `registry.access.redhat.com/ubi9/ubi-minimal:9.3`.

This stage copies the `/work` directory from the `build-image` stage and sets
up the environment for development.

#### Stage 3 - prod-image 

The [base image](https://github.com/app-sre/container-images/tree/master/qontract-reconcile-base) `qontract-reconcile-base` is used.

This stage copies the `/work` directory from the `build-image` stage.

#### Stage 4 - fips-prod-image

The base image `prod-image` is used.

This stage uses the external image `qontract-reconcile-oc` to copy a specific `oc` version into the Qontract Reconcile image for use in FIPS environments.

### ENTRYPOINT and CMD

The ENTRYPOINT for the Dockerfile is the script [run.sh](../dev/run.sh) which is included from
the 2nd build stage labed dev-image.

The `ENTRYPOINT` is set to `/work/run.sh` and is passed the script [run-integration.py](../hack/run-integration.py)
as the `CMD` in the 3rd build stage labeled prod-image.

### Testing

The [Makefile](../Makefile) has the target `test` that runs the tests for the 
qontract reconcile:

```
test: test-app test-container-image
```

The relationship for the targets is as follows:


                +------+
                | test |
                +------+
                 /   \
                v     v
      +----------+ +----------------------+
      | test-app | | test-container-image |
      +----------+ +----------------------+
           |                 |
           |                 |
           v                 |
     +------------+          | 
     | build-test |          |
     +------------+          v
                        +---------+  
                        |  build  |
                        +---------+


The Dockerfile [Dockerfile.test](Dockerfile.test) is called by the make target
`build-test` to test the image.

The target `test-container-image` builds the image and runs structure tests to test
the images structure: 

```Makefile
test-container-image: build ## Target to test the final image
	@$(CONTAINER_ENGINE) run --rm \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v $(CURDIR):/work \
		 $(CTR_STRUCTURE_IMG) test \
		--config /work/dockerfiles/structure-test.yaml \
		-i $(IMAGE_NAME):$(IMAGE_TAG)
```

`test-app` builds the image for testing with tox:

```Makefile
test-app: build-test ## Target to test app with tox on docker
	@$(CONTAINER_ENGINE) run --rm $(IMAGE_TEST)
```

`build-test` uses the image `qontract-reconcile-builder`, installs the necessary packages
and runs the tox tests

```Makefile
build-test:
	@$(CONTAINER_ENGINE) build -t $(IMAGE_TEST) -f dockerfiles/Dockerfile.test .
```
