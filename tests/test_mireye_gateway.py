import pytest
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
