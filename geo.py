import math
from typing import TypedDict

EARTH_RADIUS_KM = 6371.0
AVERAGE_SPEED_KMH = 25.0  # typical city motorbike speed
PREP_TIME_MINUTES = 10    # time for the restaurant to cook


class RiderLocation(TypedDict):
    """The parts of a rider that matching needs."""
    id: int
    latitude: float
    longitude: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in km between two points on Earth."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_eta_minutes(distance_km: float) -> int:
    """Cooking time plus riding time, rounded up to whole minutes."""
    riding_minutes = distance_km / AVERAGE_SPEED_KMH * 60
    return PREP_TIME_MINUTES + math.ceil(riding_minutes)


def find_nearest_rider(
    riders: list[RiderLocation], lat: float, lon: float, max_km: float
) -> tuple[RiderLocation, float] | None:
    """Return (closest rider, distance) within max_km, or None if nobody is close enough."""
    best: tuple[RiderLocation, float] | None = None
    for rider in riders:
        distance = haversine_km(lat, lon, rider["latitude"], rider["longitude"])
        if distance <= max_km and (best is None or distance < best[1]):
            best = (rider, distance)
    return best