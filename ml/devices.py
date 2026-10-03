"""Connects every meter and motor of the plant to the predictive-maintenance model.

Each device's measurements are mapped onto the model's signal channels
(see ml.features). The mapping is automatic - it works from measurement
names - so meters and motors added later are supported without code changes.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

from dashboard.measurements import CUMULATIVE_FIELDS

from .features import CHANNELS

# Ordered candidates per channel: ('exact', name) beats ('kw', keyword). A measurement feeds one channel only.
CHANNEL_RULES = {
    'electrical': [
        ('exact', '3-Phase Average Voltage L-N'), ('exact', 'Voltage L1N'), ('exact', '3-Phase Average Voltage L-L'),
        ('kw', 'volt'), ('kw', 'current'), ('kw', 'amp'),
    ],
    'load': [
        ('exact', '3-Phase Average Current L-L'), ('exact', 'Current L1'),
        ('exact', 'Flow Rate'), ('exact', 'Gas Flow Rate'), ('exact', 'Steam Flow Rate'), ('exact', 'Fuel Consumption Rate'),
        ('kw', 'speed'), ('kw', 'rpm'), ('kw', 'flow'), ('kw', 'current'), ('kw', 'load'), ('kw', 'active power'),
        ('kw', 'consumption'), ('kw', 'power'),
    ],
    'process': [
        ('exact', 'Temperature'), ('exact', 'Steam Pressure'), ('exact', 'Gas Pressure'), ('exact', 'Pressure'),
        ('exact', 'CO2 Level'), ('exact', 'Power Factor'),
        ('kw', 'temp'), ('kw', 'pressure'), ('kw', 'level'), ('kw', 'humidity'), ('kw', 'co2'), ('kw', 'factor'),
    ],
    'stress': [
        ('exact', 'THD Voltage L1-L2'), ('exact', 'PM2.5'),
        ('kw', 'vib'), ('kw', 'thd'), ('kw', 'harmonic'), ('kw', 'torque'), ('kw', 'pm2'), ('kw', 'pm10'), ('kw', 'noise'),
    ],
}
EXCLUDE_KEYWORDS = ('setpoint', 'set point', 'hours', 'total', 'counter', 'energy', 'frequency', 'output')


def usable(name):
    lower = name.lower()
    return name not in CUMULATIVE_FIELDS and not any(k in lower for k in EXCLUDE_KEYWORDS)


def map_channels(names):
    """{channel: measurement name} for the given measurement names."""
    names = [n for n in dict.fromkeys(names) if n and usable(n)]
    used, mapping = set(), {}
    for channel in CHANNELS:
        for kind, pattern in CHANNEL_RULES[channel]:
            match = next(
                (n for n in names if n not in used and (n == pattern if kind == 'exact' else pattern in n.lower())),
                None,
            )
            if match:
                mapping[channel] = match
                used.add(match)
                break
    return mapping


@dataclass
class Device:
    kind: str                      # 'meter' | 'motor'
    obj: object
    name: str
    type_label: str
    location: str
    measurement_names: list = field(default_factory=list)

    @property
    def key(self):
        return f'{self.kind}-{self.obj.pk}'

    @property
    def channels(self):
        return map_channels(self.measurement_names)

    def history(self, since):
        """[(timestamp, data)] readings since ``since``, oldest first."""
        if self.kind == 'meter':
            from dashboard.models import MeterReading
            qs = MeterReading.objects.filter(meter=self.obj, timestamp__gte=since)
        else:
            from .models import MotorReading
            qs = MotorReading.objects.filter(motor=self.obj, timestamp__gte=since)
        return list(qs.order_by('timestamp').values_list('timestamp', 'data'))

    def alarm_times(self, since):
        """Alarm timestamps (meters raise alarms; motors have none, so the model treats them as unknown)."""
        if self.kind != 'meter':
            return None
        from alarms.models import Alarms
        return list(Alarms.objects.filter(meter=self.obj, date__gte=since).values_list('date', flat=True))


def all_devices():
    """Every meter and motor configured in the application."""
    from dynamic.models import Meters
    from scada.models import Motor

    from .models import MotorReading

    devices = []
    for meter in Meters.objects.select_related('area__building__site').prefetch_related('measurements').order_by('id'):
        names = [m.name for m in meter.measurements.all()] or list((meter.registerMapping or {}).keys())
        area = meter.area
        location = f"{area.building.site.name} / {area.building.name} / {area.name}" if area else '—'
        devices.append(Device('meter', meter, meter.name or f'Meter {meter.pk}', meter.meterType or 'Meter', location, names))

    since = timezone.now() - timedelta(days=31)
    for motor in Motor.objects.select_related('building__site').order_by('id'):
        names = list((motor.fields or {}).keys())
        latest = MotorReading.objects.filter(motor=motor, timestamp__gte=since).order_by('-timestamp').values_list('data', flat=True).first()
        names += [k for k in (latest or {}) if k not in names]
        location = f"{motor.building.site.name} / {motor.building.name}"
        devices.append(Device('motor', motor, motor.motorName, 'Motor (PLC)', location, names))
    return devices
