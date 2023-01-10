from datetime import (
    datetime,
    timedelta,
)
from unittest.mock import patch

from gitlab import Gitlab

import reconcile.gitlab_housekeeping as gl_h
from reconcile.test.fixtures import Fixtures
from reconcile.utils.secret_reader import SecretReader

DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

fixture = Fixtures("gitlab_housekeeping").get_anymarkup("api.yml")


def get_mock(path, query_data=None, streamed=False, raw=False, **kwargs):
    path = path[1:]
    data = fixture.get("gitlab").get(path)
    return data


class TestGitLabHousekeeping:
    @staticmethod
    @patch.object(SecretReader, "read")
    @patch.object(Gitlab, "http_get")
    @patch.object(Gitlab, "http_post")
    def test_clean_pipelines_happy_path(http_post, http_get, secret_read):
        http_get.side_effect = get_mock
        now = datetime.utcnow()

        ten_minutes_ago = now - timedelta(minutes=10)
        two_hours_ago = now - timedelta(minutes=120)

        pipelines = [
            {
                "id": 46,
                "iid": 11,
                "project_id": 1,
                "status": "canceled",
                "ref": "new-pipeline",
                "sha": "dddd9c1e5c9015edee04321e423429d2f8924609",
                "web_url": "https://example.com/foo/bar/pipelines/46",
                "created_at": two_hours_ago.strftime(DATE_FORMAT),
                "updated_at": two_hours_ago.strftime(DATE_FORMAT),
            },
            {
                "id": 47,
                "iid": 12,
                "project_id": 1,
                "status": "pending",
                "ref": "new-pipeline",
                "sha": "a91957a858320c0e17f3a0eca7cfacbff50ea29a",
                "web_url": "https://example.com/foo/bar/pipelines/47",
                "created_at": two_hours_ago.strftime(DATE_FORMAT),
                "updated_at": two_hours_ago.strftime(DATE_FORMAT),
            },
            {
                "id": 48,
                "iid": 13,
                "project_id": 1,
                "status": "running",
                "ref": "new-pipeline",
                "sha": "eb94b618fb5865b26e80fdd8ae531b7a63ad851a",
                "web_url": "https://example.com/foo/bar/pipelines/48",
                "created_at": ten_minutes_ago.strftime(DATE_FORMAT),
                "updated_at": ten_minutes_ago.strftime(DATE_FORMAT),
            },
        ]
        instance = {"url": "http://localhost", "sslVerify": False, "token": "token"}

        dry_run = False
        timeout = 60

        timeout_pipelines = gl_h.get_timed_out_pipelines(pipelines, timeout)
        gl_h.clean_pipelines(dry_run, instance, "1", "", timeout_pipelines)

        # Test if mock have this exact calls
        http_post.assert_called_once_with("/projects/1/pipelines/47/cancel")


def test_calculate_time_since_approval():
    one_hour_ago = (datetime.utcnow() - timedelta(minutes=60)).strftime(DATE_FORMAT)

    time_since_merge = gl_h._calculate_time_since_approval(one_hour_ago)

    assert round(time_since_merge) == 60
