from pydantic.dataclasses import dataclass


@dataclass
class CommandExecutionResult:
    """This class represents a command execution result"""

    def __init__(self, is_ok: bool, message: str) -> None:
        self.is_ok = is_ok
        self.message = message

    def __str__(self) -> str:
        return str(self.message)

    def __bool__(self) -> bool:
        return self.is_ok
