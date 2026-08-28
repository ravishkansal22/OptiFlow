import asyncio
import logging
import os
import time
import json
import hashlib
import math
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import httpx

from schemas.mireye import (
    ProvenanceTag,
    MireyeTerrainResponse,
    MireyeLandCoverResponse,
    MireyeFloodResponse,
    MireyeRoutingResponse,
    MireyeHazardPolygon,
    MireyeHazardLayerResponse
)

log = logging.getLogger("optiflow.mireye")

# Base32 characters for Geohash encoding
GEOHASH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


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


def _brief(body: Dict[str, Any]) -> str:
    """Compact one-line description of a request body for logs."""
    if not isinstance(body, dict):
        return ""
    if "lat" in body and "lng" in body:
        return f"({body['lat']:.4f},{body['lng']:.4f} {body.get('preset', '')})"
    if "origins" in body:
        o = (body.get("origins") or [""])[0]
        d = (body.get("destinations") or [""])[0]
        return f"({o} -> {d})"
    return ""


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points in km."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


class RateLimiter:
    """
    Async token bucket. Every outbound HTTP request must acquire a token, so the
    gateway can never exceed `per_minute` requests in any rolling minute no
    matter how many agents or requests are running concurrently.
    """

    def __init__(self, per_minute: int):
        self.per_minute = max(1, per_minute)
        self.capacity = float(self.per_minute)
        self.tokens = float(self.per_minute)
        self.refill_per_sec = self.per_minute / 60.0
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()
        self.total_waits = 0
        self.total_wait_seconds = 0.0

    async def acquire(self) -> float:
        """Blocks until a token is free. Returns how long it waited, in seconds."""
        waited = 0.0
        while True:
            async with self._lock:
                now = time.monotonic()
                self.tokens = min(
                    self.capacity, self.tokens + (now - self.updated) * self.refill_per_sec
                )
                self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    if waited > 0:
                        self.total_waits += 1
                        self.total_wait_seconds += waited
                    return waited
                deficit = 1.0 - self.tokens
                sleep_for = max(deficit / self.refill_per_sec, 0.01)
            await asyncio.sleep(sleep_for)
            waited += sleep_for

    def snapshot(self) -> Dict[str, Any]:
        now = time.monotonic()
        tokens = min(self.capacity, self.tokens + (now - self.updated) * self.refill_per_sec)
        return {
            "limit_per_minute": self.per_minute,
            "tokens_available": round(tokens, 1),
            "times_throttled": self.total_waits,
            "total_wait_seconds": round(self.total_wait_seconds, 1),
        }


