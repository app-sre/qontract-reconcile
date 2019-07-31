from setuptools import find_packages
from setuptools import setup


setup(
    name="reconcile",
    version="0.1.0",
    license="BSD",

    author="Red Hat App-SRE Team",
    author_email="sd-app-sre@redhat.com",

    description="Collection of tools to reconcile services with their desired "
                "state as defined in the app-interface DB.",

    packages=find_packages(exclude=('tests',)),

    install_requires=[
        "Click>=7.0,<8.0",
        "graphqlclient>=0.2.4,<0.3.0",
        "toml>=0.10.0,<0.11.0",
        "jsonpath-rw>=1.4.0,<1.5.0",
        "PyGithub>=1.40,<1.41",
        "requests>=2.21.0,<2.22.0",
        "hvac>=0.7.0,<0.8.0",
        "ldap3>=2.5.2,<2.6.0",
        "anymarkup>=0.7.0,<0.8.0",
        "python-gitlab>=1.7.0,<1.8.0",
        "semver>=2.8.0,<2.9.0",
        "python-terraform>=0.10.0,<0.11.0",
        "jumpssh>=1.6.1,<1.7.0",
        "boto3>=1.9.0,<=1.10.0",
        "botocore>=1.12.159,<=1.13.0",
        "urllib3>=1.21.1,<1.25.0",
        "slackclient>=1.3.2,<1.4.0",
        "pypd>=1.1.0,<1.2.0",
        "jenkins-job-builder>=2.10.1,<2.11.0",
    ],

    test_suite="tests",

    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.6',
    ],
    entry_points={
        'console_scripts': [
            'qontract-reconcile = reconcile.cli:integration',
            'e2e-tests = e2e_tests.cli:test',
        ],
    },
)
