"""MQTT driver (MQTT 3.1.1, QoS 0 subscriptions, optional TLS with the system CA store).

MQTT is push based, so ``read`` works in one of two modes:

* **Listener cache** (default, meant for the long-running poller): one background ``BrokerListener``
  per broker/credentials keeps a subscription to every topic it has been asked for and remembers the
  last payload of each. ``read`` only looks the values up; it waits (up to ``wait`` seconds) for topics
  that were subscribed just now, so retained messages can arrive. Values older than ``max_age`` seconds
  count as missing.
* **One-shot** (``connection['_one_shot']`` truthy, used by "Test connection"): connect, subscribe,
  wait up to ``wait`` seconds for every topic, disconnect. No threads are left behind.

``discover`` lists the topics seen on the broker during ``wait`` seconds (one-shot).
paho-mqtt is imported lazily so the module imports without it.
"""
import atexit
import json
import logging
import math
import threading
import time
import uuid

logger = logging.getLogger('connections')

DEFAULT_PORT = 1883
DEFAULT_WAIT = 5.0
DEFAULT_MAX_AGE = 900
DISCOVER_LIMIT = 200
PAYLOAD_PREVIEW = 200
LISTENER_IDLE_SECONDS = 6 * 3600      # listeners nobody read from for this long are stopped
TRUE_WORDS = ('true', 'on')
FALSE_WORDS = ('false', 'off')


# ------------------------------------------------------------------ payload parsing
def _to_number(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError('empty value')
        if text.lower() in TRUE_WORDS:
            return 1.0
        if text.lower() in FALSE_WORDS:
            return 0.0
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f'value {text[:40]!r} is not numeric') from None
    elif value is None:
        raise ValueError('value is null')
    else:
        raise ValueError(f'value of type {type(value).__name__} is not numeric')
    if not math.isfinite(number):
        raise ValueError(f'value {number} is not a finite number')
    return number


def extract(payload, json_path=''):
    """Return the numeric value in ``payload`` (bytes or str) at the dotted ``json_path``.

    An empty path means the payload itself is the value. Numeric path segments index lists
    (``values.0.v``). Booleans and true/false/on/off become 1.0/0.0. Raises ValueError.
    """
    if isinstance(payload, (bytes, bytearray)):
        try:
            text = bytes(payload).decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError('payload is not UTF-8 text') from None
    else:
        text = '' if payload is None else str(payload)
    path = (json_path or '').strip()
    if path.startswith('$'):
        path = path[1:].lstrip('.')
    if not path:
        if not text.strip():
            raise ValueError('empty payload')
        return _to_number(text)
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError(f'payload is not valid JSON (JSON path "{path}" given)') from None
    walked = []
    for segment in path.split('.'):
        where = '.'.join(walked) or 'payload'
        if isinstance(data, dict):
            if segment not in data:
                raise ValueError(f'key "{segment}" not found in {where}')
            data = data[segment]
        elif isinstance(data, list):
            if not segment.isdigit():
                raise ValueError(f'{where} is a list; "{segment}" is not an index')
            index = int(segment)
            if index >= len(data):
                raise ValueError(f'index {index} out of range in {where} (length {len(data)})')
            data = data[index]
        else:
            raise ValueError(f'cannot look up "{segment}": {where} is not an object or list')
        walked.append(segment)
    try:
        return _to_number(data)
    except ValueError as exc:
        raise ValueError(f'{path}: {exc}') from None


# ------------------------------------------------------------------ helpers
def _settings(connection):
    connection = connection or {}
    wait = connection.get('wait')
    max_age = connection.get('max_age')
    return {
        'port': int(connection.get('port') or DEFAULT_PORT),
        'tls': bool(connection.get('tls')),
        'username': connection.get('username') or '',
        'password': connection.get('password') or '',
        'client_id': (connection.get('client_id') or '').strip(),
        'wait': float(DEFAULT_WAIT if wait is None else wait),
        'max_age': float(DEFAULT_MAX_AGE if max_age is None else max_age),
    }


