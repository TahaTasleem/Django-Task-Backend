#api/management/commands/load_fuel_data.py
from django.core.management.base import BaseCommand
from api.models import FuelStation
import pandas as pd
import requests
import time
from django.db import transaction
import re
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict
import numpy as np

def clean_address(address: str) -> str:
    """Clean and simplify highway addresses for better geocoding."""
    address = re.sub(r'EXIT\s+\d+\s*&?\s*', '', address)
    address = re.sub(r'I-(\d+)', r'Interstate \1', address)
    address = re.sub(r'(?:US|SR|STATE ROUTE)-\d+\s*&?\s*', '', address)
    address = re.sub(r'\s+', ' ', address)
    return address.strip()

def geocode_batch(locations: List[Dict]) -> List[Dict]:
    """Geocode a batch of locations."""
    url = "https://nominatim.openstreetmap.org/search"
    headers = {'User-Agent': 'FuelOptimizationApp/1.0'}
    results = []
    
    for loc in locations:
        params = {
            'city': loc['city'],
            'state': loc['state'],
            'country': 'USA',
            'format': 'json',
            'limit': 1
        }
        
        try:
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if data and len(data) > 0:
                loc['latitude'] = float(data[0]['lat'])
                loc['longitude'] = float(data[0]['lon'])
            else:
                cleaned_address = clean_address(loc['address'])
                params = {
                    'q': f"{cleaned_address}, {loc['city']}, {loc['state']}, USA",
                    'format': 'json',
                    'limit': 1
                }
                
                response = requests.get(url, params=params, headers=headers)
                data = response.json()
                
                if data and len(data) > 0:
                    loc['latitude'] = float(data[0]['lat'])
                    loc['longitude'] = float(data[0]['lon'])
                else:
                    loc['latitude'] = None
                    loc['longitude'] = None
            
            time.sleep(0.5) 
            
        except Exception as e:
            print(f"Error geocoding {loc['city']}, {loc['state']}: {str(e)}")
            loc['latitude'] = None
            loc['longitude'] = None
            
        results.append(loc)
    
    return results

class Command(BaseCommand):
    help = 'Load fuel station data from CSV and geocode addresses'

    def handle(self, *args, **options):
        self.stdout.write('Clearing existing data...')
        FuelStation.objects.all().delete()
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        csv_file_path = os.path.join(script_dir, "fuel_prices.csv")

        self.stdout.write('Loading data from CSV...')
        try:
            df = pd.read_csv(csv_file_path)
            df = df.dropna(subset=['Retail Price'])
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error loading CSV file: {str(e)}'))
            return

        # Prepare data for batch processing
        locations = []
        for _, row in df.iterrows():
            locations.append({
                'station_id': row['OPIS Truckstop ID'],
                'name': row['Truckstop Name'],
                'address': row['Address'].strip(),
                'city': row['City'].strip(),
                'state': row['State'].strip(),
                'rackId': row['Rack ID'],
                'price': float(row['Retail Price'])
            })

        # Split into batches for parallel processing
        batch_size = 50
        batches = np.array_split(locations, len(locations) // batch_size + 1)
        
        success_count = 0
        error_count = 0
        processed_locations = []

        self.stdout.write(f'Processing {len(locations)} locations in {len(batches)} batches...')

        # Process batches in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_batch = {executor.submit(geocode_batch, batch.tolist()): batch 
                             for batch in batches}
            
            for future in as_completed(future_to_batch):
                try:
                    results = future.result()
                    processed_locations.extend(results)
           
                    for loc in results:
                        if loc.get('latitude') is not None:
                            success_count += 1
                        else:
                            error_count += 1
                            
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Processed batch. Current progress: {success_count + error_count}/{len(locations)}'
                        )
                    )
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Batch processing error: {str(e)}'))

        self.stdout.write('Saving to database...')
        stations_to_create = []
        for loc in processed_locations:
            if loc.get('latitude') is not None:
                stations_to_create.append(
                    FuelStation(
                        station_id=loc['station_id'],
                        name=loc['name'],
                        address=loc['address'],
                        city=loc['city'],
                        state=loc['state'],
                        rackId=loc['rackId'],
                        price=loc['price'],
                        latitude=loc['latitude'],
                        longitude=loc['longitude']
                    )
                )

        batch_size = 500
        for i in range(0, len(stations_to_create), batch_size):
            batch = stations_to_create[i:i + batch_size]
            FuelStation.objects.bulk_create(batch)
            self.stdout.write(f'Saved batch {i//batch_size + 1}/{len(stations_to_create)//batch_size + 1}')

        self.stdout.write(
            self.style.SUCCESS(
                f'\nFinished loading data.\nSuccessfully loaded: {success_count} stations\n'
                f'Errors: {error_count}\nTotal processed: {success_count + error_count}'
            )
        )