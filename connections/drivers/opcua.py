"""OPC UA driver (anonymous or user name / password, security mode None)."""


def endpoint(host, connection):
    host = f'[{host}]' if ':' in host and not host.startswith('[') else host
    return f"opc.tcp://{host}:{connection.get('port', 4840)}{connection.get('path') or ''}"


def read(host, connection, points):
    values = {name: None for name in points}
    try:
        from opcua import Client
    except ImportError:
        return values, ['the "opcua" package is not installed']

    url = endpoint(host, connection)
    client = Client(url, timeout=connection.get('timeout', 3) + 2)
    if connection.get('username'):
        client.set_user(connection['username'])
        client.set_password(connection.get('password') or '')
    try:
        client.connect()
    except Exception as exc:
        return values, [f'OPC UA connection to {url} failed: {exc}']
    errors = []
    try:
        for name, point in points.items():
            try:
                value = client.get_node(point['node']).get_value()
            except Exception as exc:
                errors.append(f"{name} ({point['node']}): {exc}")
                continue
            if isinstance(value, (int, float, bool)):
                values[name] = value
            else:
                errors.append(f"{name} ({point['node']}): value {value!r} is not numeric")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
    return values, errors
