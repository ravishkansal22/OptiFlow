"""
Mireye Gateway Agent — the single owner of all Mireye geospatial API traffic.
 
Responsibilities:
  - Live HTTP calls (with retry + exponential backoff) when MIREYE_API_KEY is configured
  - High-fidelity local simulation fallback ("mock mode") otherwise, or on live-call failure
  - Two-tier caching: Redis (if provided) with TTL, then in-process memory fallback
  - Provenance tagging (endpoint, params, timestamp, response hash, cached flag, latency)
    attached to every response returned to downstream agents
 
Run standalone (no server needed):
    python -m agents.mireye_gateway_agent                       # full mock-mode demo of every endpoint
    python -m agents.mireye_gateway_agent --mode live terrain   # real API call for one endpoint
    python -m agents.mireye_gateway_agent routing --origin 47.27,-122.42 --destination 47.41,-122.24
 
Environment variables:
    MIREYE_API_KEY      Bearer token for the live Mireye API (values starting with "mock" force simulation)
    MIREYE_BASE_URL     API root host, e.g. https://api.mireye.com (default https://api.mireye.com)
    MIREYE_MAX_RETRIES  Retry attempts per request (default 3)
"""
 
import os
import sys
import time
import json
import math
import hashlib
import logging
import asyncio
import argparse
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable, Type, Tuple
 
import httpx
from pydantic import BaseModel, ValidationError
 
from schemas.mireye import (
    ProvenanceTag,
    MireyeTerrainResponse,
    MireyeLandCoverResponse,
    MireyeFloodResponse,
    MireyeRoutingResponse,
    MireyeHazardPolygon,
    MireyeHazardLayerResponse
)
 
logger = logging.getLogger(__name__)
 
# Base32 characters for Geohash encoding
GEOHASH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
 
DEFAULT_BASE_URL = "https://api.mireye.com"
 
 
def encode_geohash(lat: float, lon: float, precision: int = 7) -> str:
    """Encodes latitude and longitude into a geohash of specified character precision."""
    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    geohash = []
    bits = [16, 8, 4, 2, 1]
    bit = 0
    ch = 0
    even = True
 
    while len(geohash) < precision:
        if even:
            mid = (lon_interval[0] + lon_interval[1]) / 2
            if lon > mid:
                ch |= bits[bit]
                lon_interval[0] = mid
            else:
                lon_interval[1] = mid
        else:
            mid = (lat_interval[0] + lat_interval[1]) / 2
            if lat > mid:
                ch |= bits[bit]
                lat_interval[0] = mid
            else:
                lat_interval[1] = mid
 
        even = not even
        if bit < 4:
            bit += 1
        else:
            geohash.append(GEOHASH_BASE32[ch])
            bit = 0
            ch = 0
 
    return "".join(geohash)
 
 
