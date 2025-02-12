# api/views.py
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .services import geocode_address, get_route
import logging
from django.http import JsonResponse
from api.models import FuelStation
from api.services import haversine_distance as haversine

logger = logging.getLogger(__name__)

MAX_FUEL_RANGE = 500 
MIN_PROGRESS_DISTANCE = 50  
MPG = 10 # miles per gallon

class OptimalRouteView(APIView):
    @swagger_auto_schema(
        operation_description="Get an optimized route with fuel stops",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=["start_address", "end_address"],
            properties={
                "start_address": openapi.Schema(type=openapi.TYPE_STRING, description="Starting address"),
                "end_address": openapi.Schema(type=openapi.TYPE_STRING, description="Ending address"),
            },
        ),
        responses={
            200: openapi.Response("Success", openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "route": openapi.Schema(type=openapi.TYPE_STRING, description="Route geometry"),
                    "fuel_stops": openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Items(
                        type=openapi.TYPE_OBJECT,
                        properties={
                            "name": openapi.Schema(type=openapi.TYPE_STRING),
                            "latitude": openapi.Schema(type=openapi.TYPE_NUMBER),
                            "longitude": openapi.Schema(type=openapi.TYPE_NUMBER),
                            "fuel_price_per_gallon": openapi.Schema(type=openapi.TYPE_NUMBER),
                            "fuel_cost": openapi.Schema(type=openapi.TYPE_NUMBER),
                        },
                    )),
                    "total_distance": openapi.Schema(type=openapi.TYPE_NUMBER),
                    "total_fuel_cost": openapi.Schema(type=openapi.TYPE_NUMBER),
                },
            )),
            400: "Bad Request",
            500: "Internal Server Error",
        },
    )
    def post(self, request):
        try:
            start_address = request.data.get('start_address')
            end_address = request.data.get('end_address')

            logger.info(f"Processing route from {start_address} to {end_address}")

            if not start_address or not end_address:
                return Response(
                    {'error': 'Both start and end addresses are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Geocode addresses
            start_coords = geocode_address(start_address)
            end_coords = geocode_address(end_address)
            logger.info(f"Geocoded coordinates: {start_coords} to {end_coords}")

            # Get route
            route = get_route(start_coords, end_coords)
            total_distance = route['routes'][0]['distance'] * 0.000621371 

            fuel_stops = []
            current_lat, current_lon = start_coords
            total_fuel_cost = 0
            remaining_distance = total_distance
            fuel_remaining = MAX_FUEL_RANGE 

            while remaining_distance > 0:
                # Get all fuel stations within MAX_FUEL_RANGE
                reachable_stations = [
                    station for station in FuelStation.objects.all()
                    if haversine(current_lat, current_lon, station.latitude, station.longitude) <= fuel_remaining
                    and haversine(station.latitude, station.longitude, end_coords[0], end_coords[1]) < remaining_distance
                ]

                if not reachable_stations:
                    return Response(
                        {'error': 'No reachable fuel stations found within range.'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

                # Sort stations by price, ensuring significant progress
                sorted_stations = sorted(reachable_stations, key=lambda s: s.price)
                next_station = None

                for station in sorted_stations:
                    distance_to_station = haversine(current_lat, current_lon, station.latitude, station.longitude)
                    if distance_to_station >= min(MIN_PROGRESS_DISTANCE, remaining_distance * 0.1):
                        next_station = station
                        break

                if not next_station:
                    return Response(
                        {'error': 'No significant progress possible. Adjusting selection.'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

                # fuel cost
                distance_to_station = haversine(current_lat, current_lon, next_station.latitude, next_station.longitude)
                fuel_needed = distance_to_station / MPG
                fuel_cost = fuel_needed * next_station.price
                total_fuel_cost += fuel_cost

                fuel_stops.append({
                    'name': next_station.name,
                    'latitude': next_station.latitude,
                    'longitude': next_station.longitude,
                    'distance_from_last_stop': round(distance_to_station, 2),
                    'fuel_price_per_gallon': next_station.price,
                    'fuel_cost': round(fuel_cost, 2)
                })

                current_lat, current_lon = next_station.latitude, next_station.longitude
                fuel_remaining = MAX_FUEL_RANGE 
                remaining_distance -= distance_to_station

                logger.info(f"Stopping at {next_station.name}, Distance: {distance_to_station:.2f} miles, Fuel Cost: ${fuel_cost:.2f}")

                if remaining_distance <= MAX_FUEL_RANGE: 
                    fuel_stops.append({'name': 'Final Destination', 'latitude': end_coords[0], 'longitude': end_coords[1]})
                    logger.info("Reached final destination.")
                    break

            return Response({
                'route': route['routes'][0]['geometry'],
                'fuel_stops': fuel_stops,
                'total_distance': total_distance,
                'total_fuel_cost': round(total_fuel_cost, 2)
            })

        except Exception as e:
            logger.error(f"Exception: {e}", exc_info=True)
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )