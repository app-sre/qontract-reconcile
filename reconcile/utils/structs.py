class CommandExecutionResult:
    """This class represents a command execution result"""

    def __init__(self, is_ok, message):
        self.is_ok = is_ok
        self.message = message

    def __str__(self):
        return str(self.message).replace("\n", "")

    def __bool__(self):
        return self.is_ok
