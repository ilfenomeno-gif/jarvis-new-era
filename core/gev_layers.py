"""JARVIS names and GEV layer IDs exposed to local control actions."""

GEV_LAYER_IDS = {
    "satellites": "satellites",
    "flights": "flights",
    "military_flights": "military",
    "local_adsb": "local-adsb",
    "vessels": "ais-live-vessels",
    "traffic": "traffic",
    "transit": "transit",
    "bikeshare": "bikeshare",
    "cameras": "cctv",
    "recent_imagery": "recent-imagery",
    "alpr_cameras": "alpr-cameras",
    "installations": "military-installations",
    "datacenters": "local-datacenters",
    "submarine_cables": "telegeography-submarine-cables",
    "dams": "local-dams",
    "space_missions": "rocket-launches",
    "earthquakes": "earthquakes",
    "active_fires": "local-firms",
    "fire_perimeters": "fire-perimeters",
    "wind": "wind",
    "rain_radar": "weather-radar",
    "satellite_clouds": "weather-satellite",
    "lightning_density": "weather-lightning",
    "cyclone_advisories": "weather-cyclones",
    "directions": "directions",
    "radio": "radio",
}

GEV_LAYER_LABELS = {
    "satellites": "Satellites",
    "flights": "Live Flights",
    "military_flights": "Military Flights",
    "local_adsb": "Local ADS-B",
    "vessels": "Live Vessels",
    "traffic": "Street Traffic",
    "transit": "Transit",
    "bikeshare": "Bike Share",
    "cameras": "Cameras",
    "recent_imagery": "Recent Imagery",
    "alpr_cameras": "Mapped ALPR Cameras",
    "installations": "Mapped Installations",
    "datacenters": "Data Centers",
    "submarine_cables": "Submarine Cables",
    "dams": "Dams",
    "space_missions": "Space Missions",
    "earthquakes": "Earthquakes",
    "active_fires": "Active Fires",
    "fire_perimeters": "Fire Perimeters",
    "wind": "Wind",
    "rain_radar": "Rain Radar",
    "satellite_clouds": "Satellite Clouds",
    "lightning_density": "Lightning Density",
    "cyclone_advisories": "Cyclone Advisories",
    "directions": "Directions",
    "radio": "Radio",
}

_GEV_LAYER_ALIASES = {
    "military": "military_flights",
    "local-adsb": "local_adsb",
    "live_vessels": "vessels",
    "street_traffic": "traffic",
    "bike_share": "bikeshare",
    "cctv": "cameras",
    "mapped_alpr_cameras": "alpr_cameras",
    "mapped_installations": "installations",
    "data_centers": "datacenters",
    "dams_infrastructure": "dams",
    "launches": "space_missions",
    "fires": "active_fires",
    "fire-perimeters": "fire_perimeters",
    "rain": "rain_radar",
    "clouds": "satellite_clouds",
    "lightning": "lightning_density",
    "cyclones": "cyclone_advisories",
}


def normalize_gev_layer(value: str) -> str | None:
    """Return a known layer key for a canonical name or supported alias."""
    normalized = value.strip().casefold().replace(" ", "_")
    normalized = _GEV_LAYER_ALIASES.get(normalized, normalized)
    return normalized if normalized in GEV_LAYER_IDS else None
