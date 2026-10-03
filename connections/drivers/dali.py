"""DALI / DALI-2 driver: queries control gear through a daliserver TCP gateway (python-dali).

daliserver protocol (https://github.com/onitake/daliserver): every request is 4 bytes
``02 00 <address byte> <command byte>`` and every reply is 4 bytes ``<ver> <status> <value> <pad>``
where status 0 = no answer, 1 = backward frame received, 255 = framing error (several answers).

Power and energy come from the DiiA part 252 energy reporting memory banks (202 active, 203 apparent,
204 load side), read with the memory sequences of ``dali.memory.energy``.
"""
import math
import socket
import struct

DEFAULT_PORT = 55825

# point value -> (memory bank, python-dali class name in dali.memory.energy)
ENERGY_VALUES = {
    'active_power': (202, 'ActivePower'),
    'active_energy': (202, 'ActiveEnergy'),
    'apparent_power': (203, 'ApparentPower'),
    'apparent_energy': (203, 'ApparentEnergy'),
    'loadside_power': (204, 'ActivePowerLoadside'),
    'loadside_energy': (204, 'ActiveEnergyLoadside'),
}


class DaliReadError(Exception):
    """A single point could not be read (the connection itself is still usable)."""


def level_to_percent(level):
    """Arc power level (0-254) -> light output in % on the IEC 62386-102 logarithmic dimming curve."""
    if level is None:
        return None
    level = int(level)
    if level <= 0:
        return 0.0
    if level > 254:
        raise ValueError(f'arc power level {level} is out of range 0-254')
    return 10 ** ((level - 1) / (253 / 3) - 1)


def _recv_exact(sock, size):
    data = b''
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError('gateway closed the connection')
        data += chunk
    return data


def _make_gateway(host, port, timeout):
    """Return a connected DaliServer whose socket honours ``timeout`` (one connection per read)."""
    from dali.driver.daliserver import DaliServer

    class TimeoutDaliServer(DaliServer):
        def send(self, command):
            message = struct.pack('BB', 2, 0) + command.frame.pack
            self._s.sendall(message)
            result = _recv_exact(self._s, 4)
            if command.sendtwice:
                self._s.sendall(message)
                result = _recv_exact(self._s, 4)
            return self.unpack_response(command, result)

        def close(self):
            if self._s is not None:
                try:
                    self._s.close()
                finally:
                    self._s = None

    gateway = TimeoutDaliServer(host, port, multiple_frames_per_connection=True)
    gateway._s = socket.create_connection((host, port), timeout)
    gateway._s.settimeout(timeout)
    return gateway


def run_sequence(driver, sequence):
    """Drive a python-dali command sequence (generator): send each yielded command, feed back the
    response, and return the generator's return value."""
    response = None
    while True:
        try:
            command = sequence.send(response)
        except StopIteration as stop:
            return stop.value
        response = driver.send(command)


def _backward_frame(driver, command):
    """Send a query and return its integer answer; raise DaliReadError when there is none."""
    response = driver.send(command)
    frame = response.raw_value if response is not None else None
    if frame is None:
        raise DaliReadError('no response')
    if frame.error:
        raise DaliReadError('framing error (several devices answered - duplicate short address?)')
    return frame.as_integer


def _query(driver, address, value, cache):
    from dali.address import GearShort
    from dali.gear import general

    gear = GearShort(address)

    def cached(key, fn):
        if key not in cache:
            try:
                cache[key] = (fn(), None)
            except DaliReadError as exc:
                cache[key] = (None, str(exc))
        result, error = cache[key]
        if error:
            raise DaliReadError(error)
        return result

    if value in ('actual_level', 'level_percent'):
        level = cached((address, 'level'), lambda: _backward_frame(driver, general.QueryActualLevel(gear)))
        if level == 255:
            raise DaliReadError('level is MASK (lamp failure or preheating)')
        return level if value == 'actual_level' else level_to_percent(level)

    if value in ('status', 'gear_failure'):
        status = cached((address, 'status'), lambda: _backward_frame(driver, general.QueryStatus(gear)))
        return status if value == 'status' else status & 0x01

    if value == 'lamp_failure':
        response = driver.send(general.QueryLampFailure(gear))
        # YES (or a garbled YES) = failure, no answer = NO. A missing gear also answers nothing, so
        # confirm the gear is present with the (cached) status query first.
        cached((address, 'status'), lambda: _backward_frame(driver, general.QueryStatus(gear)))
        return 1 if response is not None and response.raw_value is not None else 0

    if value in ENERGY_VALUES:
        from dali.exceptions import MemoryLocationNotImplemented, ResponseError
        from dali.memory import energy
        from dali.memory.location import FlagValue

        bank, class_name = ENERGY_VALUES[value]
        memory_value = getattr(energy, class_name)
        try:
            result = run_sequence(driver, memory_value.read(gear))
        except MemoryLocationNotImplemented:
            raise DaliReadError(f'gear does not support DALI-2 energy reporting (memory bank {bank})')
        except ResponseError as exc:
            raise DaliReadError(f'framing error while reading memory bank {bank}: {exc}')
        if isinstance(result, FlagValue):
            reason = {FlagValue.MASK: 'not implemented (MASK)',
                      FlagValue.TMASK: 'temporarily unavailable (TMASK)'}.get(result, 'invalid value')
            raise DaliReadError(f'memory bank {bank} value {reason}')
        try:
            number = float(result)
        except (TypeError, ValueError):
            raise DaliReadError(f'unexpected memory bank {bank} value {result!r}')
        if not math.isfinite(number):
            raise DaliReadError(f'unexpected memory bank {bank} value {result!r}')
        return number

    raise DaliReadError(f'unknown value "{value}"')


def read(host, connection, points):
    values = {name: None for name in points}
    try:
        import dali.driver.daliserver  # noqa: F401
        import dali.gear.general  # noqa: F401
        import dali.memory.energy  # noqa: F401
    except ImportError:
        return values, ['the "python-dali" package is not installed']

    port = connection.get('port', DEFAULT_PORT)
    timeout = connection.get('timeout', 3)
    errors = []
    try:
        gateway = _make_gateway(host, port, timeout)
    except OSError as exc:
        return values, [f'cannot connect to DALI gateway {host}:{port}: {exc}']

    cache = {}
    try:
        for name, point in points.items():
            label = f"{name} (A{point.get('address')} {point.get('value')})"
            try:
                values[name] = _query(gateway, int(point['address']), point['value'], cache)
            except DaliReadError as exc:
                errors.append(f'{label}: {exc}')
            except (OSError, ConnectionError) as exc:
                # timeout / reset: the gateway connection is unusable, stop this cycle
                errors.append(f'{label}: gateway connection lost: {exc or "timed out"}')
                break
            except Exception as exc:  # python-dali CommunicationError and friends
                errors.append(f'{label}: {exc.__class__.__name__}: {exc}')
    finally:
        gateway.close()
    return values, errors
