from typing import Any
from unittest.mock import patch

import pytest

from reconcile.test.utils.jobcontroller.conftest import OCItemSetter
from reconcile.test.utils.jobcontroller.fixtures import (
    SomeJob,
    build_job_resource,
    build_job_status,
)
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobConcurrencyPolicy, JobStatus

#
# enqueue_job
#


def test_controller_enqueue_new_job(controller: K8sJobController) -> None:
    job = SomeJob(identifying_attribute="some-id")
    assert controller.enqueue_job(job)


@pytest.mark.parametrize(
    "concurrency_policy, delete_expected, create_expected",
    [
        (JobConcurrencyPolicy.NO_REPLACE, False, False),
        (JobConcurrencyPolicy.REPLACE_FAILED, False, False),
        (JobConcurrencyPolicy.REPLACE_IN_PROGRESS, True, True),
        (JobConcurrencyPolicy.REPLACE_FINISHED, False, False),
        (
            JobConcurrencyPolicy.REPLACE_IN_PROGRESS
            | JobConcurrencyPolicy.REPLACE_FINISHED,
            True,
            True,
        ),
    ],
)
def test_controller_enqueue_job_in_progress_job_exists(
    concurrency_policy: JobConcurrencyPolicy,
    delete_expected: bool,
    create_expected: bool,
    controller: K8sJobController,
    set_oc_get_items_side_effect: OCItemSetter,
) -> None:
    job = SomeJob(identifying_attribute="some-id")
    set_oc_get_items_side_effect([
        [build_job_resource(job, build_job_status(active=1))],
    ])
    with patch.object(controller, "delete_job") as mock_delete_job:
        assert create_expected == controller.enqueue_job(
            job=job, concurrency_policy=concurrency_policy
        )
        assert mock_delete_job.call_count == int(delete_expected)


@pytest.mark.parametrize(
    "concurrency_policy, delete_expected, create_expected",
    [
        (JobConcurrencyPolicy.NO_REPLACE, False, False),
        (JobConcurrencyPolicy.REPLACE_FAILED, False, False),
        (JobConcurrencyPolicy.REPLACE_IN_PROGRESS, False, False),
        (JobConcurrencyPolicy.REPLACE_FINISHED, True, True),
        (
            JobConcurrencyPolicy.REPLACE_FINISHED
            | JobConcurrencyPolicy.REPLACE_IN_PROGRESS,
            True,
            True,
        ),
    ],
)
def test_controller_enqueue_job_finished_job_exists(
    concurrency_policy: JobConcurrencyPolicy,
    delete_expected: bool,
    create_expected: bool,
    controller: K8sJobController,
    set_oc_get_items_side_effect: OCItemSetter,
) -> None:
    job = SomeJob(identifying_attribute="some-id", description="some-description")
    set_oc_get_items_side_effect([
        [build_job_resource(job, build_job_status(succeeded=1))],
    ])
    with patch.object(controller, "delete_job") as mock_delete_job:
        assert create_expected == controller.enqueue_job(
            job=job, concurrency_policy=concurrency_policy
        )
        assert mock_delete_job.call_count == int(delete_expected)


@pytest.mark.parametrize(
    "concurrency_policy, delete_expected, create_expected",
    [
        (JobConcurrencyPolicy.NO_REPLACE, False, False),
        (JobConcurrencyPolicy.REPLACE_FAILED, True, True),
        (JobConcurrencyPolicy.REPLACE_IN_PROGRESS, False, False),
        (JobConcurrencyPolicy.REPLACE_FINISHED, False, False),
        (
            JobConcurrencyPolicy.REPLACE_FAILED
            | JobConcurrencyPolicy.REPLACE_IN_PROGRESS,
            True,
            True,
        ),
    ],
)
def test_controller_enqueue_job_failed_job_exists(
    concurrency_policy: JobConcurrencyPolicy,
    delete_expected: bool,
    create_expected: bool,
    controller: K8sJobController,
    set_oc_get_items_side_effect: OCItemSetter,
) -> None:
    job = SomeJob(identifying_attribute="some-id", description="some-description")
    set_oc_get_items_side_effect([
        [build_job_resource(job, build_job_status(failed=1))],
    ])
    with patch.object(controller, "delete_job") as mock_delete_job:
        assert create_expected == controller.enqueue_job(
            job=job, concurrency_policy=concurrency_policy
        )
        assert mock_delete_job.call_count == int(delete_expected)


