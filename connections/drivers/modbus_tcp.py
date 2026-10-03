"""Modbus TCP driver (function codes 3 and 4) built on the exact-frame client in connections.modbus."""
import time

from ..modbus import ModbusError, ModbusTcpClient, RegisterSpec

INTER_REQUEST_DELAY = 0.05


def read(host, connection, points):
    values = {name: None for name in points}
    errors = []
    port = connection.get('port', 502)
    try:
        with ModbusTcpClient(host, port, connection.get('unit_id', 1), connection.get('timeout', 3)) as client:
            for name, point in points.items():
                spec = RegisterSpec(point['fc'], point['address'], point['type'], 1.0)
                try:
                    values[name] = client.read_value(spec)
                except ModbusError as exc:
                    errors.append(f"{name} (fc{spec.function_code} @{spec.address}): {exc}")
                except OSError as exc:
                    # socket timeout / reset: the connection is unusable, stop this cycle
                    errors.append(f'{name}: {exc}')
                    break
                time.sleep(INTER_REQUEST_DELAY)
    except OSError as exc:
        errors.append(f'cannot connect to {host}:{port}: {exc}')
    return values, errors
