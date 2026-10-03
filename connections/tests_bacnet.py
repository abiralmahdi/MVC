"""BACnet/IP driver tests against a real bacpypes3 server on loopback.

Run with ``python -m unittest connections.tests_bacnet -v`` (no database needed).
"""
import asyncio
import random
import socket
import threading
import time
import unittest

from connections.drivers import bacnet

try:
    import bacpypes3  # noqa: F401
    HAVE_BACPYPES3 = True
except ImportError:  # pragma: no cover
    HAVE_BACPYPES3 = False


def free_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class BACnetServer:
    """A bacpypes3 device with a few objects, running its own event loop in a daemon thread."""

    def __init__(self, port):
        self.port = port
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.error = None
        self.app = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._start())
        except Exception as exc:  # pragma: no cover
            self.error = exc
            self.ready.set()
            return
        self.ready.set()
        self.loop.run_forever()
        self.app.close()
        self.loop.run_until_complete(asyncio.sleep(0))
        self.loop.close()

    async def _start(self):
        from types import SimpleNamespace

        from bacpypes3.app import Application
        from bacpypes3.local.analog import AnalogValueObject
        from bacpypes3.local.binary import BinaryValueObject
        from bacpypes3.local.multistate import MultiStateValueObject

        self.app = Application.from_args(SimpleNamespace(
            vendoridentifier=999, instance=random.randint(1000, 2000), name='TestDevice',
            address=f'127.0.0.1:{self.port}', network=0, foreign=None, ttl=30, bbmd=None))
        flags = [0, 0, 0, 0]
        self.app.add_object(AnalogValueObject(
            objectIdentifier=('analog-value', 1), objectName='Supply Temp', presentValue=21.5, statusFlags=flags))
        self.app.add_object(BinaryValueObject(
            objectIdentifier=('binary-value', 2), objectName='Pump', presentValue='active', statusFlags=flags))
        self.app.add_object(BinaryValueObject(
            objectIdentifier=('binary-value', 3), objectName='Fan', presentValue='inactive', statusFlags=flags))
        self.app.add_object(MultiStateValueObject(
            objectIdentifier=('multi-state-value', 4), objectName='Mode', presentValue=3, numberOfStates=4,
            statusFlags=flags))
        # make sure the socket is bound before the tests send anything
        for link in self.app.link_layers.values():
            server = getattr(link, 'server', None)
            if server is not None and getattr(server, '_transport_tasks', None):
                await asyncio.gather(*server._transport_tasks)

    def start(self):
        self.thread.start()
        self.ready.wait(10)
        if self.error:
            raise self.error

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


def point(object_type, instance, prop='present-value'):
    return {'object_type': object_type, 'instance': instance, 'property': prop, 'scale': 1.0}


class HelperTests(unittest.TestCase):
    def test_device_address(self):
        self.assertEqual(bacnet.device_address('192.168.10.20', {'port': 47808}), '192.168.10.20:47808')
        self.assertEqual(bacnet.device_address('192.168.10.20', {'port': 47809, 'network': None, 'mac': None}),
                         '192.168.10.20:47809')
        self.assertEqual(bacnet.device_address('192.168.10.20', {'port': 47808, 'network': 5, 'mac': 12}),
                         '5:12@192.168.10.20:47808')

    @unittest.skipUnless(HAVE_BACPYPES3, 'bacpypes3 not installed')
    def test_routed_address_parses(self):
        from bacpypes3.pdu import Address
        address = Address(bacnet.device_address('192.168.10.20', {'port': 47808, 'network': 1205, 'mac': 12}))
        self.assertEqual(address.addrNet, 1205)
        self.assertEqual(address.addrAddr, bytes([12]))
        self.assertIsNotNone(address.addrRoute)

    @unittest.skipUnless(HAVE_BACPYPES3, 'bacpypes3 not installed')
    def test_convert(self):
        from bacpypes3.basetypes import BinaryPV
        from bacpypes3.primitivedata import Boolean, CharacterString, Double, Integer, Real, Unsigned
        self.assertEqual(bacnet.convert(Real(21.5)), 21.5)
        self.assertEqual(bacnet.convert(Double(1.25)), 1.25)
        self.assertEqual(bacnet.convert(Unsigned(7)), 7)
        self.assertEqual(bacnet.convert(Integer(-3)), -3)
        self.assertEqual(bacnet.convert(BinaryPV('active')), 1)
        self.assertEqual(bacnet.convert(BinaryPV('inactive')), 0)
        self.assertIs(bacnet.convert(Boolean(True)), True)
        with self.assertRaises(ValueError):
            bacnet.convert(CharacterString('hello'))
        with self.assertRaises(ValueError):
            bacnet.convert(None)


