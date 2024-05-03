from collections.abc import Callable, Iterable, Mapping
from unittest.mock import create_autospec

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.vcs import VCS
from tools.saas_metrics_exporter.commit_distance.commit_distance import (
    CommitDistanceFetcher,
    CommitDistanceMetric,
)
from tools.saas_metrics_exporter.commit_distance.metrics import SaasCommitDistanceGauge


def test_commit_distance_no_saas_files() -> None:
    vcs = create_autospec(spec=VCS)
    commit_distance_fetcher = CommitDistanceFetcher(vcs=vcs)
    commit_distance_metrics = commit_distance_fetcher.fetch(
        saas_files=[], thread_pool_size=1
    )
    assert commit_distance_metrics == []


def test_commit_distance_no_channels(
    saas_files_builder: Callable[[Iterable[Mapping]], list[SaasFile]],
) -> None:
    saas_files = saas_files_builder([
        {
            "path": "/saas1.yml",
            "name": "saas_1",
            "resourceTemplates": [
                {
                    "name": "template_1",
                    "url": "repo1/url",
                    "targets": [
                        {
                            "ref": "main",
                            "namespace": {"path": "/namespace1.yml"},
                            "promotion": {
                                "publish": [],
                            },
                        }
                    ],
                }
            ],
        },
        {
            "path": "/saas2.yml",
            "name": "saas_2",
            "publishJobLogs": True,
            "resourceTemplates": [
                {
                    "name": "template_2",
                    "url": "repo2/url",
                    "targets": [
                        {
                            "ref": "main",
                            "namespace": {"path": "/namespace2.yml"},
                            "promotion": {
                                "subscribe": [],
                                "auto": True,
                            },
                        }
                    ],
                }
            ],
        },
    ])
    vcs = create_autospec(spec=VCS)
    commit_distance_fetcher = CommitDistanceFetcher(vcs=vcs)
    commit_distance_metrics = commit_distance_fetcher.fetch(
        saas_files=saas_files, thread_pool_size=1
    )
    assert commit_distance_metrics == []


def test_commit_distance_single_pub_sub_pair(
    saas_files_builder: Callable[[Iterable[Mapping]], list[SaasFile]],
) -> None:
    saas_files = saas_files_builder([
        {
            "path": "/saas1.yml",
            "name": "saas_1",
            "app": {
                "name": "APP",
            },
            "resourceTemplates": [
                {
                    "name": "template_1",
                    "url": "repo1/url",
                    "targets": [
                        {
                            "ref": "main",
                            "namespace": {
                                "path": "/namespace1.yml",
                                "name": "publisher_namespace",
                            },
                            "promotion": {
                                "publish": ["channel-a"],
                            },
                        },
                        {
                            "ref": "main",
                            "namespace": {"path": "/namespace1.yml"},
                            "promotion": {
                                "publish": [],
                            },
                        },
                    ],
                }
            ],
        },
        {
            "path": "/saas2.yml",
            "name": "saas_2",
            "app": {
                "name": "APP",
            },
            "publishJobLogs": True,
            "resourceTemplates": [
                {
                    "name": "template_2",
                    "url": "repo2/url",
                    "targets": [
                        {
                            "ref": "main",
                            "namespace": {
                                "path": "/namespace2.yml",
                                "name": "subscriber_namespace",
                            },
                            "promotion": {
                                "subscribe": ["channel-a"],
                            },
                        }
                    ],
                }
            ],
        },
        {
            "path": "/saas2.yml",
            "name": "saas_2",
            "publishJobLogs": True,
            "resourceTemplates": [
                {
                    "name": "template_2",
                    "url": "repo2/url",
                    "targets": [
                        {
                            "ref": "main",
                            "namespace": {"path": "/namespace2.yml"},
                            "promotion": {
                                "subscribe": [],
                            },
                        }
                    ],
                }
            ],
        },
    ])
    vcs = create_autospec(spec=VCS)
    commit_distance_fetcher = CommitDistanceFetcher(vcs=vcs)
    commit_distance_metrics = commit_distance_fetcher.fetch(
        saas_files=saas_files, thread_pool_size=1
    )
    assert commit_distance_metrics == [
        CommitDistanceMetric(
            value=0.0,
            metric=SaasCommitDistanceGauge(
                channel="channel-a",
                app="APP",
                publisher="NoName",
                publisher_namespace="publisher_namespace",
                subscriber="NoName",
                subscriber_namespace="subscriber_namespace",
            ),
        )
    ]
