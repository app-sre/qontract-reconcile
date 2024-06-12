import logging
from collections.abc import Callable
from typing import (
    Any,
    Self,
)

import requests
from pydantic import BaseModel

from reconcile.gql_definitions.acs.acs_instances import AcsInstanceV1
from reconcile.gql_definitions.acs.acs_instances import query as acs_instances_query
from reconcile.utils.exceptions import AppInterfaceSettingsError


class AcsBaseApi(BaseModel):
    url: str
    token: str
    timeout: int = 30
    session: requests.Session = requests.Session()

    class Config:
        arbitrary_types_allowed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.session.close()

    @staticmethod
    def get_acs_instance(query_func: Callable) -> AcsInstanceV1:
        """
        Get an ACS instance

        :param query_func: function which queries GQL Server
        """
        if instances := acs_instances_query(query_func=query_func).instances:
            # mirroring logic for gitlab instances
            # current assumption is for appsre to only utilize one instance
            if len(instances) != 1:
                raise AppInterfaceSettingsError("More than one ACS instance found!")
            return instances[0]
        raise AppInterfaceSettingsError("No ACS instance found!")

    @staticmethod
    def check_len_attributes(attrs: list[Any], api_data: Any) -> None:
        # generic attribute check function for expected types with valid len()
        for attr in attrs:
            value = api_data.get(attr)
            if value is None or len(value) == 0:
                raise ValueError(
                    f"Attribute '{attr}' must exist and not be empty\n\t{api_data}"
                )

    def generic_request(
        self, path: str, verb: str, json: Any | None = None
    ) -> requests.Response:
        url = f"{self.url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
        }
        response = self.session.request(
            verb,
            url,
            headers=headers,
            json=json,
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logging.error(f"{str(e)}: {response.text}")
            raise

        return response

    def generic_request_json(
        self, path: str, verb: str, json: Any | None = None
    ) -> Any:
        return self.generic_request(path, verb, json=json).json()
