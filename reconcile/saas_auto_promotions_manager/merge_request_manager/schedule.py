class ScheduleFormatError(Exception):
    pass


class Schedule:
    def __init__(self, data: str) -> None:
        if not data:
            raise ScheduleFormatError
