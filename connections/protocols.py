"""Field protocols a meter can use, described once for the form, the validation and the drivers.

Every protocol declares
  * its connection settings (stored in ``Meters.connection``), and
  * the fields of one data point (one entry of ``Meters.registerMapping``: measurement name -> point).

The settings page renders both from ``catalogue()``; the server validates posted values with
``clean_connection`` / ``clean_mapping``; ``connections.drivers`` reads the cleaned points.
"""
import re
from dataclasses import asdict, dataclass, field

from .modbus import DATA_TYPES, default_function_code, is_opcua_node_id, parse_register_spec

MODBUS = 'modbus'
OPCUA = 'opcua'
BACNET = 'bacnet'
KNX = 'knx'
DALI = 'dali'
MBUS = 'mbus'
MQTT = 'mqtt'


@dataclass
class Field:
    name: str
    label: str
    type: str = 'str'            # str | int | float | bool | choice | secret
    default: object = None
    required: bool = False
    min: float = None
    max: float = None
    choices: list = None         # [[value, label], ...]
    help: str = ''
    placeholder: str = ''
    pattern: str = None          # regular expression for str fields
    show_if: dict = None         # {other_field: [values]} - field only applies when the condition holds
    width: int = 3               # grid columns (of 12) in the form


@dataclass
class Protocol:
    key: str
    label: str
    summary: str
    host_label: str
    host_placeholder: str
    connection: list
    point: list
    point_help: str
    host_required: bool = True
    host_show_if: dict = None
    libraries: list = field(default_factory=list)

    def as_json(self):
        data = asdict(self)
        return data


GROUP_ADDRESS = r'^\d{1,2}/\d{1,2}/\d{1,3}$|^\d{1,2}/\d{1,4}$|^\d{1,5}$'
BACNET_OBJECT_TYPES = [
    ['analog-input', 'Analog input (AI)'], ['analog-value', 'Analog value (AV)'],
    ['analog-output', 'Analog output (AO)'], ['binary-input', 'Binary input (BI)'],
    ['binary-value', 'Binary value (BV)'], ['binary-output', 'Binary output (BO)'],
    ['multi-state-input', 'Multi-state input (MI)'], ['multi-state-value', 'Multi-state value (MV)'],
    ['accumulator', 'Accumulator'], ['pulse-converter', 'Pulse converter'],
    ['integer-value', 'Integer value'], ['large-analog-value', 'Large analog value'],
]
KNX_DPTS = [
    ['9.001', '9.001 Temperature (°C)'], ['9.007', '9.007 Humidity (%)'], ['9.008', '9.008 Air quality (ppm)'],
    ['9.004', '9.004 Lux'], ['9.006', '9.006 Pressure (Pa)'], ['9.024', '9.024 Power (kW)'],
    ['9.021', '9.021 Current (mA)'], ['9.020', '9.020 Voltage (mV)'],
    ['14.056', '14.056 Power (W)'], ['14.019', '14.019 Electric current (A)'],
    ['14.027', '14.027 Electric potential (V)'], ['14.057', '14.057 Power factor'],
    ['14.033', '14.033 Frequency (Hz)'], ['14.068', '14.068 Temperature (°C, 4-byte)'],
    ['13.010', '13.010 Active energy (Wh)'], ['13.013', '13.013 Active energy (kWh)'],
    ['13.015', '13.015 Reactive energy (kVARh)'], ['12.001', '12.001 Counter (unsigned)'],
    ['5.001', '5.001 Percent (0-100 %)'], ['5.010', '5.010 Counter (0-255)'],
    ['7.001', '7.001 Pulses (0-65535)'], ['1.001', '1.001 Switch (on/off)'],
]
DALI_VALUES = [
    ['actual_level', 'Actual arc level (0-254)'], ['level_percent', 'Actual level (%)'],
    ['lamp_failure', 'Lamp failure (0/1)'], ['gear_failure', 'Control gear failure (0/1)'],
    ['status', 'Status byte'],
    ['active_power', 'Active power (W) - DALI-2 part 252'], ['active_energy', 'Active energy (Wh) - DALI-2 part 252'],
    ['apparent_power', 'Apparent power (VA) - DALI-2 part 252'],
    ['apparent_energy', 'Apparent energy (VAh) - DALI-2 part 252'],
    ['loadside_power', 'Load-side active power (W) - DALI-2 part 252'],
    ['loadside_energy', 'Load-side active energy (Wh) - DALI-2 part 252'],
]
TIMEOUT = Field('timeout', 'Timeout (s)', 'float', 3, min=0.5, max=60, width=2)

