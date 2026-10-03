"""Synthetic motor telemetry for demos (the demo PLCs are on unreachable test addresses)."""
import math
import random
from datetime import timedelta

from django.utils import timezone

DEMO_FIELDS = {
    'Speed (rpm)': ['INT', 8, 0],
    'Motor current (A)': ['REAL', 10, 0],
    'Run hours': ['DINT', 14, 0],
    'Winding temperature (°C)': ['REAL', 18, 0],
    'Vibration (mm/s)': ['REAL', 22, 0],
}
DEMO_DATA_SIZE = 26


def generate_motor_telemetry(motors, days=45, degrading=None, warming=None, seed=11, now=None):
    """Hourly readings for ``motors``.

    degrading: motor whose bearing is failing over the last 12 days (vibration, temperature and current rise).
    warming: motor with a mild temperature rise over the last 5 days.
    Returns the number of readings created.
    """
    from .models import MotorReading

    rng = random.Random(seed)
    now = (now or timezone.now()).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)
    created = 0
    for index, motor in enumerate(motors):
        rated_current = [42.0, 28.0, 18.0][index % 3]
        run_hours = 18000 + 3500 * index
        rows = []
        t = start
        while t <= now:
            local = timezone.localtime(t)
            daily = 0.92 + 0.08 * math.sin(math.pi * (local.hour - 6) / 12)
            ambient = 29 + 3 * math.sin(math.pi * (local.hour - 9) / 12)
            current = rated_current * daily * rng.uniform(0.97, 1.03)
            speed = 1478 - 6 * daily + rng.uniform(-3, 3)
            temperature = ambient + 30 * daily + rng.uniform(-1.2, 1.2)
            vibration = 2.2 + rng.uniform(-0.25, 0.25)
            days_left = (now - t).total_seconds() / 86400
            if motor == degrading and days_left < 12:
                k = ((12 - days_left) / 12) ** 2       # accelerating wear
                vibration += 5.8 * k + rng.uniform(-0.3, 0.3) * k
                temperature += 24 * k
                current *= 1 + 0.2 * k
                speed -= 22 * k
            if motor == warming and days_left < 5:
                temperature += 7 * (5 - days_left) / 5
            run_hours += 1
            rows.append(MotorReading(motor=motor, timestamp=t, data={
                'Speed (rpm)': round(speed, 1), 'Motor current (A)': round(current, 2), 'Run hours': run_hours,
                'Winding temperature (°C)': round(temperature, 1), 'Vibration (mm/s)': round(vibration, 2), 'Running': 1,
            }))
            t += timedelta(hours=1)
        MotorReading.objects.bulk_create(rows, batch_size=1000)
        created += len(rows)
    return created
