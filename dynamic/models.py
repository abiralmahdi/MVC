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
    image = models.FileField(upload_to="media/buildingImages", null=True, blank=True)
    def __str__(self):
        return self.name + " - " + self.site.name


class Areas(models.Model):
    name = models.CharField(max_length=100)
    building = models.ForeignKey(Buildings, related_name="areas", on_delete=models.CASCADE)
    image = models.FileField(upload_to="media/areaImages", null=True, blank=True)
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
    registerMapping = models.JSONField(default={}, null = True, blank = True)
    unit_id = models.IntegerField(default=1)
    
    def __str__(self):
        return self.name + ' - ' + self.meterType
    
    def delete(self, *args, **kwargs):
        # Clear ManyToMany relations before deletion
        self.gadgets.clear()
        super().delete(*args, **kwargs)


class Masters(models.Model):
    masterType = models.CharField(max_length=100)
    ip = models.CharField(max_length=100, null=True, blank=True)
    port = models.IntegerField(null=True, blank=True)



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


class Units(models.Model):
    name = models.CharField(max_length=100, null=True, blank=True)
    measurement = models.ForeignKey(Measurements, on_delete=models.CASCADE, null=True, blank=True, related_name='units')

    def __str__(self):
        return self.name