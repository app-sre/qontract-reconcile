from setuptools import find_packages
from setuptools import setup
from glob import glob


setup(
    name="reconcile",
    version="0.2.2",
    license="Apache License 2.0",

    author="Red Hat App-SRE Team",
    author_email="sd-app-sre@redhat.com",

    description="Collection of tools to reconcile services with their desired "
                "state as defined in the app-interface DB.",

    packages=find_packages(exclude=('tests',)),

    data_files=[('templates', glob('templates/*.j2'))],

    install_requires=[
        "sretoolbox==0.6.0",
        "Click>=7.0,<8.0",
        "graphqlclient>=0.2.4,<0.3.0",
        "toml>=0.10.0,<0.11.0",
        "jsonpath-rw>=1.4.0,<1.5.0",
        "PyGithub>=1.47,<1.48",
        "hvac>=0.7.0,<0.8.0",
        "ldap3>=2.5.2,<2.6.0",
        "anymarkup>=0.7.0,<0.8.0",
        "python-gitlab>=1.11.0,<1.12.0",
        "semver>=2.8.0,<2.9.0",
        "python-terraform>=0.10.0,<0.11.0",
        "boto3>=1.9.0,<=1.10.0",
        "botocore>=1.12.159,<=1.13.0",
        "urllib3>=1.21.1,<1.25.0",
        "slackclient>=1.3.2,<1.4.0",
        "pypd>=1.1.0,<1.2.0",
        "jenkins-job-builder>=2.10.1,<2.11.0",
        "Jinja2>=2.10.1,<2.11.0",
        "jira>=2.0.0,<2.1.0",
        "pyOpenSSL>=19.0.0,<20.0.0",
        "ruamel.yaml>=0.16.5,<0.17.0",
        "terrascript>=0.6.1,<0.7.0",
        "tabulate>=0.8.6,<0.9.0",
        "UnleashClient>=3.4.2,<3.5.0",
        "prometheus-client~=0.8",
        "sentry-sdk~=0.14",
        "jenkins-job-builder==2.10.1",
        "tzlocal==2.1",
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
