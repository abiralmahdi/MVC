"""Wired M-Bus (EN 13757-2/-3) driver built on pyMeterBus + pyserial.

Transport: a transparent TCP gateway (``socket://host:port``) or a serial level converter (8E1).
Addressing: primary (SND_NKE, REQ_UD2 to the address) or secondary (SND_UD select, then REQ_UD2 to
the network layer address 253). Multi-telegram responses are followed (up to MAX_TELEGRAMS).
Every point is the index of a variable data record in the (combined) RSP_UD answer.
"""
import decimal
import math
import time

ADDRESS_NETWORK_LAYER = 0xFD
MAX_TELEGRAMS = 8


class MBusError(Exception):
    """The meter did not answer or answered something unusable (message is user facing)."""


# ---------------------------------------------------------------- transport
def _open(host, connection):
    import serial

    timeout = connection.get('timeout', 3)
    if connection.get('transport', 'tcp') == 'serial':
        return serial.Serial(connection['serial_port'], int(connection.get('baudrate', 2400)),
                             bytesize=8, parity='E', stopbits=1, timeout=timeout)
    return serial.serial_for_url(f"socket://{host}:{connection.get('port', 10001)}", timeout=timeout)


def _where(host, connection):
    if connection.get('transport', 'tcp') == 'serial':
        return f"serial port {connection.get('serial_port')}"
    return f"{host}:{connection.get('port', 10001)}"


def _read_exact(ser, size, deadline):
    data = b''
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ser.timeout = remaining
        chunk = ser.read(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


def _receive(ser, timeout):
    """Read one M-Bus frame (ACK, short, control or long) within ``timeout`` seconds.

    Returns the raw bytes or None on silence; raises MBusError for a garbled / truncated answer.
    """
    deadline = time.monotonic() + timeout
    start = _read_exact(ser, 1, deadline)
    # skip line noise before a start character
    while start and start[0] not in (0xE5, 0x10, 0x68):
        start = _read_exact(ser, 1, deadline)
    if not start:
        return None
    if start[0] == 0xE5:
        return start
    if start[0] == 0x10:
        rest = _read_exact(ser, 4, deadline)
        data = start + rest
        if len(data) < 5:
            raise MBusError('truncated short frame')
        return data
    head = _read_exact(ser, 3, deadline)
    if len(head) < 3 or head[0] != head[1] or head[2] != 0x68:
        raise MBusError('invalid long frame header')
    rest = _read_exact(ser, head[0] + 2, deadline)
    if len(rest) < head[0] + 2:
        raise MBusError(f'truncated long frame ({4 + len(rest)} of {head[0] + 6} bytes)')
    return start + head + rest


def _short_frame(control, address):
    import meterbus

    frame = meterbus.TelegramShort()
    frame.header.cField.parts = [control]
    frame.header.aField.parts = [address]
    return frame


def _exchange_frames(ser, connection):
    """Talk to the meter and return the parsed (combined) TelegramLong."""
    import meterbus
    from meterbus.exceptions import MBusFrameCRCError, MBusFrameDecodeError

    timeout = connection.get('timeout', 3)

    def flush():
        try:
            ser.reset_input_buffer()
        except Exception:
            pass

    if connection.get('address_mode', 'primary') == 'secondary':
        secondary = connection['secondary_address'].upper()
        flush()
        meterbus.send_select_frame(ser, secondary)
        ack = _receive(ser, timeout)
        if ack is None:
            raise MBusError(f'no response to selection of secondary address {secondary} (timeout {timeout:g} s)')
        if ack[:1] != b'\xe5':
            raise MBusError(f'unexpected answer to selection of secondary address {secondary}')
        address = ADDRESS_NETWORK_LAYER
        label = f'secondary address {secondary}'
    else:
        address = int(connection.get('primary_address', 1))
        label = f'primary address {address}'
        flush()
        meterbus.send_ping_frame(ser, address)
        ack = _receive(ser, timeout)
        if ack is None:
            raise MBusError(f'no response from {label} (timeout {timeout:g} s)')

    combined = None
    fcb = True
    for _ in range(MAX_TELEGRAMS):
        control = meterbus.CONTROL_MASK_REQ_UD2 | meterbus.CONTROL_MASK_DIR_M2S
        if combined is not None:   # follow-up telegram: toggle the frame count bit
            control |= meterbus.CONTROL_MASK_FCV | (meterbus.CONTROL_MASK_FCB if fcb else 0)
            fcb = not fcb
        flush()
        meterbus.send_request_frame(ser, req=_short_frame(control, address))
        data = _receive(ser, timeout)
        if data is None:
            raise MBusError(f'no data from {label} (timeout {timeout:g} s)')
        try:
            frame = meterbus.load(data)
        except MBusFrameCRCError:
            raise MBusError(f'checksum error in answer from {label}')
        except (MBusFrameDecodeError, IndexError, ValueError, KeyError) as exc:
            raise MBusError(f'cannot decode answer from {label}: {exc}')
        if not isinstance(frame, meterbus.TelegramLong):
            raise MBusError(f'{label} answered without data (not an RSP_UD long frame)')
        combined = frame if combined is None else combined + frame
        if not frame.more_records_follow:
            break
    return combined


def _import_meterbus():
    """Import pyMeterBus without its import-time ``logging.basicConfig(level=INFO)`` side effect."""
    import logging
    import sys

    if 'meterbus' in sys.modules:
        return sys.modules['meterbus']
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    try:
        import meterbus
    finally:
        for handler in list(root.handlers):
            if handler not in handlers:
                root.removeHandler(handler)
        root.setLevel(level)
    return meterbus


def _fetch(host, connection):
    """Open the transport, read the meter, close. Returns the record list (raises MBusError)."""
    try:
        _import_meterbus()
        import serial  # noqa: F401
    except ImportError as exc:
        raise MBusError(f'M-Bus support is not installed ({exc.name}); install pyMeterBus and pyserial')
    try:
        ser = _open(host, connection)
    except (OSError, ValueError) as exc:   # serial.SerialException is an OSError
        raise MBusError(f'cannot open {_where(host, connection)}: {exc}')
    try:
        return list(_exchange_frames(ser, connection).records)
    except OSError as exc:
        raise MBusError(f'connection to {_where(host, connection)} failed: {exc}')
    finally:
        try:
            ser.close()
        except Exception:
            pass


def _numeric(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, decimal.Decimal)):
        try:
            number = float(value)
        except (OverflowError, ValueError, decimal.InvalidOperation):
            return None
        return number if math.isfinite(number) else None
    return None


