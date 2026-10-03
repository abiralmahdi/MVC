"""Siemens S7 access for motors and tanks (python-snap7).

* ``snap7`` is imported lazily so the web application still starts (and every
  non-SCADA page keeps working) on machines where the library is missing.
* Commands write only the single byte that contains the command bits, read
  immediately before writing. Writing back a whole DB area read seconds
  earlier could overwrite values the PLC program changed in the meantime.
"""
import logging
from contextlib import contextmanager

logger = logging.getLogger('scada')

CONNECT_TIMEOUT_MS = 1500
IO_TIMEOUT_MS = 2000
DEFAULT_DATA_SIZE = 256

# data type -> (reader name in snap7.util, needs bit offset)
FIELD_TYPES = {
    'BOOL': ('get_bool', True),
    'BYTE': ('get_byte', False),
    'INT': ('get_int', False),
    'UINT': ('get_uint', False),
    'WORD': ('get_word', False),
    'DINT': ('get_dint', False),
    'UDINT': ('get_udint', False),
    'DWORD': ('get_dword', False),
    'REAL': ('get_real', False),
    'FLOAT': ('get_real', False),   # alias kept for motors saved by the old form
    'LREAL': ('get_lreal', False),
    'STRING': ('get_string', False),
}


class PlcError(Exception):
    pass


def _snap7():
    try:
        import snap7
        import snap7.util  # noqa: F401
        import snap7.type  # noqa: F401
    except ImportError as exc:
        raise PlcError('python-snap7 is not installed on the server') from exc
    return snap7


def _db_area(snap7):
    area_enum = getattr(snap7.type, 'Area', None) or getattr(snap7.type, 'Areas')
    return area_enum.DB


@contextmanager
def plc_connection(ip, rack, slot):
    snap7 = _snap7()
    client = snap7.client.Client()
    try:
        for name, value in (('PingTimeout', CONNECT_TIMEOUT_MS), ('SendTimeout', IO_TIMEOUT_MS), ('RecvTimeout', IO_TIMEOUT_MS)):
            try:
                client.set_param(getattr(snap7.type.Parameter, name), value)
            except Exception:
                pass
        try:
            client.connect(ip, int(rack or 0), int(slot or 0))
        except Exception as exc:
            raise PlcError(f'Cannot connect to PLC {ip} (rack {rack}, slot {slot}): {exc}') from exc
        if not client.get_connected():
            raise PlcError(f'PLC {ip} is not reachable')
        yield client
    finally:
        try:
            if client.get_connected():
                client.disconnect()
        except Exception:
            pass
        try:
            client.destroy()
        except Exception:
            pass


def _offset(value, name):
    """Offsets are stored as {"byte": n, "bit": n}; validate before touching the PLC."""
    try:
        byte, bit = int(value['byte']), int(value['bit'])
    except (TypeError, ValueError, KeyError):
        raise PlcError(f'{name} offset is not configured')
    if byte < 0 or not 0 <= bit <= 7:
        raise PlcError(f'{name} offset {value} is invalid (bit must be 0-7)')
    return byte, bit


def read_db(client, motor):
    snap7 = _snap7()
    size = int(motor.dataSize or 0) or DEFAULT_DATA_SIZE
    try:
        return client.read_area(_db_area(snap7), int(motor.dbNo), int(motor.startByte or 0), size)
    except Exception as exc:
        raise PlcError(f'Reading DB{motor.dbNo} failed: {exc}') from exc


def _bool_at(data, offset, name):
    snap7 = _snap7()
    byte, bit = _offset(offset, name)
    if byte >= len(data):
        raise PlcError(f'{name} byte {byte} is outside the {len(data)}-byte data area')
    return bool(snap7.util.get_bool(data, byte, bit))


def decode_motor(motor, data):
    """Turn the raw DB bytes into the status shown on the SCADA page."""
    snap7 = _snap7()
    status = {'motor': {}, 'errors': []}

    for field_name, info in (motor.fields or {}).items():
        try:
            dtype = str(info[0]).upper()
            byte = int(info[1])
            bit = int(info[2]) if len(info) > 2 and info[2] not in (None, '') else 0
            reader, needs_bit = FIELD_TYPES[dtype]
            if byte < 0 or byte >= len(data):
                raise ValueError(f'byte {byte} outside data area')
            if needs_bit:
                if not 0 <= bit <= 7:
                    raise ValueError('bit must be 0-7')
                value = int(getattr(snap7.util, reader)(data, byte, bit))
            else:
                value = getattr(snap7.util, reader)(data, byte)
                if isinstance(value, float):
                    value = round(value, 3)
        except KeyError:
            value = None
            status['errors'].append(f'{field_name}: unsupported data type {info[0]!r}')
        except Exception as exc:
            value = None
            status['errors'].append(f'{field_name}: {exc}')
        status['motor'][field_name] = value

    for key, offset, name in (
        ('commandOn', motor.motorOnOffset, 'Motor ON'),
        ('commandOff', motor.motorOffOffset, 'Motor OFF'),
        ('running', motor.runFeedbackOffset, 'Run feedback'),
        ('trip', motor.tripOffset, 'Trip'),
    ):
        try:
            status[key] = _bool_at(data, offset, name)
        except PlcError as exc:
            status[key] = None
            status['errors'].append(str(exc))

    # "isOn" kept for compatibility: prefer the real run feedback, fall back to the command bits.
    if status.get('running') is not None:
        status['isOn'] = status['running']
    elif status.get('commandOn') is not None:
        status['isOn'] = bool(status['commandOn'] and not status.get('commandOff'))
    else:
        status['isOn'] = False
    return status


def decode_tank(tank, data):
    snap7 = _snap7()
    result = {'id': tank.id, 'name': tank.tankName or f'Tank {tank.id}', 'high': None, 'low': None, 'value': None,
              'tankVolume': tank.tankVolume or 0}
    try:
        if tank.highByte is not None and tank.highBit is not None:
            result['high'] = bool(snap7.util.get_bool(data, int(tank.highByte), int(tank.highBit)))
        if tank.lowByte is not None and tank.lowBit is not None:
            result['low'] = bool(snap7.util.get_bool(data, int(tank.lowByte), int(tank.lowBit)))
        if tank.valueByte is not None:
            result['value'] = int(snap7.util.get_int(data, int(tank.valueByte)))
    except Exception as exc:
        result['error'] = str(exc)
    return result


def write_command(client, motor, action):
    """Start: ON bit = 1, OFF bit = 0. Stop: ON bit = 0, OFF bit = 1 (latched, as the PLC program expects)."""
    snap7 = _snap7()
    area = _db_area(snap7)
    on_byte, on_bit = _offset(motor.motorOnOffset, 'Motor ON')
    off_byte, off_bit = _offset(motor.motorOffOffset, 'Motor OFF')
    wanted = {
        'start': [(on_byte, on_bit, True), (off_byte, off_bit, False)],
        'stop': [(on_byte, on_bit, False), (off_byte, off_bit, True)],
    }[action]

    base = int(motor.startByte or 0)
    by_byte = {}
    for byte, bit, value in wanted:
        by_byte.setdefault(byte, []).append((bit, value))

    for byte, bits in by_byte.items():
        absolute = base + byte
        try:
            buffer = client.read_area(area, int(motor.dbNo), absolute, 1)
            for bit, value in bits:
                snap7.util.set_bool(buffer, 0, bit, value)
            client.write_area(area, int(motor.dbNo), absolute, buffer)
        except Exception as exc:
            raise PlcError(f'Writing DB{motor.dbNo}.DBX{absolute} failed: {exc}') from exc
