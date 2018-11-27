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
        "Click==7.0",
        "graphqlclient==0.2.4",
        "toml==0.10.0",
        "jsonpath-rw==1.4.0",
        "PyGithub==1.40",
        "requests==2.19.1"
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
            'reconcile = reconcile.cli:main',
        ],
    },
)
