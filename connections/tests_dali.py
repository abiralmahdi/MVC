"""Tests for the DALI driver against an in-process fake daliserver.

Run: python -m unittest connections.tests_dali -v   (no Django database needed)
"""
import socket
import struct
import threading
import time
import unittest

from connections.drivers import dali as driver


class FakeGear:
    """One DALI-2 control gear with part 252 active energy reporting (memory bank 202 only)."""

    def __init__(self, level=200, status=0x04, lamp_failure=False):
        self.level = level
        self.status = status
        self.lamp_failure = lamp_failure
        bank202 = [0] * 16
        bank202[0x00] = 0x0F                       # last accessible memory location
        bank202[0x02] = 0xFF                       # latch byte
        bank202[0x03] = 0x01                       # bank version
        bank202[0x04] = 0x00                       # active energy scale 10^0
        bank202[0x05:0x0B] = (123456).to_bytes(6, 'big')   # 123456 Wh
        bank202[0x0B] = 0xFF                       # active power scale 10^-1 (signed)
        bank202[0x0C:0x10] = (355).to_bytes(4, 'big')      # 35.5 W
        self.banks = {0: [0x0F] + [0] * 15, 202: bank202}


class FakeDaliServer:
    """Speaks the daliserver framing: 4-byte request 02 00 <addr> <cmd>, 4-byte reply."""

    def __init__(self, gears):
        self.gears = gears
        self.dtr0 = 0
        self.dtr1 = 0
        self.frames = []
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(5)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

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
        with conn:
            buffer = b''
            while True:
                try:
                    chunk = conn.recv(64)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while len(buffer) >= 4:
                    request, buffer = buffer[:4], buffer[4:]
                    ver, kind, a, b = struct.unpack('BBBB', request)
                    assert (ver, kind) == (2, 0)
                    self.frames.append((a, b))
                    answer = self.answer(a, b)
                    reply = struct.pack('BBBB', 2, 0, 0, 0) if answer is None else struct.pack('BBBB', 2, 1, answer, 0)
                    conn.sendall(reply)

    def answer(self, a, b):
        if a == 0xA3:          # DTR0
            self.dtr0 = b
            return None
        if a == 0xC3:          # DTR1
            self.dtr1 = b
            return None
        if a & 0x80 or not a & 0x01:
            return None        # group / broadcast / direct arc power: not emulated
        gear = self.gears.get(a >> 1)
        if gear is None:
            return None
        if b == 0xA0:          # QUERY ACTUAL LEVEL
            return gear.level
        if b == 0x90:          # QUERY STATUS
            return gear.status | (0x02 if gear.lamp_failure else 0)
        if b == 0x92:          # QUERY LAMP FAILURE
            return 0xFF if gear.lamp_failure else None
        if b == 0xC5:          # READ MEMORY LOCATION
            bank = gear.banks.get(self.dtr1)
            if bank is None or self.dtr0 >= len(bank):
                return None
            value = bank[self.dtr0]
            self.dtr0 = min(self.dtr0 + 1, 255)
            return value
        return None


class LevelCurveTests(unittest.TestCase):
    def test_curve_end_points(self):
        self.assertAlmostEqual(driver.level_to_percent(254), 100.0)
        self.assertAlmostEqual(driver.level_to_percent(1), 0.1)
        self.assertEqual(driver.level_to_percent(0), 0)

    def test_curve_mid_point(self):
        # IEC 62386-102: level 170 is about 10 %, 85 about 1 %
        self.assertAlmostEqual(driver.level_to_percent(170), 10 ** ((169 / (253 / 3)) - 1))
        self.assertAlmostEqual(driver.level_to_percent(170), 10.09, places=2)
        self.assertLess(driver.level_to_percent(100), driver.level_to_percent(101))


class DaliReadTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeDaliServer({5: FakeGear(level=200)})
        self.connection = {'port': self.server.port, 'timeout': 2}

    def tearDown(self):
        self.server.close()

    def test_reads_gear_values(self):
        points = {
            'Level': {'address': 5, 'value': 'actual_level', 'scale': 1.0},
            'Level %': {'address': 5, 'value': 'level_percent', 'scale': 1.0},
            'Lamp failure': {'address': 5, 'value': 'lamp_failure', 'scale': 1.0},
            'Gear failure': {'address': 5, 'value': 'gear_failure', 'scale': 1.0},
            'Status': {'address': 5, 'value': 'status', 'scale': 1.0},
            'Lamp 5 power': {'address': 5, 'value': 'active_power', 'scale': 2.0},
            'Lamp 5 energy': {'address': 5, 'value': 'active_energy', 'scale': 1.0},
        }
        values, errors = driver.read('127.0.0.1', self.connection, points)
        self.assertEqual(errors, [])
        self.assertEqual(values['Level'], 200)
        self.assertAlmostEqual(values['Level %'], driver.level_to_percent(200))
        self.assertEqual(values['Lamp failure'], 0)
        self.assertEqual(values['Gear failure'], 0)
        self.assertEqual(values['Status'], 0x04)
        self.assertAlmostEqual(values['Lamp 5 power'], 35.5)   # raw, scale not applied
        self.assertEqual(values['Lamp 5 energy'], 123456.0)
        self.assertIsInstance(values['Lamp 5 energy'], float)

    def test_lamp_failure_reported(self):
        self.server.gears[5].lamp_failure = True
        values, errors = driver.read('127.0.0.1', self.connection, {
            'Lamp failure': {'address': 5, 'value': 'lamp_failure', 'scale': 1.0},
            'Status': {'address': 5, 'value': 'status', 'scale': 1.0},
        })
        self.assertEqual(errors, [])
        self.assertEqual(values['Lamp failure'], 1)
        self.assertEqual(values['Status'], 0x06)

    def test_mask_level(self):
        self.server.gears[5].level = 255
        values, errors = driver.read('127.0.0.1', self.connection,
                                     {'Level': {'address': 5, 'value': 'actual_level', 'scale': 1.0}})
        self.assertIsNone(values['Level'])
        self.assertEqual(len(errors), 1)
        self.assertIn('MASK', errors[0])

    def test_missing_gear_and_unsupported_bank(self):
        points = {
            'Lamp 9 power': {'address': 9, 'value': 'active_power', 'scale': 1.0},
            'Lamp 9 level': {'address': 9, 'value': 'actual_level', 'scale': 1.0},
            'Lamp 9 lamp': {'address': 9, 'value': 'lamp_failure', 'scale': 1.0},
            'Lamp 5 apparent': {'address': 5, 'value': 'apparent_power', 'scale': 1.0},
            'Lamp 5 level': {'address': 5, 'value': 'actual_level', 'scale': 1.0},
        }
        values, errors = driver.read('127.0.0.1', self.connection, points)
        self.assertEqual(set(values), set(points))
        self.assertIsNone(values['Lamp 9 power'])
        self.assertIsNone(values['Lamp 9 level'])
        self.assertIsNone(values['Lamp 9 lamp'])
        self.assertIsNone(values['Lamp 5 apparent'])
        self.assertEqual(values['Lamp 5 level'], 200)
        self.assertIn('Lamp 9 power (A9 active_power): gear does not support DALI-2 energy reporting (memory bank 202)', errors)
        self.assertIn('Lamp 9 level (A9 actual_level): no response', errors)
        self.assertIn('Lamp 9 lamp (A9 lamp_failure): no response', errors)
        self.assertIn('Lamp 5 apparent (A5 apparent_power): gear does not support DALI-2 energy reporting (memory bank 203)', errors)
        self.assertEqual(len(errors), 4)

    def test_run_sequence_returns_value(self):
        from dali.address import GearShort
        from dali.memory import energy
        gateway = driver._make_gateway('127.0.0.1', self.server.port, 2)
        try:
            result = driver.run_sequence(gateway, energy.ActivePower.read(GearShort(5)))
        finally:
            gateway.close()
        self.assertEqual(float(result), 35.5)


class DaliConnectionTests(unittest.TestCase):
    def test_unreachable_gateway(self):
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()   # nothing listens on this port any more
        points = {'P': {'address': 5, 'value': 'active_power', 'scale': 1.0},
                  'L': {'address': 5, 'value': 'actual_level', 'scale': 1.0}}
        started = time.monotonic()
        values, errors = driver.read('127.0.0.1', {'port': port, 'timeout': 1}, points)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(values, {'P': None, 'L': None})
        self.assertEqual(len(errors), 1)
        self.assertIn('cannot connect to DALI gateway', errors[0])

    def test_silent_gateway_times_out(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)   # accepts the TCP connection but never answers
        try:
            started = time.monotonic()
            values, errors = driver.read('127.0.0.1', {'port': listener.getsockname()[1], 'timeout': 0.5}, {
                'A': {'address': 5, 'value': 'actual_level', 'scale': 1.0},
                'B': {'address': 6, 'value': 'actual_level', 'scale': 1.0},
            })
            self.assertLess(time.monotonic() - started, 2)
        finally:
            listener.close()
        self.assertEqual(values, {'A': None, 'B': None})
        self.assertEqual(len(errors), 1)
        self.assertIn('gateway connection lost', errors[0])


if __name__ == '__main__':
    unittest.main()
