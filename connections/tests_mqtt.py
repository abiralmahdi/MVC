"""Tests for the MQTT driver against an in-process fake MQTT 3.1.1 broker (QoS 0 only).

Run with:  python -m unittest connections.tests_mqtt -v
Needs no Django settings and no database.
"""
import socket
import struct
import threading
import time
import unittest

from connections.drivers import mqtt as driver


# ------------------------------------------------------------------ fake broker
def _encode_length(length):
    out = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length:
            byte |= 0x80
        out.append(byte)
        if not length:
            return bytes(out)


def _string(text):
    data = text.encode('utf-8')
    return struct.pack('!H', len(data)) + data


def topic_matches(topic_filter, topic):
    fparts, tparts = topic_filter.split('/'), topic.split('/')
    if topic.startswith('$') and fparts[0] in ('#', '+'):
        return False
    for i, part in enumerate(fparts):
        if part == '#':
            return True
        if i >= len(tparts) or (part != '+' and part != tparts[i]):
            return False
    return len(fparts) == len(tparts)


class FakeBroker:
    """Just enough of an MQTT 3.1.1 broker: CONNECT, SUBSCRIBE, UNSUBSCRIBE, PUBLISH (QoS 0, retain),
    PINGREQ and DISCONNECT."""

    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(16)
        self.port = self.server.getsockname()[1]
        self.lock = threading.Lock()
        self.retained = {}          # topic -> payload
        self.sessions = {}          # socket -> set of filters
        self.connects = 0
        self.running = True
        self.threads = []
        self._spawn(self._accept)

    def _spawn(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True, name='fake-mqtt-broker')
        thread.start()
        self.threads.append(thread)

    def _accept(self):
        while self.running:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._spawn(self._serve, conn)

    @staticmethod
    def _recv_exact(conn, count):
        data = b''
        while len(data) < count:
            chunk = conn.recv(count - len(data))
            if not chunk:
                raise ConnectionError('closed')
            data += chunk
        return data

    def _read_packet(self, conn):
        header = self._recv_exact(conn, 1)[0]
        multiplier, length = 1, 0
        while True:
            byte = self._recv_exact(conn, 1)[0]
            length += (byte & 0x7F) * multiplier
            if not byte & 0x80:
                break
            multiplier *= 128
        return header, self._recv_exact(conn, length) if length else b''

    def _send(self, conn, header, body=b''):
        try:
            conn.sendall(bytes([header]) + _encode_length(len(body)) + body)
        except OSError:
            pass

    def _publish_packet(self, topic, payload, retain):
        return 0x30 | (0x01 if retain else 0), _string(topic) + payload

    def _serve(self, conn):
        try:
            while self.running:
                header, body = self._read_packet(conn)
                kind = header >> 4
                if kind == 1:                                   # CONNECT
                    with self.lock:
                        self.sessions[conn] = set()
                        self.connects += 1
                    self._send(conn, 0x20, b'\x00\x00')
                elif kind == 8:                                 # SUBSCRIBE
                    packet_id, pos, filters = body[:2], 2, []
                    while pos < len(body):
                        (size,) = struct.unpack('!H', body[pos:pos + 2])
                        filters.append(body[pos + 2:pos + 2 + size].decode('utf-8'))
                        pos += 2 + size + 1
                    with self.lock:
                        self.sessions.setdefault(conn, set()).update(filters)
                        retained = [(t, p) for t, p in self.retained.items() if any(topic_matches(f, t) for f in filters)]
                    self._send(conn, 0x90, packet_id + b'\x00' * len(filters))
                    for topic, payload in retained:
                        self._send(conn, *self._publish_packet(topic, payload, True))
                elif kind == 10:                                # UNSUBSCRIBE
                    self._send(conn, 0xB0, body[:2])
                elif kind == 3:                                 # PUBLISH (QoS 0)
                    (size,) = struct.unpack('!H', body[:2])
                    topic = body[2:2 + size].decode('utf-8')
                    self.publish(topic, body[2 + size:], retain=bool(header & 0x01))
                elif kind == 12:                                # PINGREQ
                    self._send(conn, 0xD0)
                elif kind == 14:                                # DISCONNECT
                    break
        except (ConnectionError, OSError):
            pass
        finally:
            with self.lock:
                self.sessions.pop(conn, None)
            try:
                conn.close()
            except OSError:
                pass

    def publish(self, topic, payload, retain=False):
        if isinstance(payload, str):
            payload = payload.encode('utf-8')
        with self.lock:
            if retain:
                if payload:
                    self.retained[topic] = payload
                else:
                    self.retained.pop(topic, None)
            targets = [c for c, filters in self.sessions.items() if any(topic_matches(f, topic) for f in filters)]
        for conn in targets:
            self._send(conn, *self._publish_packet(topic, payload, False))

    def kick_all(self):
        """Drop every client connection (simulates a broker restart)."""
        with self.lock:
            conns = list(self.sessions)
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def stop(self):
        self.running = False
        try:
            self.server.close()
        except OSError:
            pass
        self.kick_all()
        for thread in self.threads:
            thread.join(timeout=2)


def free_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def paho_threads():
    return [t for t in threading.enumerate() if t.name.startswith('paho-mqtt-client') and t.is_alive()]


# ------------------------------------------------------------------ extract
class ExtractTests(unittest.TestCase):
    def test_plain_numbers(self):
        self.assertEqual(driver.extract(b'42', ''), 42.0)
        self.assertEqual(driver.extract(b' -3.5\n', ''), -3.5)
        self.assertEqual(driver.extract(b'1e3', None), 1000.0)

    def test_booleans(self):
        for word, expected in (('true', 1), ('false', 0), ('on', 1), ('off', 0), ('ON', 1), ('OFF', 0)):
            self.assertEqual(driver.extract(word.encode(), ''), expected, word)
        self.assertEqual(driver.extract(b'{"relay": true}', 'relay'), 1.0)
        self.assertEqual(driver.extract(b'{"state": "OFF"}', 'state'), 0.0)

    def test_nested_json(self):
        payload = b'{"ENERGY": {"Power": 123.4, "Total": "5.5"}}'
        self.assertEqual(driver.extract(payload, 'ENERGY.Power'), 123.4)
        self.assertEqual(driver.extract(payload, 'ENERGY.Total'), 5.5)

    def test_list_index(self):
        payload = b'{"values": [{"v": 1}, {"v": 2.25}]}'
        self.assertEqual(driver.extract(payload, 'values.1.v'), 2.25)
        self.assertEqual(driver.extract(b'[10, 20]', '1'), 20.0)

    def test_missing_key(self):
        with self.assertRaisesRegex(ValueError, 'not found'):
            driver.extract(b'{"a": {"b": 1}}', 'a.c')
        with self.assertRaisesRegex(ValueError, 'out of range'):
            driver.extract(b'{"values": [1]}', 'values.3')

    def test_non_numeric(self):
        with self.assertRaises(ValueError):
            driver.extract(b'hello', '')
        with self.assertRaises(ValueError):
            driver.extract(b'{"a": "hello"}', 'a')
        with self.assertRaises(ValueError):
            driver.extract(b'{"a": null}', 'a')
        with self.assertRaises(ValueError):
            driver.extract(b'{"a": {"b": 1}}', 'a')
        with self.assertRaisesRegex(ValueError, 'not valid JSON'):
            driver.extract(b'12 W', 'a')
        with self.assertRaisesRegex(ValueError, 'not an object'):
            driver.extract(b'12', 'a')
        with self.assertRaises(ValueError):
            driver.extract(b'', '')
        with self.assertRaises(ValueError):
            driver.extract(b'nan', '')


# ------------------------------------------------------------------ against the fake broker
class BrokerTestCase(unittest.TestCase):
    def setUp(self):
        self.broker = FakeBroker()
        self.addCleanup(self.broker.stop)
        self.addCleanup(driver.shutdown_listeners)

    def tearDown(self):
        driver.shutdown_listeners()
        deadline = time.monotonic() + 3
        while paho_threads() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(paho_threads(), [], 'paho network threads leaked')

    def connection(self, **extra):
        return {'port': self.broker.port, 'tls': False, 'username': '', 'password': '', 'client_id': '',
                'wait': 1.5, 'max_age': 900, **extra}


