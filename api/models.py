#api/models.py
from django.db import models

class FuelStation(models.Model):
    station_id = models.IntegerField()
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rackId = models.IntegerField()
    price = models.FloatField()
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.city}, {self.state}"