def _make_client(host, settings, client_id):
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
    if settings['username']:
        client.username_pw_set(settings['username'], settings['password'] or None)
    if settings['tls']:
        client.tls_set()
    client.connect_timeout = max(0.5, min(settings['wait'], 30.0))
    return client


def _client_id(settings, suffix=''):
    return settings['client_id'] or f'marksvision-{suffix}{uuid.uuid4().hex[:12]}'


def _broker(host, settings):
    return f"{host}:{settings['port']}"


def _format_seconds(seconds):
    return f'{seconds:g}'


def _close_client(client):
    """Release sockets a stopped paho client may still hold."""
    for name in ('_sock_close', '_reset_sockets'):
        method = getattr(client, name, None)
        if method:
            try:
                method()
            except Exception:
                pass


def _bad_topic(topic):
    if not topic or not isinstance(topic, str):
        return 'no topic'
    if '#' in topic or '+' in topic:
        return 'wildcard topics are not supported for a data point'
    return None


def _point_values(points, lookup, errors):
    """Fill values from ``lookup(topic) -> (payload | None, error | None)``."""
    values = {}
    for name, point in points.items():
        values[name] = None
        topic = (point or {}).get('topic')
        problem = _bad_topic(topic)
        if problem:
            errors.append(f'{name} ({topic}): {problem}')
            continue
        payload, problem = lookup(topic)
        if problem:
            errors.append(f'{name} ({topic}): {problem}')
            continue
        try:
            values[name] = extract(payload, point.get('json_path') or '')
        except ValueError as exc:
            errors.append(f'{name} ({topic}): {exc}')
    return values


def _topics(points):
    return sorted({p.get('topic') for p in points.values() if isinstance(p, dict) and not _bad_topic(p.get('topic'))})


# ------------------------------------------------------------------ listener cache
class BrokerListener:
    """Background subscription to one broker that caches the last message of every requested topic."""

    def __init__(self, host, settings):
        self.host = host
        self.settings = dict(settings)
        self.broker = _broker(host, settings)
        self._cond = threading.Condition()
        self._requested = {}        # topic -> monotonic time first requested
        self._subscribed = {}       # topic -> monotonic time subscribed on the current connection
        self._messages = {}         # topic -> (payload bytes, monotonic receive time, retained)
        self._connected = False
        self._last_error = None
        self._stopped = False
        self.last_used = time.monotonic()

        self.client = _make_client(host, settings, _client_id(settings))
        self.client.reconnect_delay_set(1, 30)
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.connect_async(host, settings['port'], keepalive=60)
        self.client.loop_start()

    # paho callbacks (network thread)
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        with self._cond:
            if reason_code.is_failure:
                self._connected = False
                self._last_error = f'broker refused the connection: {reason_code}'
                self._cond.notify_all()
                return
            self._connected = True
            self._last_error = None
            topics = list(self._requested)
            now = time.monotonic()
            self._subscribed = {topic: now for topic in topics}
            self._cond.notify_all()
        if topics:
            client.subscribe([(topic, 0) for topic in topics])

    def _on_connect_fail(self, client, userdata):
        with self._cond:
            self._connected = False
            self._last_error = f'cannot connect to broker {self.broker}'
            self._cond.notify_all()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        with self._cond:
            self._connected = False
            self._subscribed = {}
            if not self._stopped:
                self._last_error = f'disconnected from broker {self.broker}: {reason_code}'
            self._cond.notify_all()

    def _on_message(self, client, userdata, message):
        with self._cond:
            if message.topic in self._requested:
                self._messages[message.topic] = (bytes(message.payload), time.monotonic(), bool(message.retain))
                self._cond.notify_all()

    # API
    def add_topics(self, topics):
        with self._cond:
            self.last_used = time.monotonic()
            new = [t for t in topics if t not in self._requested]
            now = time.monotonic()
            for topic in new:
                self._requested[topic] = now
            connected = self._connected
            if connected:
                for topic in new:
                    self._subscribed[topic] = now
        if new and connected:
            self.client.subscribe([(topic, 0) for topic in new])
        return new

    def wait_for(self, topics, wait):
        """Wait until every topic has a message, or it was subscribed more than ``wait`` seconds ago."""
        end = time.monotonic() + wait
        with self._cond:
            while not self._stopped:
                now = time.monotonic()
                missing = [t for t in topics if t not in self._messages]
                if not missing:
                    return
                # topics subscribed (or requested while disconnected) long ago do not block the poller
                deadline = max((self._subscribed.get(t) or self._requested.get(t, now)) + wait for t in missing)
                deadline = min(deadline, end)
                if now >= deadline:
                    return
                self._cond.wait(deadline - now)

    def lookup(self, topic, wait, max_age):
        with self._cond:
            entry = self._messages.get(topic)
            if entry is None:
                if not self._connected:
                    reason = self._last_error or f'not connected to broker {self.broker}'
                    return None, f'no message ({reason})'
                return None, f'no message within {_format_seconds(wait)} s'
            payload, received, _retained = entry
        age = time.monotonic() - received
        if age > max_age:
            return None, f'last message {int(age)} s old'
        return payload, None

    @property
    def connected(self):
        with self._cond:
            return self._connected

    def stop(self):
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
        try:
            self.client.disconnect()
        except Exception:
            pass
        try:
            self.client.loop_stop()
        except Exception:
            pass
        _close_client(self.client)


