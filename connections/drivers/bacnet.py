"""BACnet/IP driver: ReadProperty of each point, built on bacpypes3.

Every read creates a short-lived client application bound to an ephemeral UDP port on all interfaces
(``0.0.0.0:0``) with a random device instance, so several reads can run at the same time in different
worker threads. Devices behind a BACnet router (MS/TP) are addressed as ``network:mac@router-ip:port``.

Not supported: foreign-device registration / BBMDs (the device must be reachable by unicast UDP),
segmented responses larger than the default APDU size are left to bacpypes3.
"""
import asyncio
import random

CLIENT_ADDRESS = '0.0.0.0:0'
VENDOR_IDENTIFIER = 999


def describe(point):
    return f"{point.get('object_type')},{point.get('instance')} {point.get('property', 'present-value')}"


def device_address(host, connection):
    port = connection.get('port') or 47808
    if ':' in host and not host.startswith('['):   # bare IPv6 literal
        host = f'[{host}]'
    router = f'{host}:{port}'
    if connection.get('network') is not None and connection.get('mac') is not None:
        return f"{connection['network']}:{connection['mac']}@{router}"
    return router


def convert(value):
    """Map a decoded BACnet value to a plain number. Raises ValueError for non-numeric values."""
    if value is None:
        raise ValueError('no value returned')
    if isinstance(value, str):   # CharacterString, or bacpypes3 "-no object class-" style markers
        raise ValueError(f'value {str(value)!r} is not numeric')
    if isinstance(value, bool):
        return value
    # Enumerated (BinaryPV: inactive=0 / active=1, other enumerations by their number), Boolean,
    # Unsigned and Integer are int subclasses; Real and Double are float subclasses.
    try:
        from bacpypes3.primitivedata import Boolean, Enumerated
    except ImportError:  # pragma: no cover - only used when bacpypes3 is present
        Boolean = Enumerated = ()
    if Boolean and isinstance(value, Boolean):
        return bool(value)
    if Enumerated and isinstance(value, Enumerated):
        return int(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    raise ValueError(f'value {value!r} ({type(value).__name__}) is not numeric')


def error_text(exc):
    """Short description of an Error / Reject / Abort PDU or another exception."""
    try:
        from bacpypes3.apdu import AbortPDU, ErrorPDU, RejectPDU
    except ImportError:  # pragma: no cover
        return str(exc) or type(exc).__name__
    if isinstance(exc, AbortPDU):
        reason = str(exc.apduAbortRejectReason)
        return 'timeout (no response)' if reason == 'no-response' else f'abort: {reason}'
    if isinstance(exc, RejectPDU):
        return f'reject: {exc.apduAbortRejectReason}'
    if isinstance(exc, ErrorPDU):
        code = getattr(exc, 'errorCode', None)
        klass = getattr(exc, 'errorClass', None)
        return f'error: {klass}: {code}' if code is not None else f'error: {exc}'
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return 'timeout'
    return str(exc) or type(exc).__name__


def _client(timeout):
    from types import SimpleNamespace

    from bacpypes3.app import Application

    args = SimpleNamespace(
        vendoridentifier=VENDOR_IDENTIFIER, instance=random.randint(3_000_000, 4_194_302),
        name=f'MarksVision-{random.randint(0, 999_999)}', address=CLIENT_ADDRESS,
        network=0, foreign=None, ttl=30, bbmd=None,
    )
    app = Application.from_args(args)
    # one retry inside the timeout so a single lost datagram does not fail the point
    device = app.asap.device_object
    device.apduTimeout = max(250, int(timeout * 1000 / 2))
    device.numberOfApduRetries = 1
    return app


async def _read_all(host, connection, points, values, errors):
    from bacpypes3.apdu import ErrorRejectAbortNack
    from bacpypes3.primitivedata import ObjectIdentifier
    from bacpypes3.settings import settings

    timeout = float(connection.get('timeout') or 3)
    address = device_address(host, connection)
    if '@' in address:
        # needed for "network:mac@router" addresses; only changes behaviour of routed addresses
        settings.route_aware = True
    try:
        app = _client(timeout)
    except Exception as exc:
        errors.append(f'cannot start BACnet client: {exc}')
        return
    try:
        responded = False
        names = list(points)
        for index, name in enumerate(names):
            point = points[name]
            label = f'{name} ({describe(point)})'
            try:
                objid = ObjectIdentifier(f"{point['object_type']},{int(point['instance'])}")
                result = await asyncio.wait_for(
                    app.read_property(address, objid, point.get('property') or 'present-value'),
                    timeout + 0.5)
            except (TimeoutError, asyncio.TimeoutError) as exc:
                errors.append(f'{label}: {error_text(exc)}')
                if not responded:
                    rest = len(names) - index - 1
                    if rest:
                        errors.append(f'device {address} did not respond; {rest} more point(s) skipped')
                    break
                continue
            except ErrorRejectAbortNack as exc:   # raised by bacpypes3 (derives from BaseException)
                text = error_text(exc)
                errors.append(f'{label}: {text}')
                if text.startswith('timeout') and not responded:
                    rest = len(names) - index - 1
                    if rest:
                        errors.append(f'device {address} did not respond; {rest} more point(s) skipped')
                    break
                responded = responded or not text.startswith('timeout')
                continue
            except (ValueError, KeyError) as exc:   # property / object type bacpypes3 does not know
                errors.append(f'{label}: unknown object type or property ({exc})')
                continue
            except Exception as exc:   # socket errors, ...
                errors.append(f'{label}: {error_text(exc)}')
                continue
            responded = True
            if isinstance(result, ErrorRejectAbortNack):   # older bacpypes3 returned instead of raising
                errors.append(f'{label}: {error_text(result)}')
                continue
            try:
                values[name] = convert(result)
            except ValueError as exc:
                errors.append(f'{label}: {exc}')
    finally:
        try:
            app.close()
        except Exception:
            pass


def read(host, connection, points):
    values = {name: None for name in points}
    try:
        import bacpypes3  # noqa: F401
    except ImportError:
        return values, ['the "bacpypes3" package is not installed']
    errors = []
    try:
        asyncio.run(_read_all(host, connection, points, values, errors))
    except Exception as exc:
        errors.append(f'BACnet read from {host} failed: {exc}')
    return values, errors
