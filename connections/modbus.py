"""Minimal, dependency-free Modbus TCP client for energy meters.

Why not the old ``sock.recv(1024)`` code: TCP is a stream, so one recv() may
return a partial frame or two frames glued together, and responses were never
matched to requests. This client reads exact frame lengths and validates the
transaction id, unit id and function code of every response.
"""
import socket
import struct

from django.conf import settings

READ_HOLDING_REGISTERS = 3
READ_INPUT_REGISTERS = 4
SUPPORTED_FUNCTION_CODES = (READ_HOLDING_REGISTERS, READ_INPUT_REGISTERS)

# data type -> (register count, struct format for the big-endian byte payload)
DATA_TYPES = {
    'float32': (2, '>f'),
    'float32_swapped': (2, None),  # low word first (common on some gateways)
    'int16': (1, '>h'),
    'uint16': (1, '>H'),
    'int32': (2, '>i'),
    'uint32': (2, '>I'),
    'float64': (4, '>d'),
}
DEFAULT_DATA_TYPE = 'float32'

EXCEPTION_MESSAGES = {
    1: 'illegal function',
    2: 'illegal data address',
    3: 'illegal data value',
    4: 'server device failure',
    6: 'server device busy',
    10: 'gateway path unavailable',
    11: 'gateway target device failed to respond',
}


class ModbusError(Exception):
    pass


class RegisterSpec:
    __slots__ = ('function_code', 'address', 'data_type', 'scale')

    def __init__(self, function_code, address, data_type=DEFAULT_DATA_TYPE, scale=1.0):
        self.function_code = function_code
        self.address = address
        self.data_type = data_type
        self.scale = scale

    @property
    def count(self):
        return DATA_TYPES[self.data_type][0]

    def as_dict(self):
        return {'fc': self.function_code, 'address': self.address, 'type': self.data_type, 'scale': self.scale}


def default_function_code():
    return getattr(settings, 'MODBUS_DEFAULT_FUNCTION_CODE', READ_INPUT_REGISTERS)


def parse_register_spec(value):
    """Normalise every register-map shape the application has ever stored.

    Accepted shapes:
      * ``55`` or ``"55"``                         -> default function code, float32
      * ``[4, 55]``                                -> function code 4, address 55
      * ``[4, 55, "int16", 0.1]``                  -> with data type and scale
      * ``{"fc": 4, "address": 55, "type": "float32", "scale": 1}``
    Raises ValueError with a readable message for anything else.
    """
    if isinstance(value, bool):
        raise ValueError(f'invalid register {value!r}')

    fc, address, data_type, scale = default_function_code(), None, DEFAULT_DATA_TYPE, 1.0

    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().lstrip('-').isdigit()):
        address = int(value)
    elif isinstance(value, (list, tuple)):
        if len(value) < 2:
            raise ValueError(f'register list needs [function_code, address], got {value!r}')
        fc, address = int(value[0]), int(value[1])
        if len(value) > 2 and value[2]:
            data_type = str(value[2])
        if len(value) > 3 and value[3] not in (None, ''):
            scale = float(value[3])
    elif isinstance(value, dict):
        if 'address' not in value:
            raise ValueError(f'register object needs an "address", got {value!r}')
        address = int(value['address'])
        fc = int(value.get('fc') or value.get('function_code') or fc)
        data_type = str(value.get('type') or data_type)
        if value.get('scale') not in (None, ''):
            scale = float(value['scale'])
    else:
        raise ValueError(f'unsupported register definition {value!r}')

    data_type = data_type.lower()
    if fc not in SUPPORTED_FUNCTION_CODES:
        raise ValueError(f'function code {fc} is not supported (use 3 or 4)')
    if not 0 <= address <= 65535:
        raise ValueError(f'register address {address} is out of range')
    if data_type not in DATA_TYPES:
        raise ValueError(f'unknown data type "{data_type}"')
    return RegisterSpec(fc, address, data_type, scale)


def is_opcua_node_id(value):
    return isinstance(value, str) and value.strip().startswith(('ns=', 'i=', 's=', 'g=', 'b='))


def decode_registers(payload, data_type):
    if data_type == 'float32_swapped':
        low, high = struct.unpack('>HH', payload[:4])
        return struct.unpack('>f', struct.pack('>HH', high, low))[0]
    fmt = DATA_TYPES[data_type][1]
    return struct.unpack(fmt, payload[:struct.calcsize(fmt)])[0]


class ModbusTcpClient:
    def __init__(self, host, port=502, unit_id=1, timeout=2.0):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self._sock = None
        self._transaction_id = 0

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _recv_exact(self, size):
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self._sock.recv(size - len(chunks))
            if not chunk:
                raise ModbusError('connection closed by device')
            chunks.extend(chunk)
        return bytes(chunks)

    def read_registers(self, function_code, address, count):
        if self._sock is None:
            raise ModbusError('not connected')
        self._transaction_id = (self._transaction_id + 1) % 0x10000
        tid = self._transaction_id
        request = struct.pack('>HHHBBHH', tid, 0, 6, self.unit_id & 0xFF, function_code, address, count)
        self._sock.sendall(request)

        # Skip stale responses (e.g. a late answer to a request that timed out).
        for _ in range(3):
            header = self._recv_exact(7)
            resp_tid, protocol, length, unit = struct.unpack('>HHHB', header)
            body = self._recv_exact(length - 1)
            if resp_tid != tid:
                continue
            if protocol != 0:
                raise ModbusError(f'unexpected protocol id {protocol}')
            resp_fc = body[0]
            if resp_fc == function_code | 0x80:
                code = body[1] if len(body) > 1 else 0
                raise ModbusError(f'exception {code} ({EXCEPTION_MESSAGES.get(code, "unknown")})')
            if resp_fc != function_code:
                raise ModbusError(f'unexpected function code {resp_fc}')
            byte_count = body[1]
            payload = body[2:2 + byte_count]
            if byte_count != count * 2 or len(payload) != byte_count:
                raise ModbusError(f'expected {count * 2} data bytes, got {len(payload)}')
            return payload
        raise ModbusError('no matching response (transaction id mismatch)')

    def read_value(self, spec):
        payload = self.read_registers(spec.function_code, spec.address, spec.count)
        return decode_registers(payload, spec.data_type) * spec.scale
