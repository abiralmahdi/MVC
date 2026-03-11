from django.db import models

# Create your models here.
class GlobalConfiguration(models.Model):
    report = models.BooleanField(default=True)
    dashboard = models.BooleanField(default=True)
    alarm = models.BooleanField(default=True)
    siteLocations = models.BooleanField(default=True)
    scada = models.BooleanField(default=False)
    billing = models.BooleanField(default=True)
    subscribed = models.BooleanField(default=True)
    treeType = models.CharField(max_length=100, default='hierarchy')