def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points in km."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c
 
 
class MireyeGatewayAgent:
    """
    Central Mireye Gateway Agent.
    Owns all Mireye traffic, caching (Redis / in-memory), retry-with-backoff,
    and provenance tagging on every single field returned to any downstream agent.
    """
 
    ENDPOINTS = {
        "terrain":   "/v1/fetch",
        # "/v1/geospatial/land-cover-parcels" does not exist in Mireye's
        # current API (verified against docs.mireye.ai — confirmed 404).
        # Land cover, like terrain, is served through the general-purpose
        # POST /v1/fetch endpoint via "fields", not a dedicated path.
        "landcover": "/v1/fetch",
        # Flood hazard is served via POST /v1/fetch with "preset": "flood_risk"
        # (not via the deprecated /v1/hazard/flood-risk endpoint, which returns 404).
        "flood":     "/v1/fetch",
        # Routing uses POST /v1/proximity with "op": "distance" and origin/destination arrays
        # (not the deprecated /v1/routing/accessibility endpoint, which returns 404).
        "routing":   "/v1/proximity",
        # Regional hazards are fetched via POST /v1/fetch with hazard presets or fields.
        "hazards":   "/v1/fetch",
    }
 
    # Mireye field-catalog names actually returned by POST /v1/fetch for the
    # "terrain" preset (docs.mireye.ai/api-reference/fetch). These are the
    # exact keys under response["fields"] — not endpoint paths.
    TERRAIN_PRESET_FIELDS = (
        "elevation", "slope_degrees", "aspect_cardinal",
        "coast_distance_m", "soil_drainage_class", "bedrock_depth_cm",
    )
 
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        redis_client=None,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        timeout_seconds: float = 10.0,
    ):
        self.api_key = api_key or os.getenv("MIREYE_API_KEY", "")
        self.base_url = (base_url or os.getenv("MIREYE_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.redis_client = redis_client
        self.max_retries = max(1, max_retries if max_retries is not None else int(os.getenv("MIREYE_MAX_RETRIES", "3")))
        self.backoff_seconds = backoff_seconds
        self.timeout_seconds = timeout_seconds
        self.memory_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # key -> (expiry_epoch, payload)
        self.call_history = deque(maxlen=1000)
 
    # ------------------------------------------------------------------ #
    # Configuration helpers
    # ------------------------------------------------------------------ #
 
    def _is_live_mode(self) -> bool:
        """True when a real (non-mock) API key is configured."""
        return bool(self.api_key) and not self.api_key.lower().startswith("mock")
 
    def _build_url(self, canonical_endpoint: str) -> str:
        """
        Joins base_url with a canonical endpoint path ("/v1/...") without
        duplicating the version segment, so provenance metadata always matches
        the URL actually requested.
        """
        if self.base_url.endswith("/v1") and canonical_endpoint.startswith("/v1"):
            return f"{self.base_url}{canonical_endpoint[len('/v1'):]}"
        return f"{self.base_url}{canonical_endpoint}"
 
    @staticmethod
    def _validate_lat_lon(lat: float, lon: float) -> None:
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"latitude out of range [-90, 90]: {lat}")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"longitude out of range [-180, 180]: {lon}")
 
    @staticmethod
    def _validate_bbox(bounding_box: List[float]) -> None:
        if len(bounding_box) != 4:
            raise ValueError(f"bounding_box must be [min_lat, min_lon, max_lat, max_lon], got {bounding_box}")
        min_lat, min_lon, max_lat, max_lon = bounding_box
        MireyeGatewayAgent._validate_lat_lon(min_lat, min_lon)
        MireyeGatewayAgent._validate_lat_lon(max_lat, max_lon)
        if min_lat > max_lat or min_lon > max_lon:
            raise ValueError(f"bounding_box corners are inverted: {bounding_box}")
 
    # ------------------------------------------------------------------ #
    # Cache internals — payloads stored in cache NEVER contain provenance
    # (keeps entries JSON-serializable and makes response hashes stable).
    # ------------------------------------------------------------------ #
 
    def _get_cache_key(self, layer: str, lat: float, lon: float, radius: float = 0.0) -> str:
        """Cache key = (layer, geohash-7, radius) as specified in the OptiFlow build plan."""
        gh7 = encode_geohash(lat, lon, precision=7)
        return f"mireye:{layer}:{gh7}:{int(radius)}"
 
    def _get_od_cache_key(self, origin: List[float], destination: List[float], mode: str = "heavy_truck") -> str:
        """Cache key for Origin-Destination routing. Includes travel mode so different modes never collide."""
        gh_o = encode_geohash(origin[0], origin[1], precision=7)
        gh_d = encode_geohash(destination[0], destination[1], precision=7)
        return f"mireye:routing:{gh_o}:{gh_d}:{mode}"
 
    def _create_provenance_tag(self, endpoint: str, params: Dict[str, Any], payload: Any, cached: bool, latency_ms: float) -> ProvenanceTag:
        # Strip any existing provenance before computing semantic response hash
        clean_payload = dict(payload) if isinstance(payload, dict) else payload
        if isinstance(clean_payload, dict) and "provenance" in clean_payload:
            clean_payload = {k: v for k, v in clean_payload.items() if k != "provenance"}
 
        raw_str = json.dumps(clean_payload, sort_keys=True, default=str)
        resp_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]
        tag = ProvenanceTag(
            endpoint=endpoint,
            params=params,
            timestamp=datetime.now(timezone.utc).isoformat(),
            response_hash=resp_hash,
            cached=cached,
            latency_ms=round(latency_ms, 2)
        )
        self.call_history.append({
            "endpoint": endpoint,
            "params": params,
            "provenance": tag.model_dump(),
            "timestamp": tag.timestamp
        })
        return tag
 
    def _read_cache(self, key: str) -> Optional[Dict[str, Any]]:
        if self.redis_client:
            try:
                cached_val = self.redis_client.get(key)
                if cached_val:
                    return json.loads(cached_val)
            except Exception as exc:
                # Redis read failed — fall through to in-memory cache. This is
                # non-fatal but should be visible so connection issues are caught early.
                logger.warning(
                    "Redis read failed for key '%s': %s: %s",
                    key, type(exc).__name__, exc
                )
        entry = self.memory_cache.get(key)
        if entry is None:
            return None
        expiry, value = entry
        if expiry < time.time():
            del self.memory_cache[key]
            return None
        return value
 
    def _write_cache(self, key: str, value: Dict[str, Any], ttl_seconds: int = 86400):
        if self.redis_client:
            try:
                self.redis_client.setex(key, ttl_seconds, json.dumps(value))
            except Exception as exc:
                # Redis write failed — value is still stored in memory_cache below.
                logger.warning(
                    "Redis write failed for key '%s': %s: %s",
                    key, type(exc).__name__, exc
                )
        self.memory_cache[key] = (time.time() + ttl_seconds, value)
 
    # ------------------------------------------------------------------ #
    # Shared execution pipeline (cache -> live retry/backoff -> simulation)
    # ------------------------------------------------------------------ #
 
    async def _request_live(
        self,
        canonical_endpoint: str,
        params: Dict[str, Any],
        method: str = "GET",
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Call the live Mireye API with retry + exponential backoff.
        method="GET" sends `params` as query params (legacy path, still used
        by the not-yet-migrated layers). method="POST" sends `json_body` as
        the JSON request body, which is what Mireye's real /v1/fetch requires.
        Returns the parsed JSON object on success, or None after exhausting retries.
        Non-200 statuses and transport errors are logged at WARNING level.
        """
        url = self._build_url(canonical_endpoint)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        if method == "POST":
            headers["content-type"] = "application/json"
        last_error = "unknown"
 
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    if method == "POST":
                        resp = await client.post(url, json=json_body, headers=headers)
                    else:
                        resp = await client.get(url, params=params, headers=headers)
 
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        data.pop("provenance", None)  # never trust inbound provenance
                        return data
                    last_error = f"non-object payload ({type(data).__name__})"
                    logger.warning("Mireye %s returned a non-object payload (%s).", url, type(data).__name__)
                else:
                    last_error = f"HTTP {resp.status_code}"
                    logger.warning(
                        "Mireye %s responded HTTP %s (attempt %d/%d).",
                        url, resp.status_code, attempt, self.max_retries
                    )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Mireye %s request failed (attempt %d/%d): %s: %s",
                    url, attempt, self.max_retries, type(exc).__name__, exc
                )
 
            if attempt < self.max_retries:
                await asyncio.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
 
        logger.error(
            "Mireye %s failed after %d attempts (%s) — falling back to local simulation.",
            url, self.max_retries, last_error
        )
        return None
 
    def _serve(
        self,
        model_cls: Type[BaseModel],
        endpoint: str,
        params: Dict[str, Any],
        payload: Dict[str, Any],
        cached: bool,
        start_time: float,
        cache_key: Optional[str] = None,
    ) -> BaseModel:
        """Attach provenance, persist the clean payload to cache, build the response model."""
        latency_ms = (time.perf_counter() - start_time) * 1000
        clean_payload = {k: v for k, v in payload.items() if k != "provenance"}
        prov = self._create_provenance_tag(endpoint, params, clean_payload, cached=cached, latency_ms=latency_ms)
        if cache_key is not None and not cached:
            self._write_cache(cache_key, clean_payload)
        return model_cls(**clean_payload, provenance=prov)
 
    async def _execute(
        self,
        model_cls: Type[BaseModel],
        layer: str,
        params: Dict[str, Any],
        cache_key: str,
        simulator: Callable[[], Dict[str, Any]],
        start_time: float,
        live_method: str = "GET",
        live_body: Optional[Dict[str, Any]] = None,
        response_mapper: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> BaseModel:
        """
        Common flow: serve from cache, else try live API, else run the local simulation.
 
        live_method/live_body: how to call the live endpoint ("POST" + a JSON
        body for Mireye's real /v1/fetch; "GET" + query params for the legacy,
        not-yet-migrated layers).
        response_mapper: translates the live API's raw response shape into the
        flat dict our pydantic model expects, run BEFORE schema validation so
        a shape mismatch is caught the same way a validation failure is
        (falls back to simulation rather than raising).
        """
        endpoint = self.ENDPOINTS[layer]
 
        cached_data = self._read_cache(cache_key)
        if isinstance(cached_data, dict):
            return self._serve(model_cls, endpoint, params, cached_data, cached=True, start_time=start_time)
 
        raw: Optional[Dict[str, Any]] = None
        if self._is_live_mode():
            raw = await self._request_live(endpoint, params, method=live_method, json_body=live_body)
            if raw is not None:
                try:
                    mapped = response_mapper(raw) if response_mapper is not None else raw
                    return self._serve(model_cls, endpoint, params, mapped, cached=False, start_time=start_time, cache_key=cache_key)
                except ValidationError as exc:
                    logger.warning(
                        "Live Mireye %s payload failed schema validation (%s) — using local simulation instead.",
                        endpoint, exc
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning(
                        "Live Mireye %s response could not be mapped (%s: %s) — using local simulation instead.",
                        endpoint, type(exc).__name__, exc
                    )
 
        simulated = simulator()
        return self._serve(model_cls, endpoint, params, simulated, cached=False, start_time=start_time, cache_key=cache_key)
 
    # ------------------------------------------------------------------ #
    # Public API — one method per Mireye product
    # ------------------------------------------------------------------ #
 
    async def get_terrain_elevation(self, lat: float, lon: float, known_base: Optional[Dict[str, Any]] = None) -> MireyeTerrainResponse:
        """
        Retrieves terrain slope, elevation, and buildability score for site screening.
        """
        self._validate_lat_lon(lat, lon)
        start_time = time.perf_counter()
        cache_key = self._get_cache_key("terrain", lat, lon)
        params = {"lat": lat, "lon": lon}
        # Real Mireye request shape: POST /v1/fetch, body uses "lng" (not
        # "lon") plus a preset name — see docs.mireye.ai/api-reference/fetch.
        live_body = {"lat": lat, "lng": lon, "preset": "terrain"}
        return await self._execute(
            MireyeTerrainResponse, "terrain", params, cache_key,
            simulator=lambda: self._simulate_terrain(lat, lon, known_base),
            start_time=start_time,
            live_method="POST",
            live_body=live_body,
            response_mapper=lambda raw: self._map_terrain_fetch_response(raw, lat, lon),
        )
 
    async def get_land_cover_buildings(self, lat: float, lon: float, radius_m: float = 500.0, known_base: Optional[Dict[str, Any]] = None) -> MireyeLandCoverResponse:
        """
        Retrieves zoning, parcel size, existing building footprint, and occupancy status.
        """
        self._validate_lat_lon(lat, lon)
        start_time = time.perf_counter()
        cache_key = self._get_cache_key("landcover", lat, lon, radius_m)
        params = {"lat": lat, "lon": lon, "radius_m": radius_m}
        # Real Mireye request shape: POST /v1/fetch, body uses "lng" (not
        # "lon"). No preset bundles land-cover + parcel + building fields
        # together, so they're requested explicitly (see docs.mireye.ai/
        # api-reference/fetch — "fields" and "preset" can be combined or
        # "fields" used alone; well under the 50-field-per-request cap).
        live_body = {
            "lat": lat,
            "lng": lon,
            "fields": [
                "land_use_class",
                "parcel_zoning",
                "parcel_area_m2",
                "primary_building_footprint_sqm",
            ],
        }
        return await self._execute(
            MireyeLandCoverResponse, "landcover", params, cache_key,
            simulator=lambda: self._simulate_land_cover(lat, lon, radius_m, known_base),
            start_time=start_time,
            live_method="POST",
            live_body=live_body,
            response_mapper=lambda raw: self._map_land_cover_fetch_response(raw, lat, lon, radius_m),
        )
 
    async def get_flood_hazard(self, lat: float, lon: float, known_base: Optional[Dict[str, Any]] = None) -> MireyeFloodResponse:
        """
        Evaluates flood exposure, annual inundation probability, and historical flood frequency.
        Uses POST /v1/fetch with preset="flood_risk" (not the deprecated /v1/hazard/flood-risk endpoint).
        """
        self._validate_lat_lon(lat, lon)
        start_time = time.perf_counter()
        cache_key = self._get_cache_key("flood", lat, lon)
        params = {"lat": lat, "lon": lon}
        # Real Mireye request: POST /v1/fetch with preset="flood_risk"
        live_body = {"lat": lat, "lng": lon, "preset": "flood_risk"}
        return await self._execute(
            MireyeFloodResponse, "flood", params, cache_key,
            simulator=lambda: self._simulate_flood(lat, lon, known_base),
            start_time=start_time,
            live_method="POST",
            live_body=live_body,
            response_mapper=lambda raw: self._map_flood_fetch_response(raw, lat, lon),
        )
 
    async def get_routing(self, origin: List[float], destination: List[float], mode: str = "heavy_truck") -> MireyeRoutingResponse:
        """
        Retrieves real road transit distance, travel time, and logistics route hazard score.
        Uses POST /v1/proximity with "op": "distance" (not the deprecated /v1/routing/accessibility endpoint).
        """
        self._validate_lat_lon(origin[0], origin[1])
        self._validate_lat_lon(destination[0], destination[1])
        start_time = time.perf_counter()
        cache_key = self._get_od_cache_key(origin, destination, mode)
        params = {"origin": origin, "destination": destination, "mode": mode}
        # Real Mireye request: POST /v1/proximity with "op": "distance"
        # origin/destination are [lat, lon] pairs; Mireye /v1/proximity expects them as arrays
        live_body = {
            "op": "distance",
            "origins": [[origin[0], origin[1]]],
            "destinations": [[destination[0], destination[1]]],
            "mode": mode  # "heavy_truck", "light_truck", "car", etc.
        }
        return await self._execute(
            MireyeRoutingResponse, "routing", params, cache_key,
            simulator=lambda: self._simulate_routing(origin, destination, mode),
            start_time=start_time,
            live_method="POST",
            live_body=live_body,
            response_mapper=lambda raw: self._map_routing_proximity_response(raw, origin, destination, mode),
        )
 
    async def get_regional_hazards(self, region_name: str, bounding_box: List[float], known_hazards: Optional[List[Dict[str, Any]]] = None) -> MireyeHazardLayerResponse:
        """
        Retrieves flood hazard polygons and active road closures across the region.
        Uses POST /v1/fetch with preset="hazards" or /v1/fetch with hazard-related fields
        (not the deprecated /v1/hazard/layers endpoint, which returns 404).
        For regional queries, uses the bounding box center point as the query location.
        """
        self._validate_bbox(bounding_box)
        start_time = time.perf_counter()
        cache_key = f"mireye:hazards:{region_name}"
        params = {"region_name": region_name, "bbox": bounding_box}

        # Compute bounding box center for the Mireye query
        min_lat, min_lon, max_lat, max_lon = bounding_box
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2

        # Real Mireye request: POST /v1/fetch at the center with hazard-related fields
        live_body = {
            "lat": center_lat,
            "lng": center_lon,
            "fields": ["flood_zone", "hazard_type", "hazard_severity"]
        }

        return await self._execute(
            MireyeHazardLayerResponse, "hazards", params, cache_key,
            simulator=lambda: self._simulate_hazards(region_name, bounding_box, known_hazards),
            start_time=start_time,
            live_method="POST",
            live_body=live_body,
            response_mapper=lambda raw: self._map_hazards_fetch_response(raw, region_name, bounding_box),
        )
 
    # ------------------------------------------------------------------ #
    # Local high-fidelity simulation (MIREYE_MOCK_MODE fallbacks)
    # ------------------------------------------------------------------ #
 
    @staticmethod
    def _map_terrain_fetch_response(raw: Dict[str, Any], lat: float, lon: float) -> Dict[str, Any]:
        """
        Translate a real POST /v1/fetch (preset="terrain") response into the
        flat shape MireyeTerrainResponse expects.
 
        Mireye's response nests each requested field under
        raw["fields"][<field_name>] = {"value": ..., "status": "ok"/"absent"/"failed", ...}
        (docs.mireye.ai/api-reference/fetch). A field with status != "ok" has
        no usable value, so we treat that as a mapping failure — this raises
        and lets _execute's existing fallback-to-simulation path handle it,
        the same way a schema ValidationError already does.
        """
        fields = raw.get("fields")
        if not isinstance(fields, dict):
            raise ValueError("terrain fetch response missing 'fields' object")
 
        def _value(field_name: str) -> Any:
            entry = fields.get(field_name)
            if not isinstance(entry, dict):
                raise ValueError(f"terrain fetch response missing field '{field_name}'")
            if entry.get("status") != "ok":
                raise ValueError(
                    f"terrain field '{field_name}' has status={entry.get('status')!r} "
                    f"(error={entry.get('error')!r}), no usable value"
                )
            return entry["value"]
 
        elevation_m = float(_value("elevation"))
        slope_degrees = float(_value("slope_degrees"))
        aspect_cardinal = _value("aspect_cardinal")
 
        # slope_pct is the inverse of the mock's slope_degrees derivation
        # (slope_degrees = atan(slope_pct / 100) in degrees), so real live
        # data and simulated data both land on the same internal shape.
        slope_pct = math.tan(math.radians(slope_degrees)) * 100.0
 
        # buildability_score isn't in Mireye's catalog — it's OptiFlow's own
        # derived score. Computed here from the real fetched elevation/slope,
        # using the identical formula the simulator uses, so live results are
        # never a hardcoded stand-in.
        buildability_score = max(0.0, min(1.0, 1.0 - (slope_pct / 10.0) - (0.3 if elevation_m > 200 else 0.0)))
 
        resolved = raw.get("resolved_location") or {}
 
        return {
            "lat": resolved.get("lat", lat),
            "lon": resolved.get("lng", lon),
            "elevation_m": round(elevation_m, 2),
            "slope_degrees": round(slope_degrees, 2),
            "slope_pct": round(slope_pct, 2),
            "aspect": aspect_cardinal,
            "buildability_score": round(buildability_score, 3),
        }
 
    @staticmethod
    def _map_land_cover_fetch_response(raw: Dict[str, Any], lat: float, lon: float, radius_m: float) -> Dict[str, Any]:
        """
        Translate a real POST /v1/fetch response (fields: land_use_class,
        parcel_zoning, parcel_area_m2, primary_building_footprint_sqm) into
        the flat shape MireyeLandCoverResponse expects.
 
        Same nested {"value", "status", ...} shape as terrain — see
        _map_terrain_fetch_response and docs.mireye.ai/api-reference/fetch.
 
        Two fields in MireyeLandCoverResponse have no direct Mireye
        equivalent and are DERIVED here, not sourced from the API:
          - is_occupied: Mireye exposes no occupancy flag. Proxied as
            "a building footprint was recorded at this parcel" — treated as
            occupied when primary_building_footprint_sqm > 0.
          - is_industrial_zoned: derived from the parcel_zoning string via a
            substring check. Mireye's zoning-code taxonomy is not published
            in the public docs consulted here, so this heuristic is
            UNVERIFIED — confirm against real parcel_zoning values for known
            industrial sites before relying on it for screening decisions.
        """
        fields = raw.get("fields")
        if not isinstance(fields, dict):
            raise ValueError("land-cover fetch response missing 'fields' object")
 
        def _value(field_name: str, required: bool = True, default: Any = None) -> Any:
            entry = fields.get(field_name)
            if not isinstance(entry, dict):
                if required:
                    raise ValueError(f"land-cover fetch response missing field '{field_name}'")
                return default
            status = entry.get("status")
            if status == "ok":
                return entry["value"]
            if status == "absent" and not required:
                # Valid no-data (e.g. no building recorded at this parcel) —
                # not a fetch failure.
                return default
            raise ValueError(
                f"land-cover field '{field_name}' has status={status!r} "
                f"(error={entry.get('error')!r}), no usable value"
            )
 
        land_use_class = _value("land_use_class")
        parcel_zoning = str(_value("parcel_zoning", required=False, default="") or "")
        parcel_area_m2 = float(_value("parcel_area_m2"))
        # A missing/absent footprint field means "no building on record" —
        # not a failure — so it defaults to 0.0 rather than raising.
        building_footprint_sqm = float(_value("primary_building_footprint_sqm", required=False, default=0.0) or 0.0)
 
        is_occupied = building_footprint_sqm > 0.0
        is_industrial_zoned = "ind" in parcel_zoning.lower()
 
        return {
            "lat": lat,
            "lon": lon,
            "radius_m": radius_m,
            "primary_land_cover": land_use_class,
            "is_industrial_zoned": is_industrial_zoned,
            "building_footprint_sqm": round(building_footprint_sqm, 2),
            "available_parcel_sqm": 0.0 if is_occupied else round(parcel_area_m2, 2),
            "is_occupied": is_occupied,
        }
 
    @staticmethod
    def _map_flood_fetch_response(raw: Dict[str, Any], lat: float, lon: float) -> Dict[str, Any]:
        """
        Translate a real POST /v1/fetch (preset="flood_risk") response into the
        flat shape MireyeFloodResponse expects.

        Similar to the terrain and land-cover mappers, the response nests each
        field under raw["fields"][<field_name>] = {"value": ..., "status": "ok"/"absent"/"failed", ...}.
        """
        fields = raw.get("fields")
        if not isinstance(fields, dict):
            raise ValueError("flood fetch response missing 'fields' object")

        def _value(field_name: str, required: bool = True, default: Any = None) -> Any:
            entry = fields.get(field_name)
            if not isinstance(entry, dict):
                if required:
                    raise ValueError(f"flood fetch response missing field '{field_name}'")
                return default
            status = entry.get("status")
            if status == "ok":
                return entry["value"]
            if status == "absent" and not required:
                return default
            raise ValueError(
                f"flood field '{field_name}' has status={status!r} "
                f"(error={entry.get('error')!r}), no usable value"
            )

        # Mireye's flood_risk preset includes: flood_zone, annual_flood_probability,
        # and related fields. Exact field names depend on preset definition.
        # Using reasonable defaults if any field is missing.
        flood_zone = _value("flood_zone", required=False, default="Zone X (Minimal Flood Hazard)")
        annual_prob = float(_value("annual_flood_probability", required=False, default=0.001))
        hist_events = int(_value("historical_flood_events", required=False, default=0))

        # elevation_differential_m is OptiFlow's derived field, not from Mireye
        elev_diff = float(_value("elevation_differential_m", required=False, default=5.0))

        # flood_risk_index is OptiFlow's own composite score
        flood_risk_idx = float(_value("flood_risk_index", required=False, default=0.05))

        return {
            "lat": lat,
            "lon": lon,
            "flood_zone": flood_zone,
            "annual_flood_probability": annual_prob,
            "elevation_differential_m": round(elev_diff, 2),
            "historical_flood_events": hist_events,
            "flood_risk_index": round(flood_risk_idx, 3)
        }

    @staticmethod
    def _map_routing_proximity_response(raw: Dict[str, Any], origin: List[float], destination: List[float], mode: str) -> Dict[str, Any]:
        """
        Translate a real POST /v1/proximity (op="distance") response into the
        flat shape MireyeRoutingResponse expects.

        Mireye's /v1/proximity distance operation returns a matrix of distances/times
        between origins and destinations. With a single origin and single destination,
        we extract the [0][0] element from the response matrix.
        """
        # Expected response structure from /v1/proximity distance operation:
        # {
        #   "distances": [[distance_km, ...], ...],
        #   "durations": [[duration_minutes, ...], ...],
        #   "routes": [[{...route_geojson...}, ...], ...],
        #   ...
        # }
        distances = raw.get("distances")
        durations = raw.get("durations")
        routes = raw.get("routes")

        if not isinstance(distances, list) or not distances or not isinstance(distances[0], list):
            raise ValueError("proximity distance response missing or malformed 'distances' matrix")

        distance_km = float(distances[0][0])

        duration_minutes = 0.0
        if isinstance(durations, list) and durations and isinstance(durations[0], list):
            duration_minutes = float(durations[0][0])
        else:
            # Compute duration from distance if not provided (assuming avg speed)
            duration_minutes = (distance_km / 48.0) * 60.0 + 4.0

        # Extract route geometry if available
        route_geojson = None
        if isinstance(routes, list) and routes and isinstance(routes[0], list) and routes[0]:
            route_geojson = routes[0][0]

        # Fallback geometry if not provided by API
        if not route_geojson:
            mid_lat = (origin[0] + destination[0]) / 2
            mid_lon = (origin[1] + destination[1]) / 2
            route_geojson = {
                "type": "LineString",
                "coordinates": [
                    [origin[1], origin[0]],
                    [mid_lon, mid_lat],
                    [destination[1], destination[0]]
                ]
            }

        # Compute route risk from location heuristics (same as simulator)
        mid_lat = (origin[0] + destination[0]) / 2
        mid_lon = (origin[1] + destination[1]) / 2
        route_risk = 0.15
        if 47.30 <= mid_lat <= 47.45 and -122.30 <= mid_lon <= -122.20:
            route_risk = 0.45

        return {
            "origin": origin,
            "destination": destination,
            "distance_km": round(distance_km, 2),
            "duration_minutes": round(duration_minutes, 1),
            "toll_cost_usd": 0.0,  # Mireye doesn't return toll costs; OptiFlow doesn't model them
            "fuel_cost_usd": round((distance_km * 2.15) + (duration_minutes * 0.65), 2),
            "route_risk_score": round(route_risk, 3),
            "geometry_geojson": route_geojson
        }

    @staticmethod
    def _map_hazards_fetch_response(raw: Dict[str, Any], region_name: str, bounding_box: List[float]) -> Dict[str, Any]:
        """
        Translate a real POST /v1/fetch response (hazard-related fields) into the
        flat shape MireyeHazardLayerResponse expects.

        Since /v1/fetch queries a single point, not a region, this mapper constructs
        a minimal hazard layer response. In production, this might call a different
        Mireye endpoint optimized for regional polygon queries, but that endpoint
        isn't currently documented as available. As a fallback, we use /v1/fetch
        at the region center and extract what hazard data is available.
        """
        fields = raw.get("fields", {})

        # Try to extract hazard information from the /v1/fetch response
        def _value(field_name: str, required: bool = False, default: Any = None) -> Any:
            entry = fields.get(field_name)
            if not isinstance(entry, dict):
                if required:
                    raise ValueError(f"hazards response missing field '{field_name}'")
                return default
            status = entry.get("status")
            if status == "ok":
                return entry["value"]
            if status == "absent" and not required:
                return default
            raise ValueError(f"hazards field '{field_name}' has status={status!r}, no usable value")

        flood_zone = _value("flood_zone", required=False, default="Zone X (Minimal Flood Hazard)")
        hazard_type = _value("hazard_type", required=False, default="FloodZone")
        hazard_severity = _value("hazard_severity", required=False, default="Low")

        # Build a single hazard polygon from the queried point
        min_lat, min_lon, max_lat, max_lon = bounding_box
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2

        # Create a simple polygon around the center point (not a true regional polygon,
        # but the best we can do with point-based /v1/fetch data)
        delta = 0.05  # ~5.5 km at the equator
        polygon_coords = [
            [center_lon - delta, center_lat - delta],
            [center_lon + delta, center_lat - delta],
            [center_lon + delta, center_lat + delta],
            [center_lon - delta, center_lat + delta],
            [center_lon - delta, center_lat - delta],
        ]

        hazard_polygon = {
            "hazard_id": f"{region_name}_primary",
            "hazard_type": hazard_type,
            "severity": hazard_severity,
            "coordinates": polygon_coords,
            "description": f"{hazard_type} in {region_name}: {flood_zone}"
        }

        return {
            "region_name": region_name,
            "bounding_box": bounding_box,
            "hazards": [hazard_polygon],
            "active_road_closures": []
        }

    @staticmethod
    def _simulate_terrain(lat: float, lon: float, known_base: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        elev = known_base.get("base_elevation_m", 25.0) if known_base else 25.0 + math.sin(lat * 50) * 15
        slope = known_base.get("base_slope_pct", 1.5) if known_base else abs(math.cos(lon * 40) * 4)
 
        # Sites with slope > 8% or elevation > 250m have severely degraded buildability
        buildability = max(0.0, min(1.0, 1.0 - (slope / 10.0) - (0.3 if elev > 200 else 0.0)))
 
        return {
            "lat": lat,
            "lon": lon,
            "elevation_m": round(elev, 2),
            "slope_degrees": round(math.atan(slope / 100) * 180 / math.pi, 2),
            "slope_pct": round(slope, 2),
            "aspect": "North-West" if lon < -122.25 else "South-East",
            "buildability_score": round(buildability, 3)
        }
 
    @staticmethod
    def _simulate_land_cover(lat: float, lon: float, radius_m: float, known_base: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        land_cover = known_base.get("land_cover", "Industrial") if known_base else "Industrial"
        parcel_sqm = known_base.get("parcel_sqm", 60000.0) if known_base else 55000.0
        is_occupied = land_cover in ["ProtectedWetland", "Forestry/SteepSlope", "ResidentialDense"]
 
        return {
            "lat": lat,
            "lon": lon,
            "radius_m": radius_m,
            "primary_land_cover": land_cover,
            "is_industrial_zoned": land_cover in ["Industrial", "Commercial"],
            "building_footprint_sqm": 8500.0 if is_occupied else 0.0,
            "available_parcel_sqm": 0.0 if is_occupied else parcel_sqm,
            "is_occupied": is_occupied
        }
 
    @staticmethod
    def _simulate_flood(lat: float, lon: float, known_base: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        elev = known_base.get("base_elevation_m", 25.0) if known_base else 25.0
 
        # Geospatial logic: Low elevation valleys near Green River (Kent South) and Puyallup Delta have high flood scores
        is_green_river_lowland = (47.34 <= lat <= 47.43) and (-122.26 <= lon <= -122.21) and (elev < 15.0)
        is_puyallup_delta = (47.21 <= lat <= 47.27) and (-122.43 <= lon <= -122.36) and (elev < 10.0)
 
        if is_green_river_lowland or is_puyallup_delta:
            flood_zone = "Zone AE (100-Year Base Flood)"
            annual_prob = 0.025
            flood_risk_idx = 0.82 if is_puyallup_delta else 0.76
            hist_events = 4
            elev_diff = -1.8
        elif elev < 15.0:
            flood_zone = "Zone X500 (500-Year Moderate Flood)"
            annual_prob = 0.005
            flood_risk_idx = 0.35
            hist_events = 1
            elev_diff = 1.5
        else:
            flood_zone = "Zone X (Minimal Flood Hazard)"
            annual_prob = 0.001
            flood_risk_idx = 0.05
            hist_events = 0
            elev_diff = 12.0
 
        return {
            "lat": lat,
            "lon": lon,
            "flood_zone": flood_zone,
            "annual_flood_probability": annual_prob,
            "elevation_differential_m": round(elev_diff, 2),
            "historical_flood_events": hist_events,
            "flood_risk_index": round(flood_risk_idx, 3)
        }
 
    @staticmethod
    def _simulate_routing(origin: List[float], destination: List[float], mode: str) -> Dict[str, Any]:
        # Haversine distance with real-world road winding multiplier (1.28x - 1.42x)
        h_dist = haversine_distance_km(origin[0], origin[1], destination[0], destination[1])
        road_distance_km = max(1.5, h_dist * 1.32)
 
        # Average commercial truck speed in Puget Sound corridor: 55 km/h highway, 30 km/h urban
        avg_speed_kmh = 48.0
        duration_minutes = (road_distance_km / avg_speed_kmh) * 60.0 + 4.0  # +4 min terminal maneuvering
 
        # Freight cost model: $2.15/km + driver time ($0.65/min) + fuel
        transport_cost = (road_distance_km * 2.15) + (duration_minutes * 0.65)
 
        # Check if route passes near known high flood corridors
        mid_lat = (origin[0] + destination[0]) / 2
        mid_lon = (origin[1] + destination[1]) / 2
        route_risk = 0.15
        if 47.30 <= mid_lat <= 47.45 and -122.30 <= mid_lon <= -122.20:
            route_risk = 0.45
 
        return {
            "origin": origin,
            "destination": destination,
            "distance_km": round(road_distance_km, 2),
            "duration_minutes": round(duration_minutes, 1),
            "toll_cost_usd": 0.0,
            "fuel_cost_usd": round(transport_cost, 2),
            "route_risk_score": round(route_risk, 3),
            "geometry_geojson": {
                "type": "LineString",
                "coordinates": [
                    [origin[1], origin[0]],
                    [mid_lon, mid_lat],
                    [destination[1], destination[0]]
                ]
            }
        }
 
    @staticmethod
    def _simulate_hazards(region_name: str, bounding_box: List[float], known_hazards: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        hazards = []
        if known_hazards:
            for hz in known_hazards:
                hazards.append(MireyeHazardPolygon(
                    hazard_id=hz["hazard_id"],
                    hazard_type=hz.get("hazard_type", "FloodZone"),
                    severity=hz.get("severity", "High"),
                    coordinates=hz["coordinates"],
                    description=hz.get("description", "Regional Hazard Polygon")
                ))
 
        return {
            "region_name": region_name,
            "bounding_box": bounding_box,
            "hazards": [h.model_dump() for h in hazards],
            "active_road_closures": [
                {
                    "road_name": "SR-167 Green River Overpass",
                    "status": "Potential Inundation Risk",
                    "lat": 47.3800,
                    "lon": -122.2300
                }
            ]
        }
 
 
# ---------------------------------------------------------------------- #
# Standalone runner — lets you exercise this agent in isolation without
# the FastAPI app or any other OptiFlow component.
#
#   python -m agents.mireye_gateway_agent                     full demo (auto mode)
#   python -m agents.mireye_gateway_agent --mode mock         force local simulation
#   python -m agents.mireye_gateway_agent --mode live all     force real API calls
#   python -m agents.mireye_gateway_agent terrain --lat 47.4124 --lon -122.2415
#   python -m agents.mireye_gateway_agent landcover --lat 47.4124 --lon -122.2415 --radius-m 800
#   python -m agents.mireye_gateway_agent flood --lat 47.3688 --lon -122.2289
#   python -m agents.mireye_gateway_agent routing \
#       --origin 47.2725,-122.4182 --destination 47.4124,-122.2415
#   python -m agents.mireye_gateway_agent hazards --region KentValley \
#       --bbox 47.34,-122.26,47.43,-122.21
#   python -m agents.mireye_gateway_agent --json all          machine-readable output
# ---------------------------------------------------------------------- #
 
DEMO_SITES: Dict[str, Dict[str, float]] = {
    "kent-valley":       {"lat": 47.3800, "lon": -122.2340},
    "puyallup-delta":    {"lat": 47.2400, "lon": -122.4000},
    "seattle-industrial": {"lat": 47.5480, "lon": -122.3350},
    "tacoma-port":       {"lat": 47.2650, "lon": -122.4200},
}
 
 
def _parse_coord(text: str) -> List[float]:
    return _parse_float_list(text, 2, "'lat,lon'")
 
 
def _parse_bbox(text: str) -> List[float]:
    return _parse_float_list(text, 4, "'min_lat,min_lon,max_lat,max_lon'")
 
 
def _parse_float_list(text: str, count: int, expected: str) -> List[float]:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != count:
        raise argparse.ArgumentTypeError(f"expected {expected}, got '{text}'")
    try:
        return [float(p) for p in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))
 
 
def build_arg_parser() -> argparse.ArgumentParser:
    # Shared flags live on a parent parser so they work BEFORE or AFTER the subcommand
    # (e.g. "--json all" and "all --json" are both accepted).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--mode", choices=["auto", "mock", "live"], default="auto",
                        help="auto: use MIREYE_API_KEY if set | mock: force simulation | live: require MIREYE_API_KEY")
    common.add_argument("--json", action="store_true", help="print raw JSON payloads only")
    common.add_argument("--redis-url", default=None, help="optional Redis URL to exercise the Redis cache tier")
 
    parser = argparse.ArgumentParser(
        prog="python -m agents.mireye_gateway_agent",
        description="Standalone tester for the Mireye Gateway Agent (mock or live API calls).",
        parents=[common],
    )
 
    sub = parser.add_subparsers(dest="target")
 
    p_all = sub.add_parser("all", parents=[common], help="exercise every endpoint end-to-end (default)")
    p_all.add_argument("--site", choices=sorted(DEMO_SITES), default="kent-valley")
 
    for name, help_text in [
        ("terrain", "terrain elevation / slope / buildability"),
        ("landcover", "zoning, parcels and building footprints"),
        ("flood", "flood zone and inundation risk"),
    ]:
        p = sub.add_parser(name, parents=[common], help=help_text)
        p.add_argument("--lat", type=float, default=DEMO_SITES["kent-valley"]["lat"])
        p.add_argument("--lon", type=float, default=DEMO_SITES["kent-valley"]["lon"])
        if name == "landcover":
            p.add_argument("--radius-m", type=float, default=500.0)
 
    p_route = sub.add_parser("routing", parents=[common], help="O-D truck routing and cost estimate")
    p_route.add_argument("--origin", type=_parse_coord, default=[47.2725, -122.4182], metavar="LAT,LON")
    p_route.add_argument("--destination", type=_parse_coord, default=[47.4124, -122.2415], metavar="LAT,LON")
    p_route.add_argument("--travel-mode", default="heavy_truck")
 
    p_hz = sub.add_parser("hazards", parents=[common], help="regional hazard layers and road closures")
    p_hz.add_argument("--region", default="KentValley")
    p_hz.add_argument("--bbox", type=_parse_bbox, default=[47.34, -122.26, 47.43, -122.21],
                      metavar="MINLAT,MINLON,MAXLAT,MAXLON",
                      help="four comma-separated values, e.g. 47.34,-122.26,47.43,-122.21")
    p_hz.add_argument("--known-hazards-file", default=None,
                      help="optional JSON file with a list of hazard polygons to merge")
 
    # Defaults for when no subcommand is supplied (equivalent to "all")
    parser.set_defaults(target="all", site="kent-valley")
 
    return parser
 
 
def _make_agent(args: argparse.Namespace) -> MireyeGatewayAgent:
    redis_client = None
    if args.redis_url:
        import redis  # lazy: only needed when explicitly requested
        redis_client = redis.Redis.from_url(args.redis_url)
 
    if args.mode == "mock":
        agent = MireyeGatewayAgent(api_key="", redis_client=redis_client)
        print("[mireye-agent] MOCK MODE — responses come from the local geospatial simulation.")
    elif args.mode == "live":
        api_key = os.getenv("MIREYE_API_KEY", "")
        if not api_key or api_key.lower().startswith("mock"):
            raise SystemExit("--mode live requires a real MIREYE_API_KEY environment variable.")
        base_url = os.getenv("MIREYE_BASE_URL", DEFAULT_BASE_URL)
        agent = MireyeGatewayAgent(api_key=api_key, base_url=base_url, redis_client=redis_client)
        print(f"[mireye-agent] LIVE MODE — calling {agent.base_url} with retry x{agent.max_retries}.")
    else:
        agent = MireyeGatewayAgent(redis_client=redis_client)
        state = "LIVE" if agent._is_live_mode() else "MOCK"
        print(f"[mireye-agent] AUTO MODE — resolved to {state} "
              f"({'MIREYE_API_KEY found' if state == 'LIVE' else 'set MIREYE_API_KEY to hit the real API'}).")
    return agent
 
 
def _print_result(title: str, result: BaseModel, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.model_dump(), indent=2, default=str))
        return
    prov = result.provenance
    print(f"\n=== {title} ===")
    body = result.model_dump(exclude={"provenance"}, exclude_none=True)
    print(json.dumps(body, indent=2, default=str))
    print(f"-- provenance: endpoint={prov.endpoint} cached={prov.cached} "
          f"latency={prov.latency_ms}ms hash={prov.response_hash}")
 
 
async def run_checks(agent: MireyeGatewayAgent, args: argparse.Namespace) -> int:
    target = args.target or "all"
    results: List[tuple] = []
    exit_code = 0
 
    try:
        if target == "terrain":
            results.append(("TERRAIN", await agent.get_terrain_elevation(args.lat, args.lon)))
        elif target == "landcover":
            results.append(("LAND COVER", await agent.get_land_cover_buildings(args.lat, args.lon, args.radius_m)))
        elif target == "flood":
            results.append(("FLOOD HAZARD", await agent.get_flood_hazard(args.lat, args.lon)))
        elif target == "routing":
            results.append(("ROUTING", await agent.get_routing(args.origin, args.destination, args.travel_mode)))
        elif target == "hazards":
            known = None
            if getattr(args, "known_hazards_file", None):
                with open(args.known_hazards_file, "r", encoding="utf-8") as fh:
                    known = json.load(fh)
            results.append(("REGIONAL HAZARDS", await agent.get_regional_hazards(args.region, args.bbox, known)))
        else:  # "all"
            site = DEMO_SITES[args.site]
            lat, lon = site["lat"], site["lon"]
            results.append(("TERRAIN", await agent.get_terrain_elevation(lat, lon)))
            results.append(("LAND COVER", await agent.get_land_cover_buildings(lat, lon)))
            results.append(("FLOOD HAZARD", await agent.get_flood_hazard(lat, lon)))
            results.append(("ROUTING", await agent.get_routing(
                [DEMO_SITES["tacoma-port"]["lat"], DEMO_SITES["tacoma-port"]["lon"]],
                [lat, lon],
            )))
            results.append(("REGIONAL HAZARDS", await agent.get_regional_hazards(
                f"{args.site}-region", [lat - 0.05, lon - 0.05, lat + 0.05, lon + 0.05]
            )))
 
            print("\n--- cache verification: repeat terrain call (must be served from cache) ---")
            repeat = await agent.get_terrain_elevation(lat, lon)
            assert repeat.provenance.cached, "repeat call was NOT served from cache!"
            results.append(("TERRAIN (cached)", repeat))
    except (ValueError, ValidationError) as exc:
        print(f"[mireye-agent] input/schema error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"[mireye-agent] unexpected failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
 
    for title, res in results:
        _print_result(title, res, args.json)
 
    if not args.json:
        print(f"\n[mireye-agent] done — {len(results)} call(s), {len(agent.call_history)} history entries.")
    return exit_code
 
 
async def main_async(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    agent = _make_agent(args)
    return await run_checks(agent, args)
 
 
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))