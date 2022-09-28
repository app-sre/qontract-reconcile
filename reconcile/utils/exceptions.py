class FetchResourceError(Exception):
    def __init__(self, msg):
        super().__init__("error fetching resource: " + str(msg))


class PrintToFileInGitRepositoryError(Exception):
    def __init__(self, msg):
        super().__init__("can not print to a git repository: " + str(msg))


class AppInterfaceSettingsError(Exception):
    pass


class AppInterfaceSmtpSettingsError(AppInterfaceSettingsError):
    pass
