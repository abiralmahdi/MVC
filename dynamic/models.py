from django.db import models

# Create your models here.
class Site(models.Model):
    name = models.CharField(max_length=100)
    latitude = models.CharField(max_length=1000)
    longitude = models.CharField(max_length=1000)
    def __str__(self):
        return self.name

class Buildings(models.Model):
    name = models.CharField(max_length=100)
    site = models.ForeignKey(Site, related_name='buildings', on_delete=models.CASCADE)
    def __str__(self):
        return self.name + " - " + self.site.name

class Areas(models.Model):
    name = models.CharField(max_length=100)
    building = models.ForeignKey(Buildings, related_name="areas", on_delete=models.CASCADE)
    def __str__(self):
        return self.name + " - " + self.building.name + " - " + self.building.site.name


class LoadType(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

class Meters(models.Model):
    name = models.CharField(max_length=100,)
    ip = models.CharField(max_length=100,)
    area = models.ForeignKey(Areas, related_name='meters', on_delete=models.CASCADE,)
    loadType = models.ForeignKey(LoadType, related_name='meters', on_delete=models.CASCADE,)
    meterType = models.CharField(max_length=100,)
    ecological = models.BooleanField(default=False)
    def __str__(self):
        return self.name + ' - ' + self.meterType



class Measurements(models.Model):
    name = models.CharField(max_length=100)
    meter = models.ForeignKey(Meters, related_name='measurements', on_delete=models.CASCADE)
    meterType = models.CharField(max_length=100, default="")
    

    def save(self, *args, **kwargs):
        if self.meter:
            self.meterType = self.meter.meterType
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
