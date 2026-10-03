"""Tests for the M-Bus driver against an in-process fake transparent TCP M-Bus gateway.

Run: python -m unittest connections.tests_mbus -v   (no Django database needed)
"""
import socket
import threading
import time
import unittest

from connections.drivers import mbus as driver

SECONDARY = '123456782D2C0104'   # id 12345678, manufacturer 0x2C2D, version 01, medium 04 (heat)

RECORDS = (
    bytes([0x04, 0x03]) + (12345).to_bytes(4, 'little')      # 0: energy, int32, Wh
    + bytes([0x0C, 0x14, 0x78, 0x56, 0x34, 0x12])            # 1: volume, 8 digit BCD, 0.01 m3 -> 123456.78
    + bytes([0x02, 0x5B]) + (65).to_bytes(2, 'little')       # 2: flow temperature, int16, °C
    + bytes([0x04, 0x6D, 0x0F, 0x0C, 0x6E, 0x18])            # 3: date/time (type F), not numeric
)
SECOND_TELEGRAM = bytes([0x02, 0x5F]) + (40).to_bytes(2, 'little')   # return temperature, °C


def long_frame(address, records, more_follow=False):
    """RSP_UD long frame, CI 0x72 variable data structure, with correct checksum."""
    header = bytes([0x08, address, 0x72,
                    0x78, 0x56, 0x34, 0x12,   # identification number (BCD, LSB first)
                    0x2D, 0x2C,               # manufacturer
                    0x01, 0x04,               # version, medium
                    0x2A, 0x00, 0x00, 0x00])  # access number, status, signature
    body = header + records + (b'\x1f' if more_follow else b'')
    return bytes([0x68, len(body), len(body), 0x68]) + body + bytes([sum(body) % 256, 0x16])


class FakeMBusGateway:
    """Primary address 1: one telegram. Primary address 2: two telegrams (multi-telegram).
    Secondary address SECONDARY selects meter 1. Every other address stays silent."""

    def __init__(self):
        self.selected = False
        self.telegram = {}
        self.received = []
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(5)
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self):
        self.listener.close()

    def _serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        buffer = b''
        with conn:
            while True:
                try:
                    chunk = conn.recv(256)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while buffer:
                    if buffer[0] == 0x10:
                        if len(buffer) < 5:
                            break
                        frame, buffer = buffer[:5], buffer[5:]
                        answer = self.short(frame[1], frame[2])
                    elif buffer[0] == 0x68:
                        if len(buffer) < 4 or len(buffer) < buffer[1] + 6:
                            break
                        size = buffer[1] + 6
                        frame, buffer = buffer[:size], buffer[size:]
                        answer = self.long(frame)
                    else:
                        buffer = buffer[1:]
                        continue
                    self.received.append(frame)
                    if answer:
                        conn.sendall(answer)

    def short(self, control, address):
        if control == 0x40:                                  # SND_NKE
            if address in (1, 2):
                self.telegram[address] = 0
                return b'\xe5'
            return None
        if control & 0xCF == 0x4B:                           # REQ_UD2 (with or without FCB/FCV)
            if address == 0xFD and self.selected:
                return long_frame(0, RECORDS)
            if address == 1:
                return long_frame(1, RECORDS)
            if address == 2:
                count = self.telegram.get(2, 0)
                self.telegram[2] = count + 1
                return long_frame(2, RECORDS, more_follow=True) if count == 0 else long_frame(2, SECOND_TELEGRAM)
        return None

    def long(self, frame):
        control, address, ci = frame[4], frame[5], frame[6]
        if control & 0xDF == 0x53 and address == 0xFD and ci == 0x52:   # SND_UD select slave
            data = frame[7:15]
            # id number LSB first on the wire, then manufacturer, version, medium (as in the RSP_UD header)
            wanted = '{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}{:02X}'.format(
                data[3], data[2], data[1], data[0], data[4], data[5], data[6], data[7])
            self.selected = wanted == SECONDARY
            return b'\xe5' if self.selected else None
        return None


def points(*indexes):
    return {f'r{i}': {'record': i, 'scale': 1.0} for i in indexes}


