#api/services.py
import requests
import numpy as np
from typing import List, Dict, Tuple
from datetime import datetime
from django.conf import settings
from .models import FuelStation
from math import radians, sin, cos, sqrt, atan2
import logging
from django.db.models import F
from geopy.distance import geodesic 
import math
logger = logging.getLogger(__name__)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in kilometers."""
    R = 6371  # Earth's radius
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c * 0.621371  # Convert to miles

def geocode_address(address: str) -> Tuple[float, float]:
    """Geocode an address using Nominatim API."""
    url = f"https://nominatim.openstreetmap.org/search"
    params = {
        'q': address,
        'format': 'json',
        'limit': 1
    }
    headers = {
        'User-Agent': 'FuelOptimizationApp/1.0'
    }
    
    response = requests.get(url, params=params, headers=headers)
    data = response.json()
    
    if not data:
        raise ValueError(f"Could not geocode address: {address}")
        
    return float(data[0]['lat']), float(data[0]['lon'])

def get_route(start_coords: Tuple[float, float], end_coords: Tuple[float, float]) -> Dict:
    """Get route using OSRM API."""
    url = f"http://router.project-osrm.org/route/v1/driving/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}"
    params = {
        'overview': 'full',
        'geometries': 'geojson'
    }
    
    response = requests.get(url, params=params)
    return response.json()

def is_on_route(route, lat, lon, threshold=0.5):
    """Check if a fuel station is near the calculated route."""
    for point in route['routes'][0]['geometry']['coordinates']:
        route_lat, route_lon = point[1], point[0]
        if haversine_distance(route_lat, route_lon, lat, lon) <= threshold:
            return True
    return False



def find_optimal_fuel_stops(route: Dict, max_range: float = 500) -> List[Dict]:
    """Find optimal fuel stops along the route while reducing computation time."""

    # Extract route coordinates
    route_coords = route['routes'][0]['geometry']['coordinates']
    route_points = [(lon, lat) for lat, lon in route_coords]

    # Initialize variables
    current_range = max_range
    current_position = route_points[0]
    fuel_stops = []
    total_distance = route['routes'][0]['distance'] * 0.000621371  # Convert to miles

    def haversine(lat1, lon1, lat2, lon2):
        """Haversine formula to calculate distance between two lat/lon points (in miles)."""
        R = 3958.8  # Radius of Earth in miles
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        return R * (2 * atan2(sqrt(a), sqrt(1 - a)))

    while current_range < total_distance:
        # Get all stations that are within a reasonable bounding box
        lat_min, lat_max = current_position[1] - 1, current_position[1] + 1
        lon_min, lon_max = current_position[0] - 1, current_position[0] + 1
        
        nearby_stations = FuelStation.objects.filter(
            latitude__gte=lat_min, latitude__lte=lat_max,
            longitude__gte=lon_min, longitude__lte=lon_max
        )

        # Calculate distance for only filtered stations
        station_list = []
        for station in nearby_stations:
            distance = haversine(current_position[1], current_position[0], station.latitude, station.longitude)
            if distance <= current_range:
                station_list.append({
                    'station': station,
                    'distance': distance,
                    'price': station.price
                })

        if not station_list:
            raise ValueError("No reachable fuel stations found within range.")

        # Find the cheapest station within reach
        optimal_station = min(station_list, key=lambda x: x['price'])

        # Add to fuel stops
        fuel_stops.append({
            'name': optimal_station['station'].name,
            'address': optimal_station['station'].address,
            'price': optimal_station['station'].price,
            'latitude': optimal_station['station'].latitude,
            'longitude': optimal_station['station'].longitude
        })

        # Move to next refueling position
        current_position = (optimal_station['station'].longitude, optimal_station['station'].latitude)
        current_range = max_range
        total_distance -= optimal_station['distance']

    return fuel_stops