from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ProvenanceTag(BaseModel):
    """
    Provenance tag attached to every Mireye data point to ensure auditability and transparency.
    """
    endpoint: str = Field(..., description="The Mireye API endpoint queried")
    params: Dict[str, Any] = Field(default_factory=dict, description="Parameters sent in the query")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of the API call")
    response_hash: str = Field(..., description="SHA-256 hash or unique ID of the returned payload")
    cached: bool = Field(default=False, description="True if response was served from cache")
    latency_ms: float = Field(default=0.0, description="Latency of the Mireye call in milliseconds")


class MireyeTerrainResponse(BaseModel):
    lat: float
    lon: float
    elevation_m: float
    slope_degrees: float
    slope_pct: float
    aspect: str = "Flat"
    buildability_score: float = Field(..., description="0-1 score representing site suitability for construction")
    provenance: ProvenanceTag


class MireyeLandCoverResponse(BaseModel):
    lat: float
    lon: float
    radius_m: float
    primary_land_cover: str
    is_industrial_zoned: bool
    building_footprint_sqm: float
    available_parcel_sqm: float
    is_occupied: bool
    provenance: ProvenanceTag


class MireyeFloodResponse(BaseModel):
    lat: float
    lon: float
    flood_zone: str = Field(..., description="e.g. Zone X, Zone AE, Zone VE")
    annual_flood_probability: float = Field(..., description="Probability 0.0 - 1.0 (e.g., 0.01 for 100-yr)")
    elevation_differential_m: float
    historical_flood_events: int
    flood_risk_index: float = Field(..., description="Normalized 0-1 flood risk score")
    provenance: ProvenanceTag


class MireyeRoutingResponse(BaseModel):
    origin: List[float] = Field(..., description="[lat, lon]")
    destination: List[float] = Field(..., description="[lat, lon]")
    distance_km: float
    duration_minutes: float
    toll_cost_usd: float = 0.0
    fuel_cost_usd: float
    route_risk_score: float = Field(default=0.0, description="0-1 environmental/congestion hazard score")
    geometry_geojson: Optional[Dict[str, Any]] = None
    provenance: ProvenanceTag


class MireyeHazardPolygon(BaseModel):
    hazard_id: str
    hazard_type: str = "FloodZone"
    severity: str = "High"
    coordinates: List[List[List[float]]] = Field(..., description="GeoJSON polygon rings")
    description: str


class MireyeHazardLayerResponse(BaseModel):
    region_name: str
    bounding_box: List[float] = Field(..., description="[min_lat, min_lon, max_lat, max_lon]")
    hazards: List[MireyeHazardPolygon]
    active_road_closures: List[Dict[str, Any]] = Field(default_factory=list)
    provenance: ProvenanceTag
