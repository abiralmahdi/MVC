from django.db import models

# Create your models here.
class GlobalConfiguration(models.Model):
    report = models.BooleanField(default=True)
    dashboard = models.BooleanField(default=True)
    alarm = models.BooleanField(default=True)
    siteLocations = models.BooleanField(default=True)
    scada = models.BooleanField(default=False)
    billing = models.BooleanField(default=True)
    machineLearning = models.BooleanField(default=True)
    subscribed = models.BooleanField(default=True)
    treeType = models.CharField(max_length=100, default='hierarchy')

    @classmethod
    def load(cls):
        """Return the single configuration row, creating it with defaults if it is missing."""
        config = cls.objects.order_by('pk').first()
        if config is None:
            config = cls.objects.create()
        return config

