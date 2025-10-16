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
    meter = models.ForeignKey(Meters, related_name='measurements', on_delete=models.CASCADE, null=True, blank=True)
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
    












'''


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

give me a python script where the meters model will be populated. Here, for each area (floor) starting from GF, there will be 3 meters in each floor upto 31F. In the area/floor name RF, there will be 1 meter. The meterType will be 'Electricity Meter' and the loadType will be a LoadType instance with name 'Mixed Load'.
The names of the meters will be like GF.1, GF.2, GF.3, 1F.1, 1F.2, 1F.3 etc. The ip will be 192.168.1.254 and the slave id will increment for each meter starting from 1.  The register mapping JSON will be exactly the following:
{
    "Power Factor": 53,
    "Total Active Power": 57,
    "Total kWh DG": 73,
    "DG Sensing": 127,
    "CT Secondary":1,
    "CT Primary": 2,
    "PT Secondary": 3,
    "PT Primary": 4

}

'''