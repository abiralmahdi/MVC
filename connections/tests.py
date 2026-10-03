import socket
import struct
import threading

from django.test import TestCase

from connections import datastorage
from connections.modbus import ModbusTcpClient, parse_register_spec
from dashboard.models import LatestMeterReading, MeterReading
from dynamic.models import Areas, Buildings, LoadType, Meters, Site


class FakeModbusServer(threading.Thread):
    """Answers FC3/FC4 requests with float32 value = address / 10."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.running = True

    def run(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                while True:
                    header = conn.recv(12)
                    if len(header) < 12:
                        break
                    tid, _, _, unit, fc, address, count = struct.unpack('>HHHBBHH', header)
                    if address == 999:  # simulate "illegal data address"
                        conn.sendall(struct.pack('>HHHBBB', tid, 0, 3, unit, fc | 0x80, 2))
                        continue
                    payload = struct.pack('>f', address / 10.0) + b'\x00' * (count * 2 - 4)
                    body = struct.pack('>BB', fc, len(payload)) + payload
                    # send in two chunks to exercise exact-length reads
                    frame = struct.pack('>HHHB', tid, 0, len(body) + 1, unit) + body
                    conn.sendall(frame[:5])
                    conn.sendall(frame[5:])

    def stop(self):
        self.running = False
        self.sock.close()


class RegisterSpecTests(TestCase):
    def test_all_stored_shapes_are_accepted(self):
        self.assertEqual(parse_register_spec(55).address, 55)
        self.assertEqual(parse_register_spec("55").address, 55)
        spec = parse_register_spec([3, 19])
        self.assertEqual((spec.function_code, spec.address), (3, 19))
        spec = parse_register_spec({"fc": 4, "address": 7, "type": "int16", "scale": 0.1})
        self.assertEqual((spec.function_code, spec.address, spec.data_type, spec.scale), (4, 7, 'int16', 0.1))

    def test_invalid_definitions_raise(self):
        for bad in ([5, 1], {"fc": 4}, "ns=1;s=x", [4], True, {"address": 70000}):
            with self.assertRaises(ValueError):
                parse_register_spec(bad)


class ModbusPollingTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = FakeModbusServer()
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        super().tearDownClass()

    def setUp(self):
        site = Site.objects.create(name='S', latitude='23.8', longitude='90.4')
        area = Areas.objects.create(name='A', building=Buildings.objects.create(name='B', site=site))
        self.meter = Meters.objects.create(
            name='M1', ip='127.0.0.1', area=area, loadType=LoadType.objects.create(name='L'),
            meterType='Electricity Meter', protocol='modbus',
            connection={'port': self.server.port, 'unit_id': 1, 'timeout': 2},
            # bare int (what the old Settings form saved), list and dict shapes together
            registerMapping={"Voltage L1N": 2300, "Current L1": [3, 125], "Energy": {"fc": 4, "address": 50}},
        )

    def test_client_reads_float(self):
        with ModbusTcpClient('127.0.0.1', self.server.port, 1, 2) as client:
            self.assertAlmostEqual(client.read_value(parse_register_spec([4, 10])), 1.0, places=5)

    def test_meter_with_old_mapping_shape_is_polled_and_stored(self):
        result = datastorage.poll_meter(self.meter)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.data, {"Voltage L1N": 230.0, "Current L1": 12.5, "Energy": 5.0})
        self.assertTrue(datastorage.store_poll_result(self.meter, result))
        self.assertEqual(MeterReading.objects.filter(meter=self.meter).count(), 1)
        datastorage.store_poll_result(self.meter, datastorage.poll_meter(self.meter))
        self.assertEqual(LatestMeterReading.objects.filter(meter=self.meter).count(), 1)

    def test_exception_responses_are_reported_not_silent(self):
        self.meter.registerMapping = {"Voltage L1N": 2300, "Broken": 999}
        result = datastorage.poll_meter(self.meter)
        self.assertEqual(result.data["Voltage L1N"], 230.0)
        self.assertIsNone(result.data["Broken"])
        self.assertTrue(any('illegal data address' in e for e in result.errors))

    def test_unreachable_meter_reports_error(self):
        self.meter.connection = {'port': 1, 'unit_id': 1, 'timeout': 1}  # nothing listens there
        result = datastorage.poll_meter(self.meter)
        self.assertFalse(result.ok)
        self.assertTrue(result.errors)
        self.assertFalse(datastorage.store_poll_result(self.meter, result))