class MireyeGatewayAgent:
    """
    Central Mireye Gateway Agent.
    Owns all Mireye traffic, caching (Redis / in-memory), retry-with-backoff,
    and provenance tagging on every single field returned to any downstream agent.

    Real Mireye API contract (verified against https://docs.mireye.ai, Aug 2026):
      - Base URL: https://api.mireye.com  (endpoint paths below already include /v1/...)
      - Auth: header "Authorization: Bearer <token>" on every request (no query-param keys)
      - Every data endpoint is POST + JSON body -- never GET + query params
      - POST /v1/fetch        -> single-point scalar field lookups (terrain, flood_risk,
                                   land_cover, natural_hazard, ... "preset" bundles)
      - POST /v1/fetch/batch  -> up to 25 discrete lat/lng points per call, no bbox/region
      - POST /v1/proximity    -> {"op":"distance", origins:[...], destinations:[...]} for
                                   real driving distance_km / duration between two points
      - POST /v1/lookup       -> address/coord -> county/parcel/timezone context
      - GET  /v1/meta/fields  -> public, unauthenticated field catalog
      There is NO bounding-box / region hazard-polygon endpoint, and no field in the
      catalog returns polygon/geometry data (only scalar values and boolean
      within_*/intersects_* flags) -- see get_regional_hazards() below for what that
      means for this gateway.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, redis_client=None):
        self.api_key = api_key or os.getenv("MIREYE_API_KEY", "")
        self.base_url = base_url or os.getenv("MIREYE_BASE_URL", "https://api.mireye.com")
        self.redis_client = redis_client
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        self.call_history: List[Dict[str, Any]] = []
        self.subscribers = []
        # Records, per cache key, whether the cached value came from the live API.
        # Kept beside the payload so cached dicts stay clean model input.
        self._live_flags: Dict[str, bool] = {}
        # When set, a failed live call raises instead of silently simulating.
        _strict_env = os.getenv("MIREYE_STRICT_LIVE", "").strip().lower()
        _has_key = bool(self.api_key and not self.api_key.startswith("mock"))
        self.strict_live = (
            _strict_env in {"1", "true", "yes", "on"}
            if _strict_env
            else _has_key  # default: refuse to fake data when a key is present
        )
        # Counters so callers can report how much of a run was genuinely live.
        self.live_calls = 0
        self.simulated_calls = 0
        self.last_live_error: Optional[str] = None
        # A first fetch for a cold coordinate can take well over 10s; later calls
        # for the same point return in under a second. Too low a ceiling here is
        # the difference between live data and a silent simulation fallback.
        self.request_timeout = float(os.getenv("MIREYE_TIMEOUT", "30"))
        self.max_attempts = max(1, int(os.getenv("MIREYE_MAX_ATTEMPTS", "2")))
        # Mireye allows 300/min; stay under it with headroom for retries.
        self.limiter = RateLimiter(int(os.getenv("MIREYE_MAX_CALLS_PER_MIN", "250")))

    def clear_cache(self) -> Dict[str, int]:
        """Drops every cached value, live flag and call record. Returns what was removed."""
        removed = {
            "memory_entries": len(self.memory_cache),
            "call_history": len(self.call_history),
            "redis_keys": 0,
        }
        if self.redis_client:
            try:
                keys = list(self.redis_client.scan_iter(match="mireye:*"))
                if keys:
                    self.redis_client.delete(*keys)
                removed["redis_keys"] = len(keys)
            except Exception:
                pass
        self.memory_cache.clear()
        self._live_flags.clear()
        self.call_history.clear()
        self.live_calls = 0
        self.simulated_calls = 0
        self.last_live_error = None
        return removed

    def data_source_summary(self) -> Dict[str, Any]:
        """How much of what has been served so far actually came from the API."""
        total = self.live_calls + self.simulated_calls
        return {
            "api_key_configured": bool(self.api_key and not self.api_key.startswith("mock")),
            "strict_live": self.strict_live,
            "base_url": self.base_url,
            "live_values": self.live_calls,
            "simulated_values": self.simulated_calls,
            "total_values": total,
            "live_pct": round((self.live_calls / total) * 100, 1) if total else 0.0,
            "cached_entries": len(self.memory_cache),
            "last_live_error": self.last_live_error,
            "request_timeout_s": self.request_timeout,
            "max_attempts": self.max_attempts,
            "rate_limit": self.limiter.snapshot(),
        }

    def _refuse_simulation(
        self, endpoint: str, detail: str, reason: str, fatal: bool = True
    ) -> None:
        """
        Called at every simulation fallback that has a real live path.

        A 200 response with a missing or failed field lands here just like a
        network error does, so strict mode covers both rather than only the
        obvious failure.

        `fatal` is False for routing: the API regularly returns a leg it cannot
        drive (flag "unreachable_or_snapped") among hundreds that resolve fine.
        Aborting a whole run for one such leg is disproportionate, and an
        estimated travel time does not fabricate a site verdict the way a
        simulated slope or flood reading would. It is still counted and tagged
        as non-live so the totals stay honest.
        """
        if self.strict_live and fatal:
            log.error("STRICT %s %s -> refusing simulated values: %s", endpoint, detail, reason)
            raise RuntimeError(
                f"Live Mireye data unavailable for {endpoint} {detail}: {reason}. "
                f"Strict mode is on, so simulated values were not substituted. "
                f"Set MIREYE_STRICT_LIVE=0 to allow the fallback."
            )
        log.warning("SIM   %s %s -> simulated (%s)", endpoint, detail, reason)

    def _get_cache_key(self, layer: str, lat: float, lon: float, radius: float = 0.0) -> str:
        """Cache key = (layer, geohash-7, radius) as specified in the OptiFlow build plan."""
        gh7 = encode_geohash(lat, lon, precision=7)
        return f"mireye:{layer}:{gh7}:{int(radius)}"

    def _get_od_cache_key(self, origin: List[float], destination: List[float]) -> str:
        """Cache key for Origin-Destination routing."""
        gh_o = encode_geohash(origin[0], origin[1], precision=7)
        gh_d = encode_geohash(destination[0], destination[1], precision=7)
        return f"mireye:routing:{gh_o}:{gh_d}"

    def _create_provenance_tag(self, endpoint: str, params: Dict[str, Any], payload: Any, cached: bool, latency_ms: float, live: bool = False) -> ProvenanceTag:
        # Strip any existing provenance before computing semantic response hash
        clean_payload = dict(payload) if isinstance(payload, dict) else payload
        if isinstance(clean_payload, dict) and "provenance" in clean_payload:
            clean_payload = {k: v for k, v in clean_payload.items() if k != "provenance"}

        raw_str = json.dumps(clean_payload, sort_keys=True, default=str)
        resp_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]
        source = ("cache" if live else "cache-simulation") if cached else ("live" if live else "simulation")
        tag = ProvenanceTag(
            endpoint=endpoint,
            params=params,
            timestamp=datetime.now(timezone.utc).isoformat(),
            response_hash=resp_hash,
            cached=cached,
            latency_ms=round(latency_ms, 2),
            live=live,
            source=source
        )
        if not cached:
            if live:
                self.live_calls += 1
            else:
                self.simulated_calls += 1
        self.call_history.append({
            "endpoint": endpoint,
            "params": params,
            "provenance": tag.model_dump(),
            "timestamp": tag.timestamp,
            "live": live,
            "source": source
        })
        return tag

    def _read_cache(self, key: str) -> Optional[Dict[str, Any]]:
        if self.redis_client:
            try:
                cached_val = self.redis_client.get(key)
                if cached_val:
                    return json.loads(cached_val)
            except Exception:
                pass
        return self.memory_cache.get(key)

    def _write_cache(self, key: str, value: Dict[str, Any], ttl_seconds: int = 86400, live: bool = False):
        if self.redis_client:
            try:
                self.redis_client.setex(key, ttl_seconds, json.dumps(value))
            except Exception:
                pass
        self.memory_cache[key] = value
        self._live_flags[key] = live

    async def _post_json(self, path: str, body: Dict[str, Any], timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Shared low-level POST helper for every real Mireye v1 endpoint. Mireye's actual
        API is JSON-body POST for every data endpoint (never GET+query-params), and
        authenticates with a single `Authorization: Bearer <token>` header -- see
        https://docs.mireye.ai/authentication.md and
        https://docs.mireye.ai/api-reference/fetch.md.

        Returns the parsed JSON body on HTTP 200, or None on any non-200 status,
        network error, or when no live key is configured -- every caller below falls
        back to the local simulation model in all of those cases, exactly as before.
        """
        if not (self.api_key and not self.api_key.startswith("mock")):
            return None

        timeout = timeout or self.request_timeout

        # Retry transient failures before giving up. Without this a single slow
        # response silently substitutes simulated values AND caches them, so one
        # bad moment poisons that coordinate for the whole cache TTL.
        last_error: Optional[str] = None
        for attempt in range(self.max_attempts):
            # Hard cap: never exceed the configured calls-per-minute, however
            # many agents or requests are in flight.
            waited = await self.limiter.acquire()
            if waited > 0.05:
                log.info("rate limit: waited %.1fs for a token (cap %d/min)", waited, self.limiter.per_minute)

            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}{path}",
                        json=body,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        }
                    )
                if resp.status_code == 200:
                    log.info(
                        "LIVE  %s %s -> 200 in %.0fms",
                        path, _brief(body), (time.perf_counter() - started) * 1000
                    )
                    return resp.json()

                # Surface the API's own explanation -- "US coordinates only" is
                # far more actionable than a bare status code.
                last_error = f"HTTP {resp.status_code}"
                try:
                    detail = resp.json().get("detail")
                    if isinstance(detail, dict):
                        code = detail.get("error")
                        msg = detail.get("message")
                        last_error = f"{code}: {msg}" if code and msg else (msg or code or last_error)
                    elif isinstance(detail, str):
                        last_error = detail
                except Exception:
                    pass

                log.warning(
                    "FAIL  %s %s -> %s (attempt %d/%d)",
                    path, _brief(body), last_error, attempt + 1, self.max_attempts
                )

                # Client errors other than rate limiting will not fix themselves.
                if resp.status_code < 500 and resp.status_code != 429:
                    break
            except Exception as exc:
                last_error = type(exc).__name__
                log.warning(
                    "FAIL  %s %s -> %s after %.0fms (attempt %d/%d)",
                    path, _brief(body), last_error,
                    (time.perf_counter() - started) * 1000, attempt + 1, self.max_attempts
                )

            if attempt < self.max_attempts - 1:
                await asyncio.sleep(0.6 * (2 ** attempt))

        self.last_live_error = last_error
        if self.strict_live:
            log.error("STRICT %s %s -> giving up: %s", path, _brief(body), last_error)
            raise RuntimeError(
                f"Live Mireye data unavailable for {path} {_brief(body)}: "
                f"{last_error or 'no response'}. Strict mode is on, so simulated values "
                f"were not substituted. Set MIREYE_STRICT_LIVE=0 to allow the fallback."
            )
        log.warning("SIM   %s %s -> falling back to simulation (%s)", path, _brief(body), last_error)
        return None

    @staticmethod
    def _field_value(fields: Dict[str, Any], name: str, default: Any = None) -> Any:
        """
        Pull a scalar out of a Mireye /v1/fetch `fields` payload, trusting only fields
        whose status is 'ok' (a 'failed'/'absent' status means that particular source
        didn't resolve for this point -- Mireye still returns HTTP 200 with a
        partial_failures list in that case, per https://docs.mireye.ai/api-reference/errors.md).
        """
        entry = fields.get(name) if isinstance(fields, dict) else None
        if isinstance(entry, dict) and entry.get("status", "ok") == "ok":
            return entry.get("value", default)
        return default

    async def get_terrain_elevation(self, lat: float, lon: float, known_base: Optional[Dict[str, Any]] = None) -> MireyeTerrainResponse:
        """
        Retrieves terrain slope, elevation, and buildability score for site screening.
        """
        start_time = time.perf_counter()
        cache_key = self._get_cache_key("terrain", lat, lon)
        cached_data = self._read_cache(cache_key)

        endpoint = "/v1/fetch"
        params = {"lat": lat, "lng": lon, "preset": "terrain"}

        if cached_data:
            latency_ms = (time.perf_counter() - start_time) * 1000
            prov = self._create_provenance_tag(endpoint, params, cached_data, cached=True, latency_ms=latency_ms, live=self._live_flags.get(cache_key, False))
            cached_data["provenance"] = prov
            return MireyeTerrainResponse(**cached_data)

        # Query live Mireye API if a key is present, otherwise high-precision simulation.
        # Real contract: POST https://api.mireye.com/v1/fetch, preset "terrain" returns
        # elevation, slope_degrees, aspect_cardinal, bedrock_depth_cm, coast_distance_m.
        # See https://docs.mireye.ai/api-reference/fetch.md
        live = await self._post_json(endpoint, params)
        if live:
            fields = live.get("fields", {})
            elevation_m = self._field_value(fields, "elevation")
            slope_degrees = self._field_value(fields, "slope_degrees")
            if elevation_m is not None and slope_degrees is not None:
                slope_pct = round(math.tan(math.radians(slope_degrees)) * 100, 2)
                buildability = max(0.0, min(1.0, 1.0 - (slope_pct / 10.0) - (0.3 if elevation_m > 200 else 0.0)))
                aspect = self._field_value(fields, "aspect_cardinal") or "Flat"

                raw = {
                    "lat": lat,
                    "lon": lon,
                    "elevation_m": round(elevation_m, 2),
                    "slope_degrees": round(slope_degrees, 2),
                    "slope_pct": slope_pct,
                    "aspect": aspect,
                    "buildability_score": round(buildability, 3)
                }

                latency_ms = (time.perf_counter() - start_time) * 1000
                prov = self._create_provenance_tag(endpoint, params, raw, cached=False, latency_ms=latency_ms, live=True)
                raw["provenance"] = prov
                self._write_cache(cache_key, raw, live=True)
                return MireyeTerrainResponse(**raw)

        self._refuse_simulation(
            endpoint,
            f"({lat:.4f},{lon:.4f} terrain)",
            "response was missing elevation or slope_degrees" if live
            else (self.last_live_error or "no response"),
        )

        # High-Fidelity Local Mireye Geospatial Model Fallback
        elev = known_base.get("base_elevation_m", 25.0) if known_base else 25.0 + math.sin(lat * 50) * 15
        slope = known_base.get("base_slope_pct", 1.5) if known_base else abs(math.cos(lon * 40) * 4)

        # Sites with slope > 8% or elevation > 250m have severely degraded buildability
        buildability = max(0.0, min(1.0, 1.0 - (slope / 10.0) - (0.3 if elev > 200 else 0.0)))

        raw_result = {
            "lat": lat,
            "lon": lon,
            "elevation_m": round(elev, 2),
            "slope_degrees": round(math.atan(slope / 100) * 180 / math.pi, 2),
            "slope_pct": round(slope, 2),
            "aspect": "North-West" if lon < -122.25 else "South-East",
            "buildability_score": round(buildability, 3)
        }

        latency_ms = (time.perf_counter() - start_time) * 1000
        prov = self._create_provenance_tag(endpoint, params, raw_result, cached=False, latency_ms=latency_ms, live=False)
        raw_result["provenance"] = prov
        self._write_cache(cache_key, raw_result, live=False)
        return MireyeTerrainResponse(**raw_result)

    async def get_land_cover_buildings(self, lat: float, lon: float, radius_m: float = 500.0, known_base: Optional[Dict[str, Any]] = None) -> MireyeLandCoverResponse:
        """
        Retrieves zoning, parcel size, existing building footprint, and occupancy status.
        """
        start_time = time.perf_counter()
        cache_key = self._get_cache_key("landcover", lat, lon, radius_m)
        cached_data = self._read_cache(cache_key)

        endpoint = "/v1/fetch"
        # NOTE: Mireye's /v1/fetch is a single-point query -- there is no radius/buffer
        # parameter in the real API. radius_m is kept only for our own cache-key/interface
        # shape below and is NOT sent in the live request body.
        params = {
            "lat": lat, "lng": lon,
            "preset": "land_cover",
            "fields": ["primary_building_footprint_sqm", "primary_building_overture_class"]
        }

        if cached_data:
            latency_ms = (time.perf_counter() - start_time) * 1000
            prov = self._create_provenance_tag(endpoint, params, cached_data, cached=True, latency_ms=latency_ms, live=self._live_flags.get(cache_key, False))
            cached_data["provenance"] = prov
            return MireyeLandCoverResponse(**cached_data)

        # Real contract: POST https://api.mireye.com/v1/fetch, preset "land_cover" plus
        # explicit building_lookup fields combined in a single call. See
        # https://docs.mireye.ai/api-reference/fetch.md and field-catalog.md
        # NOTE: the real Mireye field catalog has no direct "zoning" or "parcel area"
        # field -- is_industrial_zoned/available_parcel_sqm below are approximated from
        # land-cover class and our seeded parcel size, not literal Mireye fields.
        live = await self._post_json(endpoint, params)
        if live:
            fields = live.get("fields", {})
            lcms_class = self._field_value(fields, "lcms_class")
            land_use_class = self._field_value(fields, "land_use_class")
            building_class = self._field_value(fields, "primary_building_overture_class")
            footprint_sqm = self._field_value(fields, "primary_building_footprint_sqm")

            if lcms_class is not None or land_use_class is not None:
                primary_land_cover = lcms_class or land_use_class

                # Mireye's building fields always describe the NEAREST building
                # regardless of distance -- there is no containment/distance field
                # in the catalog (confirmed against field-catalog.md) -- so a nonzero
                # footprint does NOT mean this parcel itself has a building on it; it
                # would flag almost every real-world point as "occupied". Occupancy is
                # instead inferred from land-cover class: forest/water/wetland classes
                # are treated as non-buildable/protected here, matching the seeded
                # data's own ProtectedWetland/Forestry convention.
                NON_BUILDABLE_LAND_CLASSES = {"Trees", "Water", "Snow/Ice", "Wetland/Herbaceous", "Wetland"}
                is_occupied = primary_land_cover in NON_BUILDABLE_LAND_CLASSES
                is_industrial = (
                    building_class in ("industrial", "commercial")
                    if building_class else (land_use_class == "Developed")
                )
                parcel_sqm = known_base.get("parcel_sqm", 60000.0) if known_base else 55000.0

                raw = {
                    "lat": lat,
                    "lon": lon,
                    "radius_m": radius_m,
                    "primary_land_cover": primary_land_cover,
                    "is_industrial_zoned": bool(is_industrial),
                    "building_footprint_sqm": round(footprint_sqm, 1) if footprint_sqm else 0.0,
                    "available_parcel_sqm": 0.0 if is_occupied else parcel_sqm,
                    "is_occupied": is_occupied
                }

                latency_ms = (time.perf_counter() - start_time) * 1000
                prov = self._create_provenance_tag(endpoint, params, raw, cached=False, latency_ms=latency_ms, live=True)
                raw["provenance"] = prov
                self._write_cache(cache_key, raw, live=True)
                return MireyeLandCoverResponse(**raw)

        self._refuse_simulation(
            endpoint,
            f"({lat:.4f},{lon:.4f} land_cover)",
            "response was missing land cover fields" if live
            else (self.last_live_error or "no response"),
        )

        land_cover = known_base.get("land_cover", "Industrial") if known_base else "Industrial"
        parcel_sqm = known_base.get("parcel_sqm", 60000.0) if known_base else 55000.0
        is_occupied = land_cover in ["ProtectedWetland", "Forestry/SteepSlope", "ResidentialDense"]

        raw_result = {
            "lat": lat,
            "lon": lon,
            "radius_m": radius_m,
            "primary_land_cover": land_cover,
            "is_industrial_zoned": land_cover in ["Industrial", "Commercial"],
            "building_footprint_sqm": 8500.0 if is_occupied else 0.0,
            "available_parcel_sqm": 0.0 if is_occupied else parcel_sqm,
            "is_occupied": is_occupied
        }

        latency_ms = (time.perf_counter() - start_time) * 1000
        prov = self._create_provenance_tag(endpoint, params, raw_result, cached=False, latency_ms=latency_ms, live=False)
        raw_result["provenance"] = prov
        self._write_cache(cache_key, raw_result, live=False)
        return MireyeLandCoverResponse(**raw_result)

    async def get_flood_hazard(self, lat: float, lon: float, known_base: Optional[Dict[str, Any]] = None) -> MireyeFloodResponse:
        """
        Evaluates flood exposure, annual inundation probability, and historical flood frequency.
        """
        start_time = time.perf_counter()
        cache_key = self._get_cache_key("flood", lat, lon)
        cached_data = self._read_cache(cache_key)

        endpoint = "/v1/fetch"
        params = {"lat": lat, "lng": lon, "preset": "flood_risk"}

        if cached_data:
            latency_ms = (time.perf_counter() - start_time) * 1000
            prov = self._create_provenance_tag(endpoint, params, cached_data, cached=True, latency_ms=latency_ms, live=self._live_flags.get(cache_key, False))
            cached_data["provenance"] = prov
            return MireyeFloodResponse(**cached_data)

        # Real contract: POST https://api.mireye.com/v1/fetch, preset "flood_risk".
        # NOTE: Mireye's real catalog has no FEMA-zone-letter or historical-event-count
        # field -- it exposes boolean/continuous hazard SIGNALS (within_floodplain_polygon,
        # surface_water_permanence_pct, wetland proximity/counts, coast_distance_m). The
        # zone label, probability, and event count below are our own composite derived
        # from those real signals, not literal Mireye fields. See
        # https://docs.mireye.ai/api-reference/field-catalog.md
        live = await self._post_json(endpoint, params)
        if live:
            fields = live.get("fields", {})
            within_fp = self._field_value(fields, "within_floodplain_polygon")
            if within_fp is not None:
                elevation_m = self._field_value(fields, "elevation")
                coast_dist_m = self._field_value(fields, "coast_distance_m")
                surface_water_pct = self._field_value(fields, "surface_water_permanence_pct", 0.0) or 0.0
                intersects_wetland = bool(self._field_value(fields, "intersects_wetland", False))
                wetlands_500m = self._field_value(fields, "wetlands_within_500m_count", 0) or 0

                if within_fp:
                    flood_zone = "Zone AE (FEMA Special Flood Hazard Area)"
                    annual_prob = 0.01
                    base_risk = 0.65
                    hist_events = 3
                elif intersects_wetland or wetlands_500m > 0:
                    flood_zone = "Zone X500 (Wetland-Adjacent, Moderate Hazard)"
                    annual_prob = 0.004
                    base_risk = 0.30
                    hist_events = 1
                else:
                    flood_zone = "Zone X (Minimal Flood Hazard)"
                    annual_prob = 0.001
                    base_risk = 0.05
                    hist_events = 0

                water_modifier = min(0.25, surface_water_pct / 400.0)
                coast_modifier = 0.1 if (coast_dist_m is not None and coast_dist_m < 2000) else 0.0
                flood_risk_idx = max(0.0, min(1.0, base_risk + water_modifier + coast_modifier))
                elev_diff = round(elevation_m - 10.0, 2) if elevation_m is not None else 0.0

                raw = {
                    "lat": lat,
                    "lon": lon,
                    "flood_zone": flood_zone,
                    "annual_flood_probability": annual_prob,
                    "elevation_differential_m": elev_diff,
                    "historical_flood_events": hist_events,
                    "flood_risk_index": round(flood_risk_idx, 3)
                }

                latency_ms = (time.perf_counter() - start_time) * 1000
                prov = self._create_provenance_tag(endpoint, params, raw, cached=False, latency_ms=latency_ms, live=True)
                raw["provenance"] = prov
                self._write_cache(cache_key, raw, live=True)
                return MireyeFloodResponse(**raw)

        self._refuse_simulation(
            endpoint,
            f"({lat:.4f},{lon:.4f} flood_risk)",
            "response was missing flood fields" if live
            else (self.last_live_error or "no response"),
        )

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

        raw_result = {
            "lat": lat,
            "lon": lon,
            "flood_zone": flood_zone,
            "annual_flood_probability": annual_prob,
            "elevation_differential_m": round(elev_diff, 2),
            "historical_flood_events": hist_events,
            "flood_risk_index": round(flood_risk_idx, 3)
        }

        latency_ms = (time.perf_counter() - start_time) * 1000
        prov = self._create_provenance_tag(endpoint, params, raw_result, cached=False, latency_ms=latency_ms, live=False)
        raw_result["provenance"] = prov
        self._write_cache(cache_key, raw_result, live=False)
        return MireyeFloodResponse(**raw_result)

    async def get_routing(self, origin: List[float], destination: List[float], mode: str = "heavy_truck") -> MireyeRoutingResponse:
        """
        Retrieves real road transit distance, travel time, and logistics route hazard score.
        """
        start_time = time.perf_counter()
        cache_key = self._get_od_cache_key(origin, destination)
        cached_data = self._read_cache(cache_key)

        endpoint = "/v1/proximity"
        params = {"origin": origin, "destination": destination, "mode": mode}

        if cached_data:
            latency_ms = (time.perf_counter() - start_time) * 1000
            prov = self._create_provenance_tag(endpoint, params, cached_data, cached=True, latency_ms=latency_ms, live=self._live_flags.get(cache_key, False))
            cached_data["provenance"] = prov
            return MireyeRoutingResponse(**cached_data)

        # Real contract: POST https://api.mireye.com/v1/proximity, op "distance",
        # origins/destinations as "lat,lng" strings. See
        # https://docs.mireye.ai/api-reference/proximity.md
        # NOTE: proximity only returns distance + duration -- no cost or hazard-risk
        # field exists in the real API, and no route geometry either. Cost and route
        # risk stay our own freight-cost/corridor-risk model below, now seeded with the
        # REAL distance/duration whenever a live call succeeds.
        body = {
            "op": "distance",
            "origins": [f"{origin[0]},{origin[1]}"],
            "destinations": [f"{destination[0]},{destination[1]}"],
            "mode": "driving"
        }
        live = await self._post_json(endpoint, body)
        if live:
            legs = live.get("legs") or []
            leg = legs[0] if legs else None
            if leg and leg.get("flag") is None and leg.get("distance_km") is not None:
                road_distance_km = leg["distance_km"]
                duration_minutes = leg.get("duration_minutes")
                if duration_minutes is None and leg.get("duration_seconds") is not None:
                    duration_minutes = leg["duration_seconds"] / 60.0

                if duration_minutes is not None:
                    transport_cost = (road_distance_km * 2.15) + (duration_minutes * 0.65)
                    mid_lat = (origin[0] + destination[0]) / 2
                    mid_lon = (origin[1] + destination[1]) / 2
                    route_risk = 0.45 if (47.30 <= mid_lat <= 47.45 and -122.30 <= mid_lon <= -122.20) else 0.15

                    raw = {
                        "origin": origin,
                        "destination": destination,
                        "distance_km": round(road_distance_km, 2),
                        "duration_minutes": round(duration_minutes, 1),
                        "toll_cost_usd": 0.0,
                        "fuel_cost_usd": round(transport_cost, 2),
                        "route_risk_score": round(route_risk, 3),
                        # Mireye's proximity endpoint does not return route geometry.
                        "geometry_geojson": None
                    }

                    latency_ms = (time.perf_counter() - start_time) * 1000
                    prov = self._create_provenance_tag(endpoint, params, raw, cached=False, latency_ms=latency_ms, live=True)
                    raw["provenance"] = prov
                    self._write_cache(cache_key, raw, live=True)
                    return MireyeRoutingResponse(**raw)

        # Haversine distance with real-world road winding multiplier (1.28x - 1.42x)
        h_dist = haversine_distance_km(origin[0], origin[1], destination[0], destination[1])
        road_distance_km = max(1.5, h_dist * 1.32)

        # Average commercial truck speed in Puget Sound corridor: 55 km/h highway, 30 km/h urban
        self._refuse_simulation(
            endpoint,
            f"({origin[0]:.4f},{origin[1]:.4f} -> {destination[0]:.4f},{destination[1]:.4f})",
            "leg unreachable or missing duration" if live
            else (self.last_live_error or "no response"),
            fatal=False,
        )

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

        raw_result = {
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

        latency_ms = (time.perf_counter() - start_time) * 1000
        prov = self._create_provenance_tag(endpoint, params, raw_result, cached=False, latency_ms=latency_ms, live=False)
        raw_result["provenance"] = prov
        self._write_cache(cache_key, raw_result, live=False)
        return MireyeRoutingResponse(**raw_result)

    async def get_regional_hazards(self, region_name: str, bounding_box: List[float], known_hazards: Optional[List[Dict[str, Any]]] = None) -> MireyeHazardLayerResponse:
        """
        Retrieves flood hazard polygons and active road closures across the region.

        NOTE (verified against https://docs.mireye.ai, Aug 2026): Mireye's real API has
        no bounding-box / region-polygon endpoint. /v1/fetch and /v1/fetch/batch are
        point-based only (batch caps at 25 discrete lat/lng points), and every
        hazard-related field in the catalog is a per-point scalar or boolean flag (e.g.
        within_floodplain_polygon) -- no field returns polygon/geometry data at all.
        There is currently no live Mireye call this method could make to obtain the
        hazard_zones map polygons the frontend renders; this stays the seeded/simulated
        layer by necessity, not by omission. (get_flood_hazard() above IS wired to the
        real per-point flood signals Mireye does expose.)
        """
        start_time = time.perf_counter()
        cache_key = f"mireye:hazards:{region_name}"
        cached_data = self._read_cache(cache_key)

        endpoint = "/v1/hazard/layers"
        params = {"region_name": region_name, "bbox": bounding_box}

        if cached_data:
            latency_ms = (time.perf_counter() - start_time) * 1000
            prov = self._create_provenance_tag(endpoint, params, cached_data, cached=True, latency_ms=latency_ms, live=self._live_flags.get(cache_key, False))
            cached_data["provenance"] = prov
            return MireyeHazardLayerResponse(**cached_data)

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

        raw_result = {
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

        latency_ms = (time.perf_counter() - start_time) * 1000
        prov = self._create_provenance_tag(endpoint, params, raw_result, cached=False, latency_ms=latency_ms, live=False)
        raw_result["provenance"] = prov
        self._write_cache(cache_key, raw_result, live=False)
        return MireyeHazardLayerResponse(**raw_result)
