"""Reading meters over their field protocol and storing the values.

``poll_meter`` does network I/O only (no database access), so it can run in worker threads; the
protocol specific work is done by ``connections.drivers``. Results are persisted from a single thread
with ``store_poll_result``, which avoids SQLite "database is locked" errors and leaked per-thread DB
connections.
"""
import logging
import math
from dataclasses import dataclass, field

from django.utils import timezone

from . import drivers, protocols

logger = logging.getLogger('connections')


@dataclass
class PollResult:
    meter_id: int
    meter_name: str
    timestamp: object = None
    data: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    protocol: str = protocols.MODBUS

    @property
    def ok(self):
        return any(value is not None for value in self.data.values())


def sanitize_value(value):
    """Round numbers and replace NaN/inf with None (JSON cannot store them)."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 3)
    return None if value is None else value


def sanitize_dict(d):
    return {k: sanitize_value(v) for k, v in d.items()}


def poll_meter(meter, one_shot=False):
    """Read one meter with the driver of its protocol.

    ``one_shot`` asks push-based protocols (MQTT) not to keep a background subscription open;
    used for "Test connection" from the web application.
    """
    protocol = meter.protocol or protocols.MODBUS
    result = PollResult(meter.id, meter.name, timestamp=timezone.now(), protocol=protocol)
    connection = dict(meter.connection or {})
    if one_shot:
        connection['_one_shot'] = True
    values, errors = drivers.read_points(protocol, meter.ip, connection, meter.registerMapping)
    result.data = sanitize_dict(values)
    result.errors = errors
    result.timestamp = timezone.now()
    return result


def store_poll_result(meter, result):
    """Persist a successful poll. Returns True when a reading was stored."""
    from dashboard.models import store_reading

    for error in result.errors:
        logger.warning("%s: %s", meter.name, error)
    readable = {k: v for k, v in result.data.items() if v is not None}
    if not readable:
        logger.warning("%s: no values read, nothing stored", meter.name)
        return False
    store_reading(meter, result.data, timestamp=result.timestamp)
    return True


# Backwards compatible helpers used by older scripts --------------------------

def read_meter_data_all(meter):
    return store_poll_result(meter, poll_meter(meter))


read_meter_data = read_meter_data_scada = read_meter_data_all


def main():
    from dynamic.models import Meters

    meters = Meters.objects.all()
    if not meters.exists():
        logger.warning("No meters found in database.")
        return
    for meter in meters:
        stored = read_meter_data_all(meter)
        logger.info("%s meter '%s'", "Stored" if stored else "Skipped", meter.name)