#
# wait_for_job_completion
#


@pytest.mark.parametrize(
    "status, timeout, expected",
    [
        (build_job_status(succeeded=1), 100, True),
        (build_job_status(failed=1), 100, False),
        (build_job_status(succeeded=1), -1, True),
    ],
)
def test_controller_wait_for_completion(
    status: dict[str, Any],
    timeout: int,
    expected: bool,
    controller: K8sJobController,
    set_oc_get_items_side_effect: OCItemSetter,
) -> None:
    job = SomeJob(identifying_attribute="some-id", description="some-description")
    set_oc_get_items_side_effect([
        [build_job_resource(job, build_job_status(active=1))],  # 0 seconds
        [build_job_resource(job, build_job_status(active=1))],  # 5 seconds
        [build_job_resource(job, status)],  # 10 seconds
    ])
    assert (
        controller.wait_for_job_completion(
            job.name(), check_interval_seconds=5, timeout_seconds=timeout
        )
        == expected
    )
    assert controller.time_module.time() == 10


def test_controller_wait_for_completion_instant(
    controller: K8sJobController, set_oc_get_items_side_effect: OCItemSetter
) -> None:
    job = SomeJob(identifying_attribute="some-id", description="some-description")
    set_oc_get_items_side_effect([
        [build_job_resource(job, build_job_status(succeeded=1))],  # 0 seconds
    ])

    assert controller.wait_for_job_completion(
        job.name(), check_interval_seconds=5, timeout_seconds=0
    )
    assert controller.time_module.time() == 0


def test_controller_wait_for_completion_timeout(
    controller: K8sJobController, set_oc_get_items_side_effect: OCItemSetter
) -> None:
    job = SomeJob(identifying_attribute="some-id", description="some-description")
    set_oc_get_items_side_effect([
        [build_job_resource(job, build_job_status(active=1))],  # 0 seconds
        [build_job_resource(job, build_job_status(active=1))],  # 5 seconds
        [build_job_resource(job, build_job_status(active=1))],  # 10 seconds
    ])

    with pytest.raises(TimeoutError):
        controller.wait_for_job_completion(
            job.name(), check_interval_seconds=5, timeout_seconds=4
        )


#
# wait_for_job_list_completion
#


def test_controller_wait_for_job_list_completion(
    controller: K8sJobController, set_oc_get_items_side_effect: OCItemSetter
) -> None:
    job1 = SomeJob(identifying_attribute="some-id-1", description="some-description")
    job2 = SomeJob(identifying_attribute="some-id-2", description="some-description")
    set_oc_get_items_side_effect([
        # 0 seconds
        [
            build_job_resource(job1, build_job_status(active=1)),
            build_job_resource(job2, build_job_status(active=1)),
        ],
        # 5 seconds
        [
            build_job_resource(job1, build_job_status(succeeded=1)),
            build_job_resource(job2, build_job_status(succeeded=1)),
        ],
    ])

    expected = {
        job1.name(): JobStatus.SUCCESS,
        job2.name(): JobStatus.SUCCESS,
    }
    assert expected == controller.wait_for_job_list_completion(
        {job1.name(), job2.name()},
        check_interval_seconds=5,
        timeout_seconds=10,
    )
    assert controller.time_module.time() == 5


def test_controller_wait_for_job_list_completion_partial(
    controller: K8sJobController, set_oc_get_items_side_effect: OCItemSetter
) -> None:
    job1 = SomeJob(identifying_attribute="some-id-1", description="some-description")
    job2 = SomeJob(identifying_attribute="some-id-2", description="some-description")
    set_oc_get_items_side_effect([
        # 0 seconds
        [
            build_job_resource(job1, build_job_status(active=1)),
            build_job_resource(job2, build_job_status(active=1)),
        ],
        # 5 seconds
        [
            build_job_resource(job1, build_job_status(succeeded=1)),
            build_job_resource(job2, build_job_status(active=1)),
        ],
        # 10 seconds - we don't reach this before the timeout
        [
            build_job_resource(job1, build_job_status(succeeded=1)),
            build_job_resource(job2, build_job_status(succeeded=1)),
        ],
    ])

    expected = {
        job1.name(): JobStatus.SUCCESS,
        job2.name(): JobStatus.IN_PROGRESS,
    }
    actual = controller.wait_for_job_list_completion(
        {job1.name(), job2.name()},
        check_interval_seconds=5,
        timeout_seconds=5,
    )
    assert expected == actual
    assert controller.time_module.time() == 5