class OneShotTests(BrokerTestCase):
    def test_retained_values(self):
        self.broker.publish('plant/m1/power', '1500.5', retain=True)
        self.broker.publish('plant/m1/relay', 'ON', retain=True)
        points = {'Power': {'topic': 'plant/m1/power', 'json_path': '', 'scale': 0.001},
                  'Relay': {'topic': 'plant/m1/relay', 'json_path': '', 'scale': 1}}
        started = time.monotonic()
        values, errors = driver.read('127.0.0.1', self.connection(_one_shot=True), points)
        self.assertEqual(errors, [])
        self.assertEqual(values, {'Power': 1500.5, 'Relay': 1.0})   # raw, not scaled
        self.assertLess(time.monotonic() - started, 1.4, 'should not wait once every topic arrived')
        self.assertEqual(paho_threads(), [])

    def test_json_path(self):
        self.broker.publish('tele/meter/SENSOR', '{"ENERGY": {"Power": 88, "Voltage": 231.2}, "values": [{"v": 7}]}',
                            retain=True)
        points = {'Power': {'topic': 'tele/meter/SENSOR', 'json_path': 'ENERGY.Power'},
                  'Voltage': {'topic': 'tele/meter/SENSOR', 'json_path': 'ENERGY.Voltage'},
                  'First': {'topic': 'tele/meter/SENSOR', 'json_path': 'values.0.v'},
                  'Bad': {'topic': 'tele/meter/SENSOR', 'json_path': 'ENERGY.Current'}}
        values, errors = driver.read('127.0.0.1', self.connection(_one_shot=True), points)
        self.assertEqual(values, {'Power': 88.0, 'Voltage': 231.2, 'First': 7.0, 'Bad': None})
        self.assertEqual(len(errors), 1)
        self.assertIn('Bad (tele/meter/SENSOR)', errors[0])
        self.assertIn('Current', errors[0])

    def test_missing_topic(self):
        self.broker.publish('a/present', '1', retain=True)
        points = {'Present': {'topic': 'a/present'}, 'Power': {'topic': 'a/missing'}}
        started = time.monotonic()
        values, errors = driver.read('127.0.0.1', self.connection(_one_shot=True, wait=1), points)
        elapsed = time.monotonic() - started
        self.assertEqual(values, {'Present': 1.0, 'Power': None})
        self.assertEqual(errors, ['Power (a/missing): no message within 1 s'])
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 3)

    def test_bad_port(self):
        points = {'Power': {'topic': 'x/y'}}
        started = time.monotonic()
        values, errors = driver.read('127.0.0.1', self.connection(_one_shot=True, port=free_port(), wait=2), points)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(values, {'Power': None})
        self.assertEqual(len(errors), 1)
        self.assertIn('failed', errors[0])

    def test_wildcard_point_rejected(self):
        values, errors = driver.read('127.0.0.1', self.connection(_one_shot=True, wait=0.5),
                                     {'Power': {'topic': 'plant/#'}})
        self.assertEqual(values, {'Power': None})
        self.assertIn('wildcard', errors[0])

    def test_discover(self):
        self.broker.publish('site/m1/power', '12', retain=True)
        self.broker.publish('site/m2/state', '{"on": true}', retain=True)
        self.broker.publish('other/x', 'x' * 500, retain=True)
        entries = driver.discover('127.0.0.1', self.connection(wait=0.8))
        self.assertEqual([e['topic'] for e in entries], ['other/x', 'site/m1/power', 'site/m2/state'])
        self.assertEqual(entries[1], {'topic': 'site/m1/power', 'payload': '12', 'retained': True})
        self.assertEqual(len(entries[0]['payload']), 200)

        entries = driver.discover('127.0.0.1', self.connection(wait=0.5, _discover_topic='site/+/power'))
        self.assertEqual([e['topic'] for e in entries], ['site/m1/power'])

    def test_discover_bad_port(self):
        with self.assertRaises(ConnectionError):
            driver.discover('127.0.0.1', self.connection(port=free_port(), wait=1))


