"""Common exceptions for qontract integrations."""


class IntegrationError(Exception):
    """Raised when an integration encounters a terminal error condition.

    Use this instead of sys.exit() in async integration code to allow the
    framework's top-level runner to handle process exit codes cleanly without
    short-circuiting async shutdown.
    """