PROTOCOLS = {
    MODBUS: Protocol(
        MODBUS, 'Modbus TCP', 'Energy meters, gateways and PLCs over Modbus TCP (function codes 3 and 4).',
        'IP address / host', '192.168.0.80',
        [Field('port', 'TCP port', 'int', 502, True, 1, 65535, width=2),
         Field('unit_id', 'Unit ID', 'int', 1, True, 0, 255, help='Slave address behind a gateway; 1 for most TCP meters.', width=2),
         TIMEOUT],
        [Field('fc', 'Function', 'choice', 4, True, choices=[[4, 'FC4 input'], [3, 'FC3 holding']], width=3),
         Field('address', 'Register (0-based)', 'int', None, True, 0, 65535, placeholder='Address', width=3),
         Field('type', 'Data type', 'choice', 'float32', True, choices=[[t, t] for t in DATA_TYPES], width=4),
         Field('scale', 'Scale', 'float', 1, width=2)],
        'Function code, 0-based register address, data type and scale factor of each value.',
        libraries=['built-in'],
    ),
    BACNET: Protocol(
        BACNET, 'BACnet/IP', 'Building automation controllers, HVAC plant and meters speaking BACnet/IP (UDP).',
        'Device IP address', '192.168.10.20',
        [Field('port', 'UDP port', 'int', 47808, True, 1, 65535, help='47808 (0xBAC0) unless the site uses another.', width=2),
         Field('device_instance', 'Device instance', 'int', None, False, 0, 4194303, help='Documentation only; the IP address selects the device.', width=2),
         Field('network', 'Remote network', 'int', None, False, 1, 65534, help='Only for MS/TP devices behind a BACnet router.', width=2),
         Field('mac', 'MS/TP MAC', 'int', None, False, 0, 254, help='Station address on the remote network.', width=2),
         TIMEOUT],
        [Field('object_type', 'Object type', 'choice', 'analog-input', True, choices=BACNET_OBJECT_TYPES, width=4),
         Field('instance', 'Instance', 'int', None, True, 0, 4194303, placeholder='Instance', width=3),
         Field('property', 'Property', 'str', 'present-value', True, pattern=r'^[a-z][a-z0-9-]*$', width=3),
         Field('scale', 'Scale', 'float', 1, width=2)],
        'Object type and instance (for example analog-input 3) and the property to read, normally present-value.',
        libraries=['bacpypes3'],
    ),
    KNX: Protocol(
        KNX, 'KNX', 'KNX installations through a KNXnet/IP interface or router (group address reads).',
        'KNX/IP interface address', '192.168.20.5',
        [Field('connection_type', 'Connection', 'choice', 'tunneling', True,
               choices=[['tunneling', 'Tunnelling (UDP)'], ['tunneling_tcp', 'Tunnelling (TCP)'], ['routing', 'Routing (multicast)']], width=3),
         Field('port', 'Port', 'int', 3671, True, 1, 65535, width=2),
         Field('individual_address', 'Individual address', 'str', '', False, pattern=r'^$|^\d{1,2}\.\d{1,2}\.\d{1,3}$',
               placeholder='1.1.250', help='Optional; needed by some routers.', width=2),
         TIMEOUT],
        [Field('group_address', 'Group address', 'str', '', True, pattern=GROUP_ADDRESS, placeholder='1/2/3', width=4),
         Field('dpt', 'Datapoint type', 'choice', '9.001', True, choices=KNX_DPTS, width=6),
         Field('scale', 'Scale', 'float', 1, width=2)],
        'Group address of the status object and its datapoint type (DPT). The object must have the read flag set.',
        host_show_if={'connection_type': ['tunneling', 'tunneling_tcp']},
        libraries=['xknx'],
    ),
    DALI: Protocol(
        DALI, 'DALI / DALI-2', 'Lighting control gear on a DALI bus, reached through a DALI-over-TCP gateway (daliserver).',
        'Gateway IP address', '192.168.30.4',
        [Field('port', 'Gateway TCP port', 'int', 55825, True, 1, 65535, help='daliserver default 55825.', width=2),
         TIMEOUT],
        [Field('address', 'Short address', 'int', None, True, 0, 63, placeholder='0-63', width=3),
         Field('value', 'Value', 'choice', 'active_power', True, choices=DALI_VALUES, width=7),
         Field('scale', 'Scale', 'float', 1, width=2)],
        'Short address of the control gear and the value to query. Power and energy need DALI-2 gear with part 252 energy reporting.',
        libraries=['python-dali'],
    ),
    MBUS: Protocol(
        MBUS, 'M-Bus', 'Heat, water, gas and electricity meters on a wired M-Bus (EN 13757) via a level converter or TCP gateway.',
        'Gateway IP address', '192.168.40.9',
        [Field('transport', 'Transport', 'choice', 'tcp', True, choices=[['tcp', 'TCP gateway'], ['serial', 'Serial level converter']], width=2),
         Field('port', 'Gateway TCP port', 'int', 10001, False, 1, 65535, show_if={'transport': ['tcp']}, width=2),
         Field('serial_port', 'Serial port', 'str', '', False, placeholder='COM3 or /dev/ttyUSB0', show_if={'transport': ['serial']}, width=2),
         Field('baudrate', 'Baud rate', 'choice', 2400, True, choices=[[300, '300'], [2400, '2400'], [9600, '9600'], [19200, '19200'], [38400, '38400']], width=2),
         Field('address_mode', 'Addressing', 'choice', 'primary', True, choices=[['primary', 'Primary'], ['secondary', 'Secondary']], width=2),
         Field('primary_address', 'Primary address', 'int', 1, False, 0, 250, show_if={'address_mode': ['primary']}, width=2),
         Field('secondary_address', 'Secondary address', 'str', '', False, pattern=r'^$|^[0-9A-Fa-f]{16}$',
               placeholder='16 hex digits', show_if={'address_mode': ['secondary']}, width=2),
         TIMEOUT],
        [Field('record', 'Record index', 'int', None, True, 0, 255, placeholder='0, 1, 2 ...', width=4),
         Field('scale', 'Scale', 'float', 1, width=3)],
        'Index of the data record in the meter\'s response (use Test connection to list the records). Values are already '
        'in the record\'s unit; use the scale to convert, e.g. 0.001 for Wh to kWh.',
        host_show_if={'transport': ['tcp']},
        libraries=['pyMeterBus', 'pyserial'],
    ),
    MQTT: Protocol(
        MQTT, 'MQTT', 'IoT meters and edge gateways publishing values to an MQTT broker.',
        'Broker host', 'broker.example.com',
        [Field('port', 'Port', 'int', 1883, True, 1, 65535, help='1883 plain, 8883 TLS.', width=2),
         Field('tls', 'TLS', 'bool', False, width=1),
         Field('username', 'Username', 'str', '', width=2),
         Field('password', 'Password', 'secret', '', width=2),
         Field('client_id', 'Client ID', 'str', '', placeholder='automatic', width=2),
         Field('wait', 'Wait (s)', 'float', 5, True, 0.5, 120, help='How long a read waits for messages.', width=1),
         Field('max_age', 'Max age (s)', 'int', 900, True, 10, 86400, help='Older values are treated as missing.', width=2)],
        [Field('topic', 'Topic', 'str', '', True, pattern=r'^[^\s#+]+$', placeholder='plant/meter-1/power', width=5),
         Field('json_path', 'JSON path', 'str', '', placeholder='data.power (empty for plain numbers)', width=5),
         Field('scale', 'Scale', 'float', 1, width=2)],
        'Topic carrying the value. Plain numeric payloads are used as they are; for JSON payloads give the dotted path, '
        'e.g. ENERGY.Power or values.0.v. Publish with the retain flag so a value is available immediately.',
        libraries=['paho-mqtt'],
    ),
    OPCUA: Protocol(
        OPCUA, 'OPC UA', 'OPC UA servers such as SCADA systems, PLCs and edge gateways.',
        'Server host', 'scada-server.local',
        [Field('port', 'Port', 'int', 4840, True, 1, 65535, help='4840 is the standard port; Siemens WinCC often uses 4862.', width=2),
         Field('path', 'Endpoint path', 'str', '', pattern=r'^$|^/[^\s]*$', placeholder='/UA/Server', width=3),
         Field('username', 'Username', 'str', '', help='Leave empty for anonymous access.', width=2),
         Field('password', 'Password', 'secret', '', width=2),
         TIMEOUT],
        [Field('node', 'Node id', 'str', '', True, pattern=r'^(ns=\d+;)?[isgb]=.+$', placeholder='ns=2;s=Meter1.Voltage', width=8),
         Field('scale', 'Scale', 'float', 1, width=2)],
        'Node id of each value (ns=<namespace>;s=<string> or ns=<namespace>;i=<number>).',
        libraries=['opcua'],
    ),
}
ORDER = [MODBUS, BACNET, KNX, DALI, MBUS, MQTT, OPCUA]
CHOICES = [(key, PROTOCOLS[key].label) for key in ORDER]
DEFAULT_PORTS = {key: next((f.default for f in PROTOCOLS[key].connection if f.name == 'port'), None) for key in ORDER}


