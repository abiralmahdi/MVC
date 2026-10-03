"""Protocol drivers.

Every driver module exposes

    read(host: str, connection: dict, points: dict) -> (values: dict, errors: list)

where ``points`` is the cleaned mapping {measurement name: point} (see ``connections.protocols``),
``values`` holds the raw value for every point name (``None`` when that point could not be read) and
``errors`` lists human readable problems. Drivers never touch the database, so the poller can call
them from worker threads. Scaling and sanitising are applied here, once, for all protocols.

A driver may also expose ``discover(host, connection) -> list[dict]`` which lists what the device
offers (used by "Test connection" to help writing the mapping).
"""
import importlib
import logging

from .. import protocols

logger = logging.getLogger('connections')

MODULES = {
    protocols.MODBUS: 'connections.drivers.modbus_tcp',
    protocols.OPCUA: 'connections.drivers.opcua',
    protocols.BACNET: 'connections.drivers.bacnet',
    protocols.KNX: 'connections.drivers.knx',
    protocols.DALI: 'connections.drivers.dali',
    protocols.MBUS: 'connections.drivers.mbus',
    protocols.MQTT: 'connections.drivers.mqtt',
}


def get_driver(protocol):
    return importlib.import_module(MODULES[protocol])


def scale_value(value, scale):
    if isinstance(value, bool):
        value = 1.0 if value else 0.0
    if isinstance(value, (int, float)) and scale not in (None, 1, 1.0):
        return value * scale
    return value


def read_points(protocol, host, connection, mapping):
    """Validate the stored configuration and read every point. Returns (values, errors).

    Invalid points are reported and skipped; the rest are still read.
    """
    # Keys starting with "_" are run-time options for the driver (e.g. MQTT "_one_shot"), not stored settings.
    options = {k: v for k, v in (connection or {}).items() if str(k).startswith('_')}
    host, connection, errors = protocols.clean_connection(protocol, host, connection)
    connection.update(options)
    points, point_errors = protocols.clean_mapping(protocol, mapping or {})
    errors = list(errors) + point_errors
    if errors and not points:
        return {}, errors
    if not points:
        return {}, errors + ['no data points configured']
    if any(e for e in errors if not e.startswith('"')):
        return {name: None for name in points}, errors
    try:
        driver = get_driver(protocol)
    except ImportError as exc:
        return {name: None for name in points}, errors + [f'{protocols.label(protocol)} driver unavailable: {exc}']
    try:
        values, driver_errors = driver.read(host, connection, points)
    except Exception as exc:  # a driver bug must not stop the poller
        logger.exception('%s driver failed', protocol)
        return {name: None for name in points}, errors + [f'{protocols.label(protocol)} read failed: {exc}']
    result = {}
    for name, point in points.items():
        result[name] = scale_value(values.get(name), point.get('scale', 1))
    return result, errors + list(driver_errors)


def discover(protocol, host, connection):
    """Optional device listing (for example the data records of an M-Bus meter)."""
    options = {k: v for k, v in (connection or {}).items() if str(k).startswith('_')}
    host, connection, errors = protocols.clean_connection(protocol, host, connection)
    connection.update(options)
    if errors:
        return None, errors
    driver = get_driver(protocol)
    if not hasattr(driver, 'discover'):
        return None, []
    try:
        return driver.discover(host, connection), []
    except Exception as exc:
        return None, [f'discovery failed: {exc}']
