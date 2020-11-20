class ElasticSearchResourceNameInvalidError(Exception):
    def __init__(self, msg):
        super(ElasticSearchResourceNameInvalidError, self).__init__(
            str(msg)
        )


class ElasticSearchResourceMissingSubnetIdError(Exception):
    def __init__(self, msg):
        super(ElasticSearchResourceMissingSubnetIdError, self).__init__(
            str(msg)
        )


class ElasticSearchResourceVersionInvalidError(Exception):
    def __init__(self, msg):
        super(ElasticSearchResourceVersionInvalidError, self).__init__(
            str(msg)
        )


class ElasticSearchResourceZoneAwareSubnetInvalidError(Exception):
    def __init__(self, msg):
        super(ElasticSearchResourceZoneAwareSubnetInvalidError, self).__init__(
            str(msg)
        )