class MBusReadTests(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeMBusGateway()
        self.connection = {'transport': 'tcp', 'port': self.gateway.port, 'baudrate': 2400,
                           'address_mode': 'primary', 'primary_address': 1, 'timeout': 1}

    def tearDown(self):
        self.gateway.close()

    def test_read_records_by_index(self):
        values, errors = driver.read('127.0.0.1', self.connection, {
            'Energy': {'record': 0, 'scale': 0.001},
            'Volume': {'record': 1, 'scale': 1.0},
            'Flow temperature': {'record': 2, 'scale': 1.0},
        })
        self.assertEqual(errors, [])
        self.assertEqual(values['Energy'], 12345.0)          # raw Wh, scale not applied
        self.assertAlmostEqual(values['Volume'], 123456.78)
        self.assertEqual(values['Flow temperature'], 65.0)
        self.assertTrue(all(isinstance(v, float) for v in values.values()))
        # SND_NKE then REQ_UD2 to primary address 1
        self.assertEqual(self.gateway.received[0], bytes([0x10, 0x40, 0x01, 0x41, 0x16]))
        self.assertEqual(self.gateway.received[1], bytes([0x10, 0x5B, 0x01, 0x5C, 0x16]))

    def test_bad_index_and_non_numeric(self):
        values, errors = driver.read('127.0.0.1', self.connection, points(0, 3, 9))
        self.assertEqual(values, {'r0': 12345.0, 'r3': None, 'r9': None})
        self.assertEqual(len(errors), 2)
        self.assertIn('r3 (record 3): value', errors[0])
        self.assertIn('not numeric', errors[0])
        self.assertEqual(errors[1], 'r9 (record 9): record index out of range, the meter sent 4 records (0-3)')

    def test_discover(self):
        records = driver.discover('127.0.0.1', self.connection)
        self.assertEqual([r['record'] for r in records], [0, 1, 2, 3])
        self.assertEqual(records[0]['value'], 12345.0)
        self.assertEqual(records[0]['unit'], 'Wh')
        self.assertEqual(records[0]['type'], 'ENERGY_WH')
        self.assertEqual(records[0]['function'], 'INSTANTANEOUS_VALUE')
        self.assertEqual(records[1]['unit'], 'm^3')
        self.assertEqual(records[2]['type'], 'FLOW_TEMPERATURE')
        self.assertFalse(records[3]['numeric'])
        self.assertEqual(records[3]['value'], '2011-08-14T12:15')

    def test_multi_telegram(self):
        values, errors = driver.read('127.0.0.1', dict(self.connection, primary_address=2), points(2, 4))
        self.assertEqual(errors, [])
        self.assertEqual(values, {'r2': 65.0, 'r4': 40.0})

    def test_secondary_address(self):
        connection = dict(self.connection, address_mode='secondary', secondary_address=SECONDARY.lower())
        connection.pop('primary_address')
        values, errors = driver.read('127.0.0.1', connection, points(0, 2))
        self.assertEqual(errors, [])
        self.assertEqual(values, {'r0': 12345.0, 'r2': 65.0})
        self.assertEqual(self.gateway.received[1][:3], bytes([0x10, 0x5B, 0xFD]))

    def test_unknown_secondary_address(self):
        connection = dict(self.connection, address_mode='secondary', secondary_address='0000000100000000', timeout=0.5)
        values, errors = driver.read('127.0.0.1', connection, points(0))
        self.assertEqual(values, {'r0': None})
        self.assertEqual(len(errors), 1)
        self.assertIn('no response to selection of secondary address 0000000100000000', errors[0])

    def test_silent_primary_address(self):
        started = time.monotonic()
        values, errors = driver.read('127.0.0.1', dict(self.connection, primary_address=7, timeout=0.5), points(0, 1))
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(values, {'r0': None, 'r1': None})
        self.assertEqual(errors, ['M-Bus: no response from primary address 7 (timeout 0.5 s)'])


class MBusConnectionTests(unittest.TestCase):
    def test_closed_port(self):
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()
        connection = {'transport': 'tcp', 'port': port, 'baudrate': 2400,
                      'address_mode': 'primary', 'primary_address': 1, 'timeout': 1}
        started = time.monotonic()
        values, errors = driver.read('127.0.0.1', connection, points(0))
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(values, {'r0': None})
        self.assertEqual(len(errors), 1)
        self.assertIn(f'cannot open 127.0.0.1:{port}', errors[0])
        with self.assertRaises(RuntimeError):
            driver.discover('127.0.0.1', connection)

    def test_bad_serial_port(self):
        connection = {'transport': 'serial', 'serial_port': 'COM_DOES_NOT_EXIST', 'baudrate': 2400,
                      'address_mode': 'primary', 'primary_address': 1, 'timeout': 1}
        values, errors = driver.read('', connection, points(0))
        self.assertEqual(values, {'r0': None})
        self.assertIn('cannot open serial port COM_DOES_NOT_EXIST', errors[0])


if __name__ == '__main__':
    unittest.main()
