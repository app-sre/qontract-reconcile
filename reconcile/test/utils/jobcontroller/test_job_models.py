from reconcile.test.utils.jobcontroller.fixtures import SomeJob, SomeJobV2
from reconcile.utils.jobcontroller.models import JOB_GENERATION_ANNOTATION

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
