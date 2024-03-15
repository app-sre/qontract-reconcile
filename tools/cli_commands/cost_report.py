from typing import Self


class CostReportCommand:
    def execute(self) -> str:
        pass

    @classmethod
    def create(
        cls,
    ) -> Self:
        return cls()