_listeners = {}
_listeners_lock = threading.Lock()


def _listener_key(host, settings):
    return (host, settings['port'], settings['tls'], settings['username'], settings['client_id'])


def get_listener(host, connection):
    """Return the running listener for this broker, starting (or restarting) it when needed."""
    settings = _settings(connection)
    key = _listener_key(host, settings)
    stale = []
    with _listeners_lock:
        now = time.monotonic()
        for other_key, other in list(_listeners.items()):
            if other_key != key and now - other.last_used > LISTENER_IDLE_SECONDS:
                stale.append(_listeners.pop(other_key))
        listener = _listeners.get(key)
        if listener is not None and (listener.settings['password'] != settings['password']
                                     or listener.settings['wait'] != settings['wait']):
            stale.append(_listeners.pop(key))       # credentials or timeouts changed: reconnect
            listener = None
        if listener is None:
            listener = BrokerListener(host, settings)
            _listeners[key] = listener
    for old in stale:
        old.stop()
    return listener


def shutdown_listeners():
    """Stop every background listener (tests, process exit)."""
    with _listeners_lock:
        listeners = list(_listeners.values())
        _listeners.clear()
    for listener in listeners:
        listener.stop()


atexit.register(shutdown_listeners)


# ------------------------------------------------------------------ one-shot session
class _OneShot:
    """Connect, subscribe to some topic filters and pump the network loop in the calling thread."""

    def __init__(self, host, settings, filters):
        self.host = host
        self.settings = settings
        self.filters = list(filters)
        self.broker = _broker(host, settings)
        self.messages = {}          # topic -> (payload, retained), last message wins
        self.order = []             # topics in order of first arrival
        self.connack = None         # reason code
        self.subscribed = False
        self.client = None

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.connack = reason_code
        if not reason_code.is_failure and self.filters:
            client.subscribe([(topic, 0) for topic in self.filters])

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties=None):
        self.subscribed = True

    def _on_message(self, client, userdata, message):
        if message.topic not in self.messages:
            self.order.append(message.topic)
        self.messages[message.topic] = (bytes(message.payload), bool(message.retain))

    def run(self, done):
        """Collect messages until ``done(self)`` is true or ``wait`` expires. Raises ConnectionError."""
        wait = self.settings['wait']
        self.client = client = _make_client(self.host, self.settings, _client_id(self.settings, 'test-'))
        client.on_connect = self._on_connect
        client.on_subscribe = self._on_subscribe
        client.on_message = self._on_message
        started = time.monotonic()
        try:
            try:
                client.connect(self.host, self.settings['port'], keepalive=max(30, int(wait) + 10))
            except Exception as exc:
                raise ConnectionError(f'MQTT connection to {self.broker} failed: {exc}') from None
            end = started + wait
            while True:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    break
                rc = client.loop(timeout=min(0.1, remaining))
                if self.connack is not None and self.connack.is_failure:
                    raise ConnectionError(f'MQTT broker {self.broker} refused the connection: {self.connack}')
                if rc != 0 and self.connack is None:
                    raise ConnectionError(f'MQTT connection to {self.broker} lost before CONNACK ({rc})')
                if self.connack is not None and done(self):
                    break
            if self.connack is None:
                raise ConnectionError(f'MQTT broker {self.broker} did not answer within {_format_seconds(wait)} s')
        finally:
            try:
                client.disconnect()
                for _ in range(3):
                    if client.socket() is None:
                        break
                    client.loop(timeout=0.05)
            except Exception:
                pass
            _close_client(client)


