import pytest
from kubernetes.client import V1JobSpec, V1PodTemplateSpec
from pydantic import BaseModel

from reconcile.test.utils.jobcontroller.fixtures import SomeJob, SomeJobV2
from reconcile.utils.jobcontroller.models import (
    JOB_GENERATION_ANNOTATION,
    MAX_JOB_NAME_LENGTH,
    UNIT_OF_WORK_DIGEST_LENGTH,
    K8sJob,
)


@pytest.mark.parametrize(
    "name_prefix, expected_max_prefix_length",
    [
        # Short prefix - should not be truncated
        ("short-job", MAX_JOB_NAME_LENGTH - UNIT_OF_WORK_DIGEST_LENGTH - 1),
        # Medium prefix - should not be truncated
        (
            "medium-length-job-name",
            MAX_JOB_NAME_LENGTH - UNIT_OF_WORK_DIGEST_LENGTH - 1,
        ),
        # Long prefix that needs truncation
        (
            "very-long-job-name-that-exceeds-the-kubernetes-naming-limit-significantly",
            MAX_JOB_NAME_LENGTH - UNIT_OF_WORK_DIGEST_LENGTH - 1,
        ),
    ],
)
def test_name_truncates_prefix_correctly(
    name_prefix: str, expected_max_prefix_length: int
) -> None:
    """Test that name() correctly truncates the prefix to ensure total length compliance"""

    class TestJob(K8sJob, BaseModel):
        test_id: str

        def name_prefix(self) -> str:
            return name_prefix

        def unit_of_work_identity(self) -> str:
            return self.test_id

        def job_spec(self) -> V1JobSpec:
            return V1JobSpec(template=V1PodTemplateSpec())

    job = TestJob(test_id="test-123")
    full_name = job.name()
    prefix = job.name_prefix()

    # The prefix in the name should be truncated if necessary
    truncated_prefix = prefix[:expected_max_prefix_length]
    assert full_name.startswith(truncated_prefix)

    # Total name length should not exceed MAX_JOB_NAME_LENGTH
    assert len(full_name) <= MAX_JOB_NAME_LENGTH

    # Name should have format: {prefix}-{digest}
    # The digest should be UNIT_OF_WORK_DIGEST_LENGTH characters
    parts = full_name.split("-")
    digest = parts[-1]
    assert len(digest) == UNIT_OF_WORK_DIGEST_LENGTH


def test_name_format_consistency() -> None:
    """Test that the full job name follows the expected format"""
    job = SomeJob(identifying_attribute="test-id")
    full_name = job.name()
    prefix = job.name_prefix()

    # Name should start with prefix
    assert full_name.startswith(prefix)

    # Name should end with a digest separated by hyphen
    assert "-" in full_name
    parts = full_name.rsplit("-", 1)
    assert len(parts) == 2
    assert parts[0] == prefix
    assert len(parts[1]) == UNIT_OF_WORK_DIGEST_LENGTH


def test_name_uniqueness_based_on_unit_of_work() -> None:
    """Test that jobs with different unit_of_work_identity get different names"""
    job_a = SomeJob(identifying_attribute="job-a")
    job_b = SomeJob(identifying_attribute="job-b")

    # Same prefix but different unit of work should yield different names
    assert job_a.name_prefix() == job_b.name_prefix()
    assert job_a.name() != job_b.name()


def test_name_consistency_with_same_unit_of_work() -> None:
    """Test that jobs with the same unit_of_work_identity get the same name"""
    job_a = SomeJob(identifying_attribute="same-id")
    job_b = SomeJob(identifying_attribute="same-id")

    # Same prefix and same unit of work should yield identical names
    assert job_a.name() == job_b.name()


#
# job spec digest
#


def test_job_spec_generation_digest_same_job() -> None:
    """
    Even if the jobs are different instances and their identifying_attribute
    and description are different, the generation digest is the same since it
    is the same job_spec method implementation.
    """
    job_a = SomeJob(identifying_attribute="some-id", description="some-description")
    job_b = SomeJob(
        identifying_attribute="another-id", description="another-description"
    )
    assert job_a.job_spec_generation_digest() == job_b.job_spec_generation_digest()


def test_job_spec_generation_digest_different_job() -> None:
    """
    The difference in both jobs is the implementation of the job_spec method.
    So the generation digest is different even though the identifying_attribute
    and description are the same.
    """
    identifying_attribute = "some-id"
    description = "some-description"
    job_v1 = SomeJob(
        identifying_attribute=identifying_attribute, description=description
    )
    job_v2 = SomeJobV2(
        identifying_attribute=identifying_attribute, description=description
    )
    assert job_v1.job_spec_generation_digest() != job_v2.job_spec_generation_digest()


#
# job building
#


def test_build_job_generation_annotation() -> None:
    job = SomeJob(identifying_attribute="some-id", description="some-description")
    job_resource = job.build_job()
    assert not job.annotations()
    assert job_resource.metadata
    assert job_resource.metadata.annotations
    assert job_resource.metadata.annotations[JOB_GENERATION_ANNOTATION]


def test_unit_of_work_digest() -> None:
    job_a = SomeJob(identifying_attribute="some-id", description="some-description")
    job_b = SomeJob(identifying_attribute="some-id", description="another-description")
    job_c = SomeJob(identifying_attribute="another-id", description="some-description")

    assert job_a.unit_of_work_digest() == job_b.unit_of_work_digest()
    assert job_a.unit_of_work_digest() != job_c.unit_of_work_digest()
