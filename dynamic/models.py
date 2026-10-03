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
    name = models.CharField(max_length=100, null = True, blank = True)
    ip = models.CharField(max_length=100, null = True, blank = True)
    area = models.ForeignKey(Areas, related_name='meters', on_delete=models.CASCADE, null = True, blank = True)
    loadType = models.ForeignKey(LoadType, related_name='meters', on_delete=models.CASCADE, null = True, blank = True)
    meterType = models.CharField(max_length=100, null = True, blank = True)
    ecological = models.BooleanField(default=False,)
    registerMapping = models.JSONField(default=dict, null = True, blank = True)
    # Field protocol (see connections.protocols) and its connection settings, e.g. {"port": 502, "unit_id": 1}
    protocol = models.CharField(max_length=20, default='modbus', choices=[
        ('modbus', 'Modbus TCP'), ('bacnet', 'BACnet/IP'), ('knx', 'KNX'), ('dali', 'DALI / DALI-2'),
        ('mbus', 'M-Bus'), ('mqtt', 'MQTT'), ('opcua', 'OPC UA'),
    ])
    connection = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.name or 'Meter'} - {self.meterType or 'Unknown type'}"

    @property
    def protocol_label(self):
        return self.get_protocol_display()

    @property
    def address_summary(self):
        """Where the meter is reached, e.g. "192.0.2.11:502 · unit 1" or "COM3 · primary 5"."""
        conn = self.connection or {}
        if self.protocol == 'mbus' and conn.get('transport') == 'serial':
            where = f"{conn.get('serial_port', '')} @ {conn.get('baudrate', '')} Bd"
        else:
            where = f"{self.ip or ''}:{conn['port']}" if conn.get('port') else (self.ip or '')
        extra = {
            'modbus': f"unit {conn.get('unit_id', 1)}",
            'bacnet': f"net {conn.get('network')} mac {conn.get('mac')}" if conn.get('network') else '',
            'knx': (conn.get('connection_type') or '').replace('_', ' '),
            'mbus': (f"secondary {conn.get('secondary_address')}" if conn.get('address_mode') == 'secondary'
                     else f"primary {conn.get('primary_address', '')}"),
            'opcua': conn.get('path') or '',
            'mqtt': 'TLS' if conn.get('tls') else '',
        }.get(self.protocol, '')
        return f"{where} · {extra}" if extra else where
    
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
        return self.name or ''
