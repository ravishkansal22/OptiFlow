import json
import logging
import pytest
from unittest.mock import MagicMock
from agents.mireye_gateway_agent import MireyeGatewayAgent, encode_geohash, haversine_distance_km


def test_geohash_encoding():
    lat = 47.4124
    lon = -122.2415
    gh = encode_geohash(lat, lon, precision=7)
    assert len(gh) == 7
    assert isinstance(gh, str)


def test_haversine_distance():
    # Distance between Seattle (47.6062, -122.3321) and Tacoma (47.2529, -122.4443) ~ 40 km
    dist = haversine_distance_km(47.6062, -122.3321, 47.2529, -122.4443)
    assert 35.0 < dist < 45.0


@pytest.mark.asyncio
async def test_mireye_gateway_terrain_and_provenance():
    gw = MireyeGatewayAgent()
    
    # 1. First call (Uncached)
    resp1 = await gw.get_terrain_elevation(47.4124, -122.2415)
    assert resp1.elevation_m > 0
    assert resp1.provenance is not None
    assert resp1.provenance.endpoint == "/v1/geospatial/terrain-elevation"
    assert resp1.provenance.cached is False
    assert len(resp1.provenance.response_hash) > 0

    # 2. Second call (Must be Cached with identical hash)
    resp2 = await gw.get_terrain_elevation(47.4124, -122.2415)
    assert resp2.provenance.cached is True
    assert resp2.provenance.response_hash == resp1.provenance.response_hash


@pytest.mark.asyncio
async def test_mireye_gateway_flood_and_routing():
    gw = MireyeGatewayAgent()
    flood = await gw.get_flood_hazard(47.3688, -122.2289)
    assert flood.flood_risk_index >= 0.0
    assert flood.provenance.endpoint == "/v1/hazard/flood-risk"

    routing = await gw.get_routing([47.2725, -122.4182], [47.4124, -122.2415])
    assert routing.distance_km > 0
    assert routing.duration_minutes > 0
    assert routing.fuel_cost_usd > 0
    assert routing.provenance.endpoint == "/v1/routing/accessibility"


@pytest.mark.asyncio
async def test_redis_connection_error_is_logged(caplog):
    """
    When the Redis client raises a ConnectionError on .get(), the gateway must:
      1. Log a WARNING (not swallow the exception silently).
      2. Fall through to the in-memory cache / mock-mode path and still return a valid result,
         so callers are never disrupted by a Redis outage.
    """
    broken_redis = MagicMock()
    broken_redis.get.side_effect = ConnectionError("Redis connection refused")

    gw = MireyeGatewayAgent(redis_client=broken_redis)

    with caplog.at_level(logging.WARNING, logger="agents.mireye_gateway_agent"):
        result = await gw.get_terrain_elevation(47.4124, -122.2415)

    # The call must still succeed via mock-mode fallback
    assert result.elevation_m is not None
    assert result.provenance is not None

    # Redis .get() must have been called (proving the Redis path was attempted)
    broken_redis.get.assert_called_once()

    # A WARNING must have been emitted mentioning the failure and exception type
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "Redis read failed" in msg and "ConnectionError" in msg
        for msg in warning_messages
    ), f"Expected Redis warning not found in logs. Got: {warning_messages}"


@pytest.mark.asyncio
async def test_redis_cache_receives_json_serializable_payload():
    """
    Regression: cached payloads used to embed a Pydantic ProvenanceTag, which made
    json.dumps() (and therefore every Redis cache write) fail with a TypeError.
    The clean payload must be valid JSON and must NOT contain a provenance key.
    """
    fake_redis = MagicMock()
    gw = MireyeGatewayAgent(redis_client=fake_redis)

    resp = await gw.get_terrain_elevation(47.4124, -122.2415)

    fake_redis.setex.assert_called_once()
    key, ttl, value = fake_redis.setex.call_args.args
    parsed = json.loads(value)
    assert key.startswith("mireye:terrain:")
    assert ttl == 86400
    assert "provenance" not in parsed
    assert parsed["elevation_m"] == resp.elevation_m


@pytest.mark.asyncio
async def test_routing_cache_distinguishes_travel_modes():
    """Regression: mode was omitted from the O-D cache key, so 'drone' was served 'heavy_truck' data."""
    gw = MireyeGatewayAgent()
    origin, destination = [47.2725, -122.4182], [47.4124, -122.2415]

    truck1 = await gw.get_routing(origin, destination, mode="heavy_truck")
    drone = await gw.get_routing(origin, destination, mode="drone")
    truck2 = await gw.get_routing(origin, destination, mode="heavy_truck")

    assert drone.provenance.cached is False          # separate cache entry per mode
    assert truck2.provenance.cached is True          # same mode hits the cache
    assert truck2.provenance.response_hash == truck1.provenance.response_hash


@pytest.mark.asyncio
async def test_cached_response_hash_matches_fresh_hash():
    """Cache round-trip must preserve the semantic response hash (provenance excluded from hashing)."""
    fake_redis = MagicMock()
    # Make Redis behave like real JSON round-trip storage
    store = {}
    fake_redis.get.side_effect = lambda k: store.get(k)
    fake_redis.setex.side_effect = lambda k, ttl, v: store.__setitem__(k, v)

    gw = MireyeGatewayAgent(redis_client=fake_redis)
    fresh = await gw.get_flood_hazard(47.3688, -122.2289)
    cached = await gw.get_flood_hazard(47.3688, -122.2289)

    assert cached.provenance.cached is True
    assert cached.flood_zone == fresh.flood_zone
    assert cached.provenance.response_hash == fresh.provenance.response_hash


@pytest.mark.asyncio
async def test_invalid_coordinates_rejected():
    gw = MireyeGatewayAgent()
    with pytest.raises(ValueError):
        await gw.get_terrain_elevation(lat=95.0, lon=-122.0)
    with pytest.raises(ValueError):
        await gw.get_flood_hazard(lat=47.3, lon=-200.0)


@pytest.mark.asyncio
async def test_live_call_retries_then_falls_back_to_simulation(monkeypatch):
    """
    When the live API is unreachable, the gateway must retry max_retries times,
    then fall back to the local simulation and still return a valid response.
    """
    import agents.mireye_gateway_agent as mod

    attempts = {"count": 0}

    class FlakyClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, **kwargs):
            attempts["count"] += 1
            raise ConnectionError("network unreachable")

    monkeypatch.setattr(mod.httpx, "AsyncClient", FlakyClient)

    gw = MireyeGatewayAgent(api_key="real-key-123", max_retries=3, backoff_seconds=0.0)
    resp = await gw.get_terrain_elevation(47.4124, -122.2415)

    assert attempts["count"] == 3                       # retried exactly max_retries times
    assert resp.elevation_m > 0                         # simulation fallback produced data
    assert resp.provenance.cached is False
    assert len(gw.call_history) >= 1                    # provenance still recorded
