from django.db import models
from dashboard.models import *
from dynamic.models import *


# Create your models here.
class AlarmsRange(models.Model):
    measurement = models.ForeignKey(
        Measurements, related_name='alarmsRange', on_delete=models.CASCADE)
    meter = models.ForeignKey(
        Meters, related_name='alarmsRange', on_delete=models.CASCADE)
    minValue = models.FloatField(null=True, blank=True)
    maxValue = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"{self.meter.name} - {self.measurement.name}"

    
class Alarms(models.Model):
    measurement = models.ForeignKey(Measurements, related_name='alarms', on_delete=models.CASCADE)
    meter = models.ForeignKey(Meters, related_name='alarms', on_delete=models.CASCADE)
    value = models.FloatField()
    date = models.DateTimeField(auto_now_add=True)
    alarmType = models.CharField(max_length=100)
    acknowledged = models.BooleanField(default=False)
    desc = models.CharField(max_length=1000, default='')
    
    def __str__(self):
        return self.meter.name + " - " + self.measurement.name + " - " + str(self.value) + " - " + str(self.date)