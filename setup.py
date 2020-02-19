from setuptools import find_packages
from setuptools import setup


setup(
    name="reconcile",
    version="0.2.2",
    license="BSD",

    author="Red Hat App-SRE Team",
    author_email="sd-app-sre@redhat.com",

    description="Collection of tools to reconcile services with their desired "
                "state as defined in the app-interface DB.",

    packages=find_packages(exclude=('tests',)),

    install_requires=[
        "anymarkup~=0.7",
        "boto3~=1.9",
        "Click~=7.0",
        "graphqlclient~=0.2",
        "hvac~=0.7",
        "jenkins-job-builder~=2.10",
        "Jinja2~=2.10",
        "jira~=2.0",
        "jsonpath-rw~=1.4",
        "ldap3~=2.5",
        "PyGithub~=1.40",
        "pyOpenSSL~=19.0",
        "pypd~=1.1",
        "python-gitlab~=1.11",
        "python-terraform~=0.10",
        "ruamel.yaml~=0.16",
        "semver~=2.8",
        "slackclient~=1.3",
        "sretoolbox~=0.1",
        "tabulate~=0.8",
        "terrascript~=0.6",
        "toml~=0.10",
        "urllib3~=1.21",
    ],

    test_suite="tests",

    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
    ],
    entry_points={
        'console_scripts': [
            'qontract-reconcile = reconcile.cli:integration',
            'e2e-tests = e2e_tests.cli:test',
            'app-interface-reporter = tools.app_interface_reporter:main',
            'qontract-cli = tools.qontract_cli:root',
        ],
    },
)
