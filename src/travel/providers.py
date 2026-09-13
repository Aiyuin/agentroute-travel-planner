"""Bounded read-only Amap calls. Credentials never enter returned evidence."""

import asyncio
import time
from copy import deepcopy

import httpx

from travel.config import travel_settings


class ProviderUnavailable(Exception):
    pass


class Amap:
    def __init__(self):
        self.cache: dict = {}

    async def get(self, path: str, **params) -> dict:
        key = travel_settings.amap_key
        if not key:
            raise ProviderUnavailable("missing_amap_key")
        cache_key = (path, tuple(sorted(params.items())))
        cached = self.cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return deepcopy(cached[1])
        async with httpx.AsyncClient(timeout=8) as client:
            for attempt in range(2):
                try:
                    response = await client.get(
                        f"https://restapi.amap.com/v3/{path}",
                        params={**params, "key": key.get_secret_value()},
                    )
                    if response.status_code >= 500 and attempt == 0:
                        await asyncio.sleep(0.3)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    # Application quota/auth errors are deliberately never retried.
                    if data.get("status") != "1":
                        raise ProviderUnavailable("amap_rejected")
                    if len(self.cache) >= 256:
                        self.cache.clear()
                    self.cache[cache_key] = (time.monotonic() + 300, data)
                    return deepcopy(data)
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt:
                        raise ProviderUnavailable("amap_network") from None
                    await asyncio.sleep(0.3)
        raise ProviderUnavailable("amap_unavailable")

    async def geocode(self, city: str, address: str) -> dict:
        data = await self.get("geocode/geo", city=city, address=address)
        if not data.get("geocodes"):
            raise ProviderUnavailable("geocode_empty")
        return data["geocodes"][0]

    async def search(self, city: str, keyword: str) -> list[dict]:
        data = await self.get("place/text", city=city, keywords=keyword, citylimit="true", offset=3)
        results = []
        for poi in data.get("pois", [])[:3]:
            location = poi.get("location")
            if not location:
                try:
                    location = (await self.geocode(city, poi["name"])).get("location")
                except Exception:
                    location = None
            results.append(
                {"name": poi["name"], "address": poi.get("address"), "location": location}
            )
        return results


amap = Amap()


async def map_evidence(kind: str, city: str) -> dict:
    if kind == "weather":
        location = await amap.geocode(city, city)
        data = await amap.get("weather/weatherInfo", city=location["adcode"], extensions="all")
        return {"source": "amap_weather", "data": data.get("forecasts", [])}
    if kind in ("attractions", "hotels"):
        return {
            "source": "amap_poi",
            "data": await amap.search(city, "景点" if kind == "attractions" else "酒店"),
        }
    raise ValueError("unknown evidence kind")


async def mcp_evidence(city: str) -> dict:
    """Only call the known read-only maps_text_search tool at an operator-set server."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    if not travel_settings.mcp_url:
        raise ProviderUnavailable("missing_mcp_url")
    headers = {}
    if travel_settings.mcp_token:
        headers["Authorization"] = "Bearer " + travel_settings.mcp_token.get_secret_value()
    client = MultiServerMCPClient(
        {
            "amap": {
                "transport": "streamable_http",
                "url": travel_settings.mcp_url,
                "headers": headers,
            }
        }
    )
    tools = await client.get_tools()
    tool = next((tool for tool in tools if tool.name == "maps_text_search"), None)
    if tool is None:
        raise ProviderUnavailable("mcp_tool_missing")
    result = await tool.ainvoke({"keywords": "景点", "city": city, "citylimit": True})
    return {"source": "amap_mcp", "data": str(result)[:12000]}