def test_controller_wait_for_job_list_completion_no_timeout(
    controller: K8sJobController, set_oc_get_items_side_effect: OCItemSetter
) -> None:
    job1 = SomeJob(identifying_attribute="some-id-1", description="some-description")
    job2 = SomeJob(identifying_attribute="some-id-2", description="some-description")
    set_oc_get_items_side_effect(
        [
            # 0 seconds
            [
                build_job_resource(job1, build_job_status(active=1)),
                build_job_resource(job2, build_job_status(active=1)),
            ],
            # 5 seconds
            [
                build_job_resource(job1, build_job_status(succeeded=1)),
                build_job_resource(job2, build_job_status(succeeded=1)),
            ],
        ],
    )

    expected = {
        job1.name(): JobStatus.SUCCESS,
        job2.name(): JobStatus.SUCCESS,
    }
    assert expected == controller.wait_for_job_list_completion(
        {job1.name(), job2.name()},
        check_interval_seconds=5,
        timeout_seconds=-1,
    )
    assert controller.time_module.time() == 5


#
# build secret
#


def test_build_secret(controller: K8sJobController) -> None:
    job = SomeJob(identifying_attribute="some-id", credentials={"super": "secret"})
    job_secret = controller.build_secret(job)
    assert job_secret
    assert job_secret.kind == "Secret"
    assert job_secret.metadata and job_secret.metadata.name == job.name()
    assert job_secret.string_data == job.secret_data()


#
# create job
#


@pytest.mark.parametrize(
    "job, expected_applied_kinds",
    [
        (
            SomeJob(identifying_attribute="some-id", credentials={"super": "secret"}),
            ["Job", "Secret"],
        ),
        (
            SomeJob(identifying_attribute="some-id"),
            ["Job"],
        ),
    ],
)
def test_create_job(
    job: SomeJob, expected_applied_kinds: list[str], controller: K8sJobController
) -> None:
    controller.create_job(job)

    applied_kinds = [
        call.kwargs["resource"].kind for call in controller.oc.apply.call_args_list
    ]
    assert applied_kinds == expected_applied_kinds


#
# get job generation annotation
#


def test_get_job_generation(
    controller: K8sJobController, set_oc_get_items_side_effect: OCItemSetter
) -> None:
    job = SomeJob(identifying_attribute="some-id", description="some-description")
    set_oc_get_items_side_effect([
        [build_job_resource(job, build_job_status(active=1))],
    ])
    assert controller.get_job_generation(job.name())


#
# get job status
#


@pytest.mark.parametrize(
    "backoff_limit, expected_job_status",
    [
        (1, JobStatus.IN_PROGRESS),
        (0, JobStatus.ERROR),
    ],
)
def test_get_job_status_backoff_limit(
    backoff_limit: int,
    expected_job_status: JobStatus,
    controller: K8sJobController,
    set_oc_get_items_side_effect: OCItemSetter,
) -> None:
    """
    Verify that backoff_limit is honored when determining the job status.
    A failed job should be reported as IN_PROGRESS when its backoff limit is
    not exceeded yet.
    """
    job = SomeJob(identifying_attribute="some-id", backoff_limit=backoff_limit)
    set_oc_get_items_side_effect([
        [build_job_resource(job, build_job_status(failed=1))]
    ])
    assert controller.get_job_status(job_name=job.name()) == expected_job_status


def test_get_job_status_not_exists(controller: K8sJobController) -> None:
    assert controller.get_job_status(job_name="foo bar") == JobStatus.NOT_EXISTS


def test_get_job_status_no_job_resource_status(
    controller: K8sJobController, set_oc_get_items_side_effect: OCItemSetter
) -> None:
    job = SomeJob(identifying_attribute="some-id")
    set_oc_get_items_side_effect([[build_job_resource(job)]])
    assert controller.get_job_status(job_name=job.name()) == JobStatus.IN_PROGRESS