class ListenerTests(BrokerTestCase):
    def poll(self, connection, points, until, timeout=4):
        deadline = time.monotonic() + timeout
        while True:
            values, errors = driver.read('127.0.0.1', connection, points)
            if until(values, errors) or time.monotonic() > deadline:
                return values, errors
            time.sleep(0.1)

    def test_retained_value_and_reuse(self):
        self.broker.publish('m/power', '10', retain=True)
        connection = self.connection()
        values, errors = driver.read('127.0.0.1', connection, {'Power': {'topic': 'm/power'}})
        self.assertEqual((values, errors), ({'Power': 10.0}, []))
        self.assertEqual(len(paho_threads()), 1)
        # a second read reuses the same listener and connection
        driver.read('127.0.0.1', connection, {'Power': {'topic': 'm/power'}})
        self.assertEqual(len(paho_threads()), 1)
        self.assertEqual(self.broker.connects, 1)

    def test_new_non_retained_publish(self):
        connection = self.connection(wait=0.5)
        points = {'Power': {'topic': 'live/power', 'json_path': 'p'}}
        started = time.monotonic()
        values, errors = driver.read('127.0.0.1', connection, points)
        self.assertEqual(values, {'Power': None})
        self.assertEqual(errors, ['Power (live/power): no message within 0.5 s'])
        # later reads of a topic subscribed long ago do not wait again
        time.sleep(0.6)
        started = time.monotonic()
        driver.read('127.0.0.1', connection, points)
        self.assertLess(time.monotonic() - started, 0.3)

        self.broker.publish('live/power', '{"p": 321}')
        values, errors = self.poll(connection, points, lambda v, e: v['Power'] is not None)
        self.assertEqual((values, errors), ({'Power': 321.0}, []))

        self.broker.publish('live/power', '{"p": 322}')
        values, _ = self.poll(connection, points, lambda v, e: v['Power'] == 322.0)
        self.assertEqual(values, {'Power': 322.0})

    def test_topic_added_later(self):
        self.broker.publish('a/1', '1', retain=True)
        self.broker.publish('a/2', '2', retain=True)
        connection = self.connection()
        self.assertEqual(driver.read('127.0.0.1', connection, {'One': {'topic': 'a/1'}}), ({'One': 1.0}, []))
        values, errors = driver.read('127.0.0.1', connection, {'One': {'topic': 'a/1'}, 'Two': {'topic': 'a/2'}})
        self.assertEqual((values, errors), ({'One': 1.0, 'Two': 2.0}, []))

    def test_max_age(self):
        self.broker.publish('old/value', '5', retain=True)
        connection = self.connection(max_age=0.5)
        points = {'Value': {'topic': 'old/value'}}
        self.assertEqual(driver.read('127.0.0.1', connection, points), ({'Value': 5.0}, []))
        time.sleep(1.2)
        values, errors = driver.read('127.0.0.1', connection, points)
        self.assertEqual(values, {'Value': None})
        self.assertEqual(len(errors), 1)
        self.assertRegex(errors[0], r'^Value \(old/value\): last message \d+ s old$')

    def test_resubscribes_after_reconnect(self):
        connection = self.connection(wait=0.5)
        points = {'Power': {'topic': 'r/power'}}
        driver.read('127.0.0.1', connection, points)
        self.broker.kick_all()
        deadline = time.monotonic() + 6
        while self.broker.connects < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertGreaterEqual(self.broker.connects, 2, 'listener did not reconnect')
        values, errors = self.poll(connection, points, lambda v, e: (self.broker.publish('r/power', '9') or
                                                                     v['Power'] is not None), timeout=4)
        self.assertEqual((values, errors), ({'Power': 9.0}, []))

    def test_bad_port(self):
        connection = self.connection(port=free_port(), wait=1)
        started = time.monotonic()
        values, errors = driver.read('127.0.0.1', connection, {'Power': {'topic': 'x/y'}})
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(values, {'Power': None})
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith('Power (x/y): no message'), errors[0])


class ImportTests(unittest.TestCase):
    def test_module_api(self):
        for name in ('read', 'discover', 'extract', 'shutdown_listeners'):
            self.assertTrue(callable(getattr(driver, name)))


if __name__ == '__main__':
    unittest.main()