@unittest.skipUnless(HAVE_BACPYPES3, 'bacpypes3 not installed')
class LoopbackReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_udp_port()
        cls.server = BACnetServer(cls.port)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def connection(self, **extra):
        return {'port': self.port, 'device_instance': None, 'network': None, 'mac': None, 'timeout': 2, **extra}

    def test_reads_values(self):
        points = {
            'Supply Temp': point('analog-value', 1),
            'Pump': point('binary-value', 2),
            'Fan': point('binary-value', 3),
            'Mode': point('multi-state-value', 4),
        }
        values, errors = bacnet.read('127.0.0.1', self.connection(), points)
        self.assertEqual(errors, [])
        self.assertEqual(values, {'Supply Temp': 21.5, 'Pump': 1, 'Fan': 0, 'Mode': 3})
        self.assertIsInstance(values['Supply Temp'], float)

    def test_unknown_object_and_non_numeric(self):
        points = {
            'Missing': point('analog-value', 99),
            'Name': point('analog-value', 1, 'object-name'),
            'Bogus': point('analog-value', 1, 'no-such-property'),
            'Supply Temp': point('analog-value', 1),
        }
        values, errors = bacnet.read('127.0.0.1', self.connection(), points)
        self.assertEqual(values, {'Missing': None, 'Name': None, 'Bogus': None, 'Supply Temp': 21.5})
        self.assertEqual(len(errors), 3, errors)
        self.assertTrue(errors[0].startswith('Missing (analog-value,99 present-value): error'), errors)
        self.assertIn('unknown-object', errors[0])
        self.assertIn('not numeric', errors[1])
        self.assertTrue(errors[2].startswith('Bogus (analog-value,1 no-such-property): '), errors)

    def test_concurrent_reads_from_threads(self):
        points = {'Supply Temp': point('analog-value', 1), 'Mode': point('multi-state-value', 4)}
        results = []

        def work():
            results.append(bacnet.read('127.0.0.1', self.connection(), points))

        threads = [threading.Thread(target=work) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        self.assertEqual(len(results), 4)
        for values, errors in results:
            self.assertEqual(errors, [])
            self.assertEqual(values, {'Supply Temp': 21.5, 'Mode': 3})

    def test_unreachable_device_times_out(self):
        closed = free_udp_port()
        points = {'Supply Temp': point('analog-value', 1), 'Mode': point('multi-state-value', 4)}
        started = time.monotonic()
        values, errors = bacnet.read('127.0.0.1', self.connection(port=closed, timeout=1), points)
        elapsed = time.monotonic() - started
        self.assertEqual(values, {'Supply Temp': None, 'Mode': None})
        self.assertTrue(errors, errors)
        self.assertTrue(errors[0].startswith('Supply Temp (analog-value,1 present-value): timeout'), errors)
        self.assertIn('did not respond', errors[-1])
        self.assertLess(elapsed, 4)


class MissingLibraryTests(unittest.TestCase):
    def test_all_points_none_when_library_missing(self):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith('bacpypes3'):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        builtins.__import__ = fake_import
        try:
            values, errors = bacnet.read('127.0.0.1', {'port': 47808, 'timeout': 1}, {'A': point('analog-input', 1)})
        finally:
            builtins.__import__ = real_import
        self.assertEqual(values, {'A': None})
        self.assertIn('bacpypes3', errors[0])


if __name__ == '__main__':
    unittest.main()
