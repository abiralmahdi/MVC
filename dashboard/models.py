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
    measurement = models.ForeignKey(Measurements, related_name='gadgets', on_delete=models.CASCADE)
    def __str__(self):
        return self.name
