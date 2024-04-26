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

    def __lt__(self, other: Schedule) -> bool:
        return self.after < other.after

    def is_now(self) -> bool:
        return datetime.datetime.now(tz=datetime.timezone.utc) >= self.after

    @staticmethod
    def now() -> Schedule:
        return Schedule(
            data=(
                datetime.datetime.now(tz=datetime.timezone.utc)
                - datetime.timedelta(minutes=5)
            ).isoformat()
        )

    @staticmethod
    def default() -> Schedule:
        """
        Handy for tests
        """
        # TODO: this should be in conftest.py
        return Schedule(
            data=(
                datetime.datetime.now(tz=datetime.timezone.utc)
                - datetime.timedelta(minutes=5)
            ).isoformat()
        )
