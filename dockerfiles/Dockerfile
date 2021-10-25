FROM quay.io/app-sre/qontract-reconcile-base:0.5.1

WORKDIR /reconcile

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY tools tools
COPY setup.py .

# setup.py install is not used because it will install pre-releases:
# https://github.com/pypa/setuptools/issues/855
RUN python3 -m pip install .

COPY dockerfiles/hack/run-integration.py /run-integration.py
CMD [ "/run-integration.py" ]
