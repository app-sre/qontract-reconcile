from unittest.mock import Mock, call

from datetime import datetime, timedelta

from gitlab.v4.objects import Project, ProjectPipelineManager

import reconcile.gitlab_housekeeping as gl_h

DATE_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'


class TestGitLabHousekeeping:
    @staticmethod
    def test_clean_pipelines_happy_path():
        now = datetime.now()

        ten_minutes_ago = now - timedelta(minutes=10)
        two_hours_ago = now - timedelta(minutes=120)

        pipelines = [
            {
                'id': 46,
                'iid': 11,
                'project_id': 1,
                'status': 'canceled',
                'ref': 'new-pipeline',
                'sha': 'dddd9c1e5c9015edee04321e423429d2f8924609',
                'web_url': 'https://example.com/foo/bar/pipelines/46',
                'created_at': two_hours_ago.strftime(DATE_FORMAT),
                'updated_at': two_hours_ago.strftime(DATE_FORMAT)
            },
            {
                'id': 47,
                'iid': 12,
                'project_id': 1,
                'status': 'pending',
                'ref': 'new-pipeline',
                'sha': 'a91957a858320c0e17f3a0eca7cfacbff50ea29a',
                'web_url': 'https://example.com/foo/bar/pipelines/47',
                'created_at': two_hours_ago.strftime(DATE_FORMAT),
                'updated_at': two_hours_ago.strftime(DATE_FORMAT)
            },
            {
                'id': 48,
                'iid': 13,
                'project_id': 1,
                'status': 'running',
                'ref': 'new-pipeline',
                'sha': 'eb94b618fb5865b26e80fdd8ae531b7a63ad851a',
                'web_url': 'https://example.com/foo/bar/pipelines/48',
                'created_at': ten_minutes_ago.strftime(DATE_FORMAT),
                'updated_at': ten_minutes_ago.strftime(DATE_FORMAT)
            },
        ]

        dry_run = False
        timeout = 60
        gl_project_mock = Mock(spec=Project)
        gl_project_mock.pipelines = Mock(spec=ProjectPipelineManager)

        gl_h.clean_pipelines(dry_run, gl_project_mock, pipelines, timeout)

        # Test if mock have this exact calls
        kall = call(47).cancel()
        assert gl_project_mock.pipelines.get.mock_calls == kall.call_list()
