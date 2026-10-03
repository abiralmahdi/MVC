from django.db import models
from django.utils import timezone

from home.models import *
from dynamic.models import *
from utils.timeutils import local_str


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
    meters = models.ManyToManyField(Meters, related_name='gadgets', blank=True)
    measurement = models.ManyToManyField(Measurements, related_name='gadgets')
    building = models.ForeignKey(Buildings, on_delete=models.CASCADE, null=True, blank=True)
    area = models.ForeignKey(Areas, on_delete=models.CASCADE, null=True, blank=True)
    access = models.JSONField(default=list, blank=True)
    def __str__(self):
        return self.name


class Files(models.Model):
    name = models.CharField(max_length=100)
    file = models.FileField(upload_to='data/')
    created_at = models.DateTimeField(auto_now_add=True)
    meter = models.ForeignKey(Meters, related_name='files', on_delete=models.CASCADE)
    def __str__(self):
        return self.name + " - " + self.meter.name


def evaluate_alarms(meter, data):
    """Raise High/Low alarms for readings outside the configured range.

    While an alarm for the same meter, measurement and direction is still
    unacknowledged no duplicate is created (one alarm per event instead of one
    per poll); its value is updated when the excursion gets worse.
    """
    from alarms.models import AlarmsRange, Alarms
    from dashboard.measurements import to_number

    if not data:
        return []

    ranges = AlarmsRange.objects.filter(
        meter=meter, measurement__name__in=list(data.keys())
    ).select_related('measurement')

    raised = []
    for range_obj in ranges:
        name = range_obj.measurement.name
        value = to_number(data.get(name))
        if value is None:
            continue

        if range_obj.minValue is not None and value < range_obj.minValue:
            alarm_type, desc = "Low", f"{name} below min ({range_obj.minValue})"
            worse = lambda new, old: new < old
        elif range_obj.maxValue is not None and value > range_obj.maxValue:
            alarm_type, desc = "High", f"{name} above max ({range_obj.maxValue})"
            worse = lambda new, old: new > old
        else:
            continue

        active = Alarms.objects.filter(
            meter=meter,
            measurement__name=name,
            alarmType=alarm_type,
            acknowledged=False,
        ).first()
        if active:
            if worse(value, active.value):
                active.value = value
                active.save(update_fields=['value'])
            continue

        raised.append(Alarms.objects.create(
            meter=meter,
            measurement=range_obj.measurement,
            value=value,
            alarmType=alarm_type,
            desc=desc,
            acknowledged=False,
        ))
    return raised


class MeterReading(models.Model):
    meter = models.ForeignKey(Meters, related_name='data', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=False, db_index=True)
    data = models.JSONField()

    def __str__(self):
        return f"{self.meter.name} - {local_str(self.timestamp, '%d-%m-%y %H:%M:%S')}"

    def save(self, *args, **kwargs):
        if self.timestamp is None:
            self.timestamp = timezone.now()
        is_new = self._state.adding
        super().save(*args, **kwargs)
        # New alarms are stashed on the instance; store_reading() emails them (the live poll path only).
        self._raised_alarms = evaluate_alarms(self.meter, self.data) if is_new else []

    class Meta:
        indexes = [
            models.Index(fields=['meter', 'timestamp']),
        ]


class LatestMeterReading(models.Model):
    """The most recent reading of each meter (exactly one row per meter)."""
    meter = models.ForeignKey(Meters, related_name='dataLatest', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=False, db_index=True)
    data = models.JSONField()

    def __str__(self):
        return f"{self.meter.name} - {local_str(self.timestamp, '%d-%m-%y %H:%M:%S')}"

    @classmethod
    def record(cls, meter, timestamp, data):
        latest, _ = cls.objects.update_or_create(
            meter=meter, defaults={'timestamp': timestamp, 'data': data}
        )
        return latest

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['meter'], name='unique_latest_reading_per_meter'),
        ]


def store_reading(meter, data, timestamp=None):
    """Persist a polled reading: history row (raises alarms) + latest snapshot."""
    timestamp = timestamp or timezone.now()
    reading = MeterReading.objects.create(meter=meter, timestamp=timestamp, data=data)
    LatestMeterReading.record(meter, timestamp, data)
    raised = getattr(reading, '_raised_alarms', None)
    if raised:
        from home.notifications import notify_alarms
        notify_alarms(raised)
    return reading



class MeterReadingAggregate(models.Model):
    meter = models.ForeignKey(Meters, on_delete=models.CASCADE)
    period_type = models.CharField(max_length=20, choices=[
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('3monthly', '3Monthly'),
        ('6monthly', '6Monthly'),
        ('yearly', 'Yearly'),
    ])
    start_date = models.DateField()
    aggregateData = models.JSONField()

    def __str__(self):
        return f"{self.meter.name} -  {self.period_type} - {self.start_date}"

    class Meta:
        indexes = [
            models.Index(fields=['meter', 'period_type', 'start_date']),
        ]


class HierarchyDataAggregate(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE)
    period_type = models.CharField(max_length=20)
    start_date = models.DateField()
    data = models.JSONField()

    def __str__(self):
        return self.site.name + " - " + str(self.start_date) + " - " + self.period_type

    class Meta:
        unique_together = ('site', 'period_type', 'start_date')
