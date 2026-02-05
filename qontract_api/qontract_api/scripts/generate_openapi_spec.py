import json

from qontract_api.main import custom_openapi

print(  # noqa: T201
    json.dumps(custom_openapi(), indent=2, sort_keys=True),
)
