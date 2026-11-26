"""The API contract in contracts/openapi.yaml matches the API that the server serves (story E01-002).

The client is generated from the contract, so a change to a route that is not written to the contract is a
failing test. After changing a route, run:  scripts/update-contract
"""

from pathlib import Path

import yaml

from franca.api import create_app

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml"


def test_contract_file_matches_the_served_api() -> None:
    written = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    served = create_app().openapi()
    assert written == served, "contracts/openapi.yaml is out of date: run  scripts/update-contract"


def test_every_route_is_under_api_v1() -> None:
    paths = create_app().openapi()["paths"]
    assert paths
    assert all(p.startswith("/api/v1/") for p in paths)


def test_every_operation_has_an_id_and_a_summary() -> None:
    # The generated client names its functions after the operation IDs.
    for path, operations in create_app().openapi()["paths"].items():
        for method, operation in operations.items():
            assert operation.get("operationId"), f"{method.upper()} {path} has no operationId"
            assert operation.get("summary"), f"{method.upper()} {path} has no summary"


def test_every_json_response_has_an_example() -> None:
    # The client's tests answer requests with these examples (client/src/mocks/handlers.ts).
    spec = create_app().openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    missing = []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            for status, response in operation.get("responses", {}).items():
                schema = response.get("content", {}).get("application/json", {}).get("schema")
                if not status.startswith("2") or schema is None:
                    continue
                if "$ref" in schema:
                    schema = schemas[schema["$ref"].rsplit("/", 1)[-1]]
                if not schema.get("examples"):
                    missing.append(f"{method.upper()} {path} {status}")
    assert missing == []
