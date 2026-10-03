"""KNX driver tests: payload decoding and connection failure handling.

Run with ``python -m unittest connections.tests_knx -v`` (no database needed).
"""
import socket
import threading
import time
import unittest

from connections.drivers import knx

try:
    import xknx  # noqa: F401
    HAVE_XKNX = True
except ImportError:  # pragma: no cover
    HAVE_XKNX = False


def closed_tcp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@unittest.skipUnless(HAVE_XKNX, 'xknx not installed')
class DecodeTests(unittest.TestCase):
    def encode(self, dpt, value):
        from xknx.dpt import DPTBase
        return DPTBase.parse_transcoder(dpt).to_knx(value)

    def test_numeric_dpts(self):
        from xknx.dpt import DPTArray
        cases = [('9.001', 21.5), ('14.056', 1234.5), ('13.010', -42), ('13.013', 123456), ('5.001', 50),
                 ('12.001', 4000000000), ('7.001', 300), ('9.024', -12.3)]
        for dpt, value in cases:
            with self.subTest(dpt=dpt):
                payload = self.encode(dpt, value)
                self.assertIsInstance(payload, DPTArray)
                self.assertAlmostEqual(knx.decode(dpt, payload), value, places=1)

    def test_raw_payloads(self):
        from xknx.dpt import DPTArray
        self.assertEqual(knx.decode('9.001', DPTArray((0x0C, 0x33))), 21.5)
        self.assertEqual(knx.decode('13.010', DPTArray((0x00, 0x00, 0x01, 0x00))), 256)
        self.assertEqual(knx.decode('5.001', DPTArray((0xFF,))), 100)

    def test_binary_dpt(self):
        from xknx.dpt import DPTBinary
        payload = self.encode('1.001', True)
        self.assertIsInstance(payload, DPTBinary)
        self.assertIs(knx.decode('1.001', payload), True)
        self.assertIs(knx.decode('1.001', DPTBinary(0)), False)

    def test_enum_dpt_maps_to_number(self):
        self.assertEqual(knx.decode('20.102', self.encode('20.102', 'comfort')), 1)

    def test_errors(self):
        from xknx.dpt import DPTArray, DPTBinary
        with self.assertRaises(ValueError):
            knx.decode('9.001', DPTArray((0x01,)))          # wrong length
        with self.assertRaises(ValueError):
            knx.decode('9.001', DPTBinary(1))                # wrong payload kind
        with self.assertRaises(ValueError):
            knx.decode('999.999', DPTArray((0x01,)))        # unknown DPT
        with self.assertRaises(ValueError):
            knx.decode('16.000', self.encode('16.000', 'hello'))   # string, not numeric

    def test_connection_config(self):
        from xknx.io import ConnectionType
        config = knx.connection_config('192.168.20.5', {'connection_type': 'tunneling_tcp', 'port': 3672,
                                                        'individual_address': '1.1.250', 'timeout': 3})
        self.assertEqual(config.connection_type, ConnectionType.TUNNELING_TCP)
        self.assertEqual((config.gateway_ip, config.gateway_port), ('192.168.20.5', 3672))
        self.assertEqual(str(config.individual_address), '1.1.250')
        config = knx.connection_config('192.168.20.5', {'connection_type': 'routing', 'individual_address': ''})
        self.assertEqual(config.connection_type, ConnectionType.ROUTING)
        self.assertIsNone(config.individual_address)


@unittest.skipUnless(HAVE_XKNX, 'xknx not installed')
class UnreachableTests(unittest.TestCase):
    points = {
        'Room Temp': {'group_address': '1/2/3', 'dpt': '9.001', 'scale': 1.0},
        'Power': {'group_address': '1/2/4', 'dpt': '14.056', 'scale': 1.0},
    }

    def check_unreachable(self, connection_type, timeout):
        port = closed_tcp_port()
        started = time.monotonic()
        values, errors = knx.read('127.0.0.1', {'connection_type': connection_type, 'port': port,
                                                'individual_address': '', 'timeout': timeout}, self.points)
        elapsed = time.monotonic() - started
        self.assertEqual(values, {'Room Temp': None, 'Power': None})
        self.assertEqual(len(errors), 1, errors)
        self.assertTrue(errors[0].startswith(f'cannot connect to KNX/IP interface 127.0.0.1:{port}: '), errors)
        self.assertLess(elapsed, timeout + 2)

    def test_tcp_tunnel_unreachable(self):
        self.check_unreachable('tunneling_tcp', 1)

    def test_udp_tunnel_unreachable(self):
        self.check_unreachable('tunneling', 1.5)

    def test_callable_from_threads(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(knx.read(
            '127.0.0.1', {'connection_type': 'tunneling_tcp', 'port': closed_tcp_port(), 'timeout': 1},
            self.points))) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(len(results), 3)
        for values, errors in results:
            self.assertEqual(values, {'Room Temp': None, 'Power': None})
            self.assertTrue(errors[0].startswith('cannot connect'), errors)


class MissingLibraryTests(unittest.TestCase):
    def test_all_points_none_when_library_missing(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith('xknx'):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        builtins.__import__ = fake_import
        try:
            values, errors = knx.read('127.0.0.1', {'port': 3671, 'timeout': 1},
                                      {'A': {'group_address': '1/2/3', 'dpt': '9.001', 'scale': 1.0}})
        finally:
            builtins.__import__ = real_import
        self.assertEqual(values, {'A': None})
        self.assertIn('xknx', errors[0])


if __name__ == '__main__':
    unittest.main()
