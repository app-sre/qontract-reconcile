from __future__ import annotations

import datetime


class ScheduleFormatError(Exception):
    pass


class Schedule:
    def __init__(self, data: str) -> None:
        if not data:
            raise ScheduleFormatError
        try:
            self.after: datetime.datetime = datetime.datetime.fromisoformat(data)
        except ValueError:
            raise ScheduleFormatError

    @staticmethod
    def default() -> Schedule:
        """
        Handy for tests
        """
        # TODO: this should be in conftest.py
        return Schedule(data="2023-08-31T16:47+00:00")