def get(protocol):
    return PROTOCOLS.get(protocol) or PROTOCOLS[MODBUS]


def label(protocol):
    return get(protocol).label


def catalogue():
    """JSON-ready description of every protocol, in display order (used by the meter form)."""
    return [PROTOCOLS[key].as_json() for key in ORDER]


# ---------------------------------------------------------------- validation
def _applies(fld, values):
    if not fld.show_if:
        return True
    return all(str(values.get(other)) in [str(v) for v in allowed] for other, allowed in fld.show_if.items())


def _clean_field(fld, raw):
    """Return (value, error) for one posted value."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ''):
        if fld.required and fld.default is None:
            return None, f'{fld.label} is required'
        return fld.default if fld.type != 'secret' else '', None
    try:
        if fld.type == 'int':
            if isinstance(raw, bool) or float(raw) != int(float(raw)):
                raise ValueError
            value = int(float(raw))
        elif fld.type == 'float':
            value = float(raw)
        elif fld.type == 'bool':
            value = raw if isinstance(raw, bool) else str(raw).strip().lower() in ('1', 'true', 'on', 'yes')
        elif fld.type == 'choice':
            allowed = {str(v): v for v, _ in fld.choices}
            if str(raw).strip() not in allowed:
                return None, f'{fld.label} "{raw}" is not one of {", ".join(allowed)}'
            value = allowed[str(raw).strip()]
        else:
            value = str(raw).strip()
    except (TypeError, ValueError):
        return None, f'{fld.label} must be a {"whole number" if fld.type == "int" else "number"}'
    if fld.type in ('int', 'float'):
        if value != value or value in (float('inf'), float('-inf')):
            return None, f'{fld.label} must be a finite number'
        if fld.min is not None and value < fld.min or fld.max is not None and value > fld.max:
            return None, f'{fld.label} must be between {fld.min:g} and {fld.max:g}'
    if fld.type == 'str' and fld.pattern and not re.match(fld.pattern, value):
        return None, f'{fld.label} "{value}" is not valid'
    return value, None


def _clean_fields(fields, data):
    cleaned, errors = {}, []
    data = data if isinstance(data, dict) else {}
    # resolve fields without conditions first so show_if can look at them
    for fld in sorted(fields, key=lambda f: f.show_if is not None):
        if not _applies(fld, {**data, **cleaned}):
            continue
        value, error = _clean_field(fld, data.get(fld.name))
        if error:
            errors.append(error)
        else:
            cleaned[fld.name] = value
    return cleaned, errors


def host_required(protocol, connection):
    spec = get(protocol)
    return spec.host_required and (not spec.host_show_if or all(
        str(connection.get(k)) in [str(v) for v in allowed] for k, allowed in spec.host_show_if.items()))


def clean_connection(protocol, host, data):
    """Validate the connection settings. Returns (host, connection, errors)."""
    if protocol not in PROTOCOLS:
        return host, {}, [f'Unknown protocol "{protocol}"']
    spec = PROTOCOLS[protocol]
    connection, errors = _clean_fields(spec.connection, data)
    host = (host or '').strip()
    if host_required(protocol, connection):
        if not host:
            errors.append(f'{spec.host_label} is required')
        elif not re.match(r'^[0-9A-Za-z.\-:\[\]]+$', host):
            errors.append(f'{spec.host_label} "{host}" may only contain letters, digits, dots, dashes and colons')
    if protocol == MBUS:
        if connection.get('transport') == 'serial' and not connection.get('serial_port'):
            errors.append('Serial port is required for a serial M-Bus level converter')
        if connection.get('address_mode') == 'secondary' and not connection.get('secondary_address'):
            errors.append('Secondary address is required with secondary addressing')
    if protocol == BACNET and (connection.get('network') is None) != (connection.get('mac') is None):
        errors.append('Remote network and MS/TP MAC must be given together')
    return host, connection, errors


def legacy_point(protocol, definition):
    """Convert mapping entries written before protocols existed into the protocol's point shape."""
    if protocol == MODBUS:
        return parse_register_spec(definition).as_dict()
    if protocol == OPCUA and is_opcua_node_id(definition):
        return {'node': definition.strip(), 'scale': 1}
    return definition


