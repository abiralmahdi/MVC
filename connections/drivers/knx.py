"""KNX driver: GroupValueRead of each group address through a KNXnet/IP interface or router (xknx).

Tunnelling (UDP or TCP) connects to the interface at ``host:port``. Routing joins the KNX multicast group
224.0.23.12 on the default interface; the host is not used then and the router must be in the same
multicast domain. KNX Data Secure / KNX IP Secure are not supported.
"""
import asyncio

CONNECTION_TYPES = {
    'tunneling': 'TUNNELING',
    'tunneling_tcp': 'TUNNELING_TCP',
    'routing': 'ROUTING',
}


def describe(point):
    return f"{point.get('group_address')} DPT {point.get('dpt')}"


def decode(dpt, payload):
    """Decode a DPTArray / DPTBinary payload to a plain number (int, float or bool).

    Raises ValueError for unknown datapoint types, malformed payloads and non-numeric values.
    """
    from enum import Enum

    from xknx.dpt import DPTBase
    from xknx.exceptions import XKNXException

    transcoder = DPTBase.parse_transcoder(dpt)
    if transcoder is None:
        raise ValueError(f'unknown datapoint type "{dpt}"')
    try:
        value = transcoder.from_knx(payload)
    except XKNXException as exc:
        raise ValueError(f'cannot decode {payload} as DPT {dpt}: {exc}') from exc
    if isinstance(value, Enum):   # e.g. 1.001 Switch.ON (True), 20.102 HVAC mode (1)
        value = value.value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    raise ValueError(f'DPT {dpt} value {value!r} is not numeric')


def connection_config(host, connection):
    from xknx.io import ConnectionConfig, ConnectionType

    kind = connection.get('connection_type') or 'tunneling'
    connection_type = getattr(ConnectionType, CONNECTION_TYPES.get(kind, 'TUNNELING'))
    kwargs = {
        'connection_type': connection_type,
        'individual_address': connection.get('individual_address') or None,
        'auto_reconnect': False,
    }
    if connection_type != ConnectionType.ROUTING:
        kwargs.update(gateway_ip=host, gateway_port=int(connection.get('port') or 3671))
    return ConnectionConfig(**kwargs)


async def _read_all(host, connection, points, values, errors):
    from xknx import XKNX
    from xknx.core import ValueReader
    from xknx.telegram import GroupAddress

    timeout = float(connection.get('timeout') or 3)
    port = int(connection.get('port') or 3671)
    where = 'KNX/IP routing (multicast)' if connection.get('connection_type') == 'routing' \
        else f'KNX/IP interface {host}:{port}'
    try:
        xknx = XKNX(connection_config=connection_config(host, connection))
    except Exception as exc:
        errors.append(f'invalid KNX connection settings: {exc}')
        return
    try:
        try:
            await asyncio.wait_for(xknx.start(), timeout)
        except (TimeoutError, asyncio.TimeoutError):
            errors.append(f'cannot connect to {where}: timeout')
            return
        except Exception as exc:
            errors.append(f'cannot connect to {where}: {exc}')
            return
        for name, point in points.items():
            label = f'{name} ({describe(point)})'
            try:
                address = GroupAddress(point['group_address'])
            except Exception as exc:
                errors.append(f'{label}: invalid group address ({exc})')
                continue
            try:
                telegram = await asyncio.wait_for(
                    ValueReader(xknx, address, timeout_in_seconds=timeout).read(), timeout + 1)
            except (TimeoutError, asyncio.TimeoutError):
                telegram = None
            except Exception as exc:
                errors.append(f'{label}: {exc}')
                continue
            if telegram is None:
                errors.append(f'{label}: timeout (no response; is the read flag set?)')
                continue
            try:
                values[name] = decode(point['dpt'], telegram.payload.value)
            except (ValueError, AttributeError) as exc:
                errors.append(f'{label}: {exc}')
    finally:
        try:
            await asyncio.wait_for(xknx.stop(), 5)
        except Exception:  # cleanup must not hide the values already read
            pass


def read(host, connection, points):
    values = {name: None for name in points}
    try:
        import xknx  # noqa: F401
    except ImportError:
        return values, ['the "xknx" package is not installed']
    errors = []
    try:
        asyncio.run(_read_all(host, connection, points, values, errors))
    except Exception as exc:
        errors.append(f'KNX read through {host} failed: {exc}')
    return values, errors