def _read_one_shot(host, settings, points):
    topics = _topics(points)
    session = _OneShot(host, settings, topics)
    errors = []
    try:
        session.run(lambda s: all(t in s.messages for t in topics))
    except ConnectionError as exc:
        return {name: None for name in points}, [str(exc)]

    def lookup(topic):
        if topic not in session.messages:
            return None, f"no message within {_format_seconds(settings['wait'])} s"
        return session.messages[topic][0], None

    values = _point_values(points, lookup, errors)
    return values, errors


def _read_listener(host, settings, connection, points):
    try:
        listener = get_listener(host, connection)
    except Exception as exc:
        return {name: None for name in points}, [f'MQTT listener for {_broker(host, settings)} failed: {exc}']
    topics = _topics(points)
    listener.add_topics(topics)
    listener.wait_for(topics, settings['wait'])
    errors = []
    values = _point_values(points, lambda t: listener.lookup(t, settings['wait'], settings['max_age']), errors)
    return values, errors


# ------------------------------------------------------------------ driver API
def read(host, connection, points):
    values = {name: None for name in points}
    try:
        import paho.mqtt.client  # noqa: F401
    except ImportError:
        return values, ['the "paho-mqtt" package is not installed']
    try:
        settings = _settings(connection)
    except (TypeError, ValueError) as exc:
        return values, [f'invalid MQTT connection settings: {exc}']
    try:
        if (connection or {}).get('_one_shot'):
            return _read_one_shot(host, settings, points)
        return _read_listener(host, settings, connection, points)
    except Exception as exc:     # never let a broker problem escape into the poller
        logger.exception('MQTT read from %s failed', host)
        return values, [f'MQTT read from {_broker(host, settings)} failed: {exc}']


def discover(host, connection):
    """List topics published on the broker within ``wait`` seconds (retained ones arrive at once).

    Returns up to 200 ``{'topic', 'payload', 'retained'}`` entries sorted by topic.
    Raises ConnectionError when the broker cannot be reached.
    """
    try:
        import paho.mqtt.client  # noqa: F401
    except ImportError:
        raise ConnectionError('the "paho-mqtt" package is not installed') from None
    settings = _settings(connection)
    topic_filter = (connection or {}).get('_discover_topic') or '#'
    session = _OneShot(host, settings, [topic_filter])
    session.run(lambda s: len(s.messages) >= DISCOVER_LIMIT)
    entries = []
    for topic in sorted(session.order[:DISCOVER_LIMIT]):
        payload, retained = session.messages[topic]
        entries.append({
            'topic': topic,
            'payload': payload.decode('utf-8', errors='replace')[:PAYLOAD_PREVIEW],
            'retained': retained,
        })
    return entries
