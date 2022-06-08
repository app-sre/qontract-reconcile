import json
import requests

from graphql import get_introspection_query


INTROSPECTION_JSON_FILE = "reconcile/gql_queries/schema_introspection.json"


def query_schema():
    gql_url = "http://localhost:4000/graphql"
    query = get_introspection_query()
    request = requests.post(gql_url, json={"query": query})
    if request.status_code == 200:
        with open(INTROSPECTION_JSON_FILE, "w") as f:
            f.write(json.dumps(request.json(), indent=4))
            return
    raise Exception(f"Could not query {gql_url}")


query_schema()
