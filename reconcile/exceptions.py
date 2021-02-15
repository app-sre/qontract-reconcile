class FetchResourceError(Exception):
    def __init__(self, msg):
        super().__init__("error fetching resource: " + str(msg))