def clean_point(protocol, definition):
    """Validate one mapping entry. Returns (point, errors)."""
    try:
        definition = legacy_point(protocol, definition)
    except (TypeError, ValueError) as exc:
        return None, [str(exc)]
    if not isinstance(definition, dict):
        return None, [f'expected an object with {", ".join(f.name for f in get(protocol).point)}']
    point, errors = _clean_fields(get(protocol).point, definition)
    if protocol == MODBUS and not errors:
        point['fc'] = int(point['fc'] or default_function_code())
    if protocol == KNX and not errors:
        error = knx_dpt_error(point['dpt'])
        if error:
            errors.append(error)
    return point, errors


def knx_dpt_error(dpt):
    try:
        from xknx.dpt import DPTBase
    except ImportError:
        return None
    return None if DPTBase.parse_transcoder(dpt) else f'unknown KNX datapoint type "{dpt}"'


def clean_mapping(protocol, mapping):
    """Validate a whole mapping {measurement name: point}. Returns (cleaned, errors)."""
    if not isinstance(mapping, dict):
        return {}, ['The data point mapping must be an object']
    cleaned, errors = {}, []
    for name, definition in mapping.items():
        name = str(name).strip()
        if not name:
            continue
        point, point_errors = clean_point(protocol, definition)
        if point_errors:
            errors.extend(f'"{name}": {e}' for e in point_errors)
        else:
            cleaned[name] = point
    return cleaned, errors


def describe_point(protocol, point):
    """Short human readable address of a point, for tables and logs."""
    if not isinstance(point, dict):
        return str(point)
    if protocol == MODBUS:
        return f"FC{point.get('fc')} @{point.get('address')} {point.get('type')}"
    if protocol == BACNET:
        return f"{point.get('object_type')},{point.get('instance')} {point.get('property')}"
    if protocol == KNX:
        return f"{point.get('group_address')} DPT {point.get('dpt')}"
    if protocol == DALI:
        return f"A{point.get('address')} {point.get('value')}"
    if protocol == MBUS:
        return f"record {point.get('record')}"
    if protocol == MQTT:
        return f"{point.get('topic')}{' → ' + point['json_path'] if point.get('json_path') else ''}"
    if protocol == OPCUA:
        return str(point.get('node'))
    return str(point)