def _safe(getter):
    try:
        return getter()
    except Exception:
        return None


# ---------------------------------------------------------------- driver API
def read(host, connection, points):
    values = {name: None for name in points}
    try:
        records = _fetch(host, connection)
    except MBusError as exc:
        return values, [f'M-Bus: {exc}']
    errors = []
    for name, point in points.items():
        index = int(point['record'])
        label = f'{name} (record {index})'
        if index >= len(records):
            errors.append(f'{label}: record index out of range, the meter sent {len(records)} records (0-{len(records) - 1})')
            continue
        raw = _safe(lambda: records[index].value)
        number = _numeric(raw)
        if number is None:
            errors.append(f'{label}: value {raw!r} is not numeric')
            continue
        values[name] = number
    return values, errors


def discover(host, connection):
    """List the data records of the meter: [{'record', 'value', 'unit', 'type', 'function', ...}]."""
    try:
        records = _fetch(host, connection)
    except MBusError as exc:
        raise RuntimeError(str(exc)) from None
    result = []
    for index, record in enumerate(records):
        interpreted = _safe(lambda: record.interpreted) or {}
        raw = _safe(lambda: record.value)
        number = _numeric(raw)
        entry = {
            'record': index,
            'value': number if number is not None else (None if raw is None else str(raw)),
            'numeric': number is not None,
            'unit': _safe(lambda: record.unit),
            'type': _strip_enum(interpreted.get('type')),
            'function': _strip_enum(interpreted.get('function')),
            'storage_number': interpreted.get('storage_number'),
        }
        for key in ('tariff', 'device'):
            if interpreted.get(key) is not None:
                entry[key] = interpreted[key]
        if entry['unit'] is not None:
            entry['unit'] = str(entry['unit'])
        result.append(entry)
    return result


def _strip_enum(text):
    """'VIFUnit.FLOW_TEMPERATURE' -> 'FLOW_TEMPERATURE'; 'None' -> None."""
    if text in (None, 'None'):
        return None
    return str(text).split('.', 1)[-1]
