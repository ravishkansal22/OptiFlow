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
