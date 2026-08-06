"""Unit tests for mcp_servers/gleif_server.py, via an httpx.MockTransport replaying the response
shape confirmed live against https://api.gleif.org during Phase 3 implementation (see
gleif_server.py's module docstring) -- no network access needed."""

from __future__ import annotations

import httpx

from greenlux_sentinel.mcp_servers import gleif_server

_LEI_RECORD = {
    "type": "lei-records",
    "id": "254900T9OSB6HNQZBG26",
    "attributes": {
        "lei": "254900T9OSB6HNQZBG26",
        "entity": {
            "legalName": {"name": "Global Innovators Pool", "language": "fr"},
            "legalForm": {"id": "8888", "other": "SUB-FUND"},
            "legalAddress": {"country": "LU"},
            "status": "ACTIVE",
            "category": "FUND",
        },
    },
}


def _client(handler):
    return httpx.Client(base_url="https://api.gleif.org/api/v1", transport=httpx.MockTransport(handler))


class TestLookupLei:
    def test_by_lei_hits_the_single_record_endpoint(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/lei-records/254900T9OSB6HNQZBG26"
            return httpx.Response(200, json={"data": _LEI_RECORD})

        result = gleif_server.lookup_lei("254900T9OSB6HNQZBG26", client=_client(handler))

        assert result == {
            "lei": "254900T9OSB6HNQZBG26",
            "legal_name": "Global Innovators Pool",
            "entity_legal_form": "8888",
            "entity_status": "ACTIVE",
            "country": "LU",
        }

    def test_by_lei_not_found_returns_none(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        assert gleif_server.lookup_lei("00000000000000000000", client=_client(handler)) is None

    def test_by_name_hits_the_search_endpoint_and_takes_the_first_match(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/lei-records"
            assert request.url.params["filter[entity.legalName]"] == "Amundi"
            return httpx.Response(200, json={"data": [_LEI_RECORD]})

        result = gleif_server.lookup_lei("Amundi", client=_client(handler))

        assert result["legal_name"] == "Global Innovators Pool"

    def test_by_name_no_match_returns_none(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        assert gleif_server.lookup_lei("Nonexistent Fund Xyz", client=_client(handler)) is None


class TestSearchLuEntities:
    def test_filters_by_lu_country_and_entity_category(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["filter[entity.legalAddress.country]"] == "LU"
            assert request.url.params["filter[entity.category]"] == "FUND"
            return httpx.Response(200, json={"data": [_LEI_RECORD, _LEI_RECORD]})

        results = gleif_server.search_lu_entities("FUND", client=_client(handler))

        assert len(results) == 2
        assert all(r["country"] == "LU" for r in results)

    def test_no_entity_type_omits_the_category_filter(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "filter[entity.category]" not in request.url.params
            return httpx.Response(200, json={"data": []})

        gleif_server.search_lu_entities(client=_client(handler))
