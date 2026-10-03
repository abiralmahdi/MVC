"""Store motor readings from the PLCs so the model can see how motors change over time."""
import logging
import math

from django.utils import timezone

logger = logging.getLogger('ml')


def numeric_fields(status):
    values = {}
    for name, value in (status.get('motor') or {}).items():
        if isinstance(value, bool):
            values[name] = int(value)
        elif isinstance(value, (int, float)) and math.isfinite(value):
            values[name] = round(float(value), 3)
    if status.get('running') is not None:
        values['Running'] = int(bool(status['running']))
    return values


def record_motor_readings():
    """Read every motor once and store its numeric values. Returns (stored, failed)."""
    from scada.models import Motor
    from scada.views import _status_for_motors

    from .models import MotorReading

    motors = list(Motor.objects.prefetch_related('tank'))
    if not motors:
        return 0, 0
    now = timezone.now()
    stored = failed = 0
    for motor_id, status in _status_for_motors(motors).items():
        values = numeric_fields(status) if 'error' not in status else {}
        if values:
            MotorReading.objects.create(motor_id=motor_id, timestamp=now, data=values)
            stored += 1
        else:
            failed += 1
    return stored, failed
