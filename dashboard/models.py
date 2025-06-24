from django.db import models
from home.models import *
from dynamic.models import *


# Create your models here.
class Dashboard(models.Model):
    title = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    site = models.ForeignKey(Site, related_name="dashboard", on_delete=models.CASCADE)


    def __str__(self):
        return self.title



class Gadgets(models.Model):
    name = models.CharField(max_length=100)
    gadget_type = models.CharField(max_length=100)
    dashboard = models.ForeignKey(Dashboard, related_name='gadgets', on_delete=models.CASCADE)
    meters = models.ManyToManyField(Meters, related_name='gadgets')  
    measurement = models.ManyToManyField(Measurements, related_name='gadgets')
    def __str__(self):
        return self.name
    
class Files(models.Model):
    name = models.CharField(max_length=100)
    file = models.FileField(upload_to='data/')
    created_at = models.DateTimeField(auto_now_add=True)
    meter = models.ForeignKey(Meters, related_name='files', on_delete=models.CASCADE)
    def __str__(self):
        return self.name + " - " + self.meter.name + " - " + self.meter.area.name + " - " + self.meter.area.building.name + " - " + self.meter.area.building.site.name
    

class MeterReading(models.Model):
    meter = models.ForeignKey(Meters, related_name='data', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=False, db_index=True)
    data = models.JSONField()
    def __str__(self):
        return f"{self.meter.name} - {self.timestamp.strftime('%d-%m-%y %H:%M:%S')}"


class LatestMeterReading(models.Model):
    meter = models.ForeignKey(Meters, related_name='dataLatest', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=False, db_index=True)
    data = models.JSONField()
    def __str__(self):
        return f"{self.meter.name} - {self.timestamp.strftime('%d-%m-%y %H:%M:%S')}"


# models.py
class MeterReadingAggregate(models.Model):
    meter = models.ForeignKey(Meters, on_delete=models.CASCADE)
    measurement = models.CharField(max_length=100)
    period_type = models.CharField(max_length=20, choices=[
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('3monthly', '3Monthly'),
        ('6monthly', '6Monthly'),
        ('yearly', 'Yearly'),
    ])
    start_date = models.DateField()  # e.g., 2025-06-01
    average_value = models.FloatField()

    class Meta:
        unique_together = ('meter', 'measurement', 'period_type', 'start_date')

    def __str__(self):
        return f"{self.meter.name} - {self.measurement} - {self.period_type} - {self.start_date} - {self.average_value}"
