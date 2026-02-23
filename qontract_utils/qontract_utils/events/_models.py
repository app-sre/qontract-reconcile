from cloudevents.pydantic.v2.event import CloudEvent


class Event(CloudEvent):
    """Represents a CloudEvent with a flexible payload.

    The payload can be any JSON-serializable data structure, allowing for
    versatile event contents while adhering to the CloudEvents specification.
    """
