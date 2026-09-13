from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from travel.config import travel_settings
from travel.providers import Amap, ProviderUnavailable


@pytest.mark.asyncio
async def test_quota_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(travel_settings, "amap_key", SecretStr("test-only"))
    get = AsyncMock(
        return_value=httpx.Response(
            200,
            json={"status": "0", "infocode": "10003"},
            request=httpx.Request("GET", "https://example.com"),
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    with pytest.raises(ProviderUnavailable):
        await Amap().get("place/text", city="杭州")
    assert get.await_count == 1


@pytest.mark.asyncio
async def test_cache_reuses_result_without_exposing_credentials(monkeypatch):
    monkeypatch.setattr(travel_settings, "amap_key", SecretStr("test-only"))
    get = AsyncMock(
        return_value=httpx.Response(
            200,
            json={"status": "1", "pois": []},
            request=httpx.Request("GET", "https://example.com"),
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    client = Amap()
    first = await client.get("place/text", city="杭州")
    first["pois"].append("caller mutation")
    second = await client.get("place/text", city="杭州")
    assert second["pois"] == []
    assert get.await_count == 1
    assert "test-only" not in str(client.cache)


@pytest.mark.asyncio
async def test_transient_server_failure_retries_once(monkeypatch):
    monkeypatch.setattr(travel_settings, "amap_key", SecretStr("test-only"))
    request = httpx.Request("GET", "https://example.com")
    get = AsyncMock(
        side_effect=[
            httpx.Response(503, request=request),
            httpx.Response(200, json={"status": "1"}, request=request),
        ]
    )
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    assert (await Amap().get("place/text"))["status"] == "1"
    assert get.await_count == 2
