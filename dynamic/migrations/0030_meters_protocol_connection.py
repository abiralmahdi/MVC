"""Give every meter an explicit field protocol and connection settings.

Before this migration a meter was either Modbus TCP (port 502, ``unit_id``) or, when ``isScada`` was
ticked, OPC UA on the fixed port 4862. Existing meters keep exactly that behaviour:

* Modbus meters -> protocol "modbus", connection {"port": 502, "unit_id": <unit_id>, "timeout": 2},
  register definitions normalised to {"fc", "address", "type", "scale"}.
* OPC UA meters -> protocol "opcua", connection {"port": 4862, "path": "", "timeout": 3}, node ids
  wrapped as {"node", "scale"}. Hosts entered as "host:port/path#" (the old workaround for other
  ports) are split into host, port and path.
"""
import re

from django.db import migrations, models

DATA_TYPES = {'float32', 'float32_swapped', 'int16', 'uint16', 'int32', 'uint32', 'float64'}
NODE_ID = re.compile(r'^(ns=\d+;)?[isgb]=.+$')


def _modbus_point(definition):
    fc, address, data_type, scale = 4, None, 'float32', 1.0
    if isinstance(definition, bool):
        return definition
    if isinstance(definition, (int, float)) or (isinstance(definition, str) and definition.strip().isdigit()):
        address = int(definition)
    elif isinstance(definition, (list, tuple)) and len(definition) >= 2:
        fc, address = int(definition[0]), int(definition[1])
        if len(definition) > 2 and definition[2]:
            data_type = str(definition[2]).lower()
        if len(definition) > 3 and definition[3] not in (None, ''):
            scale = float(definition[3])
    elif isinstance(definition, dict) and 'address' in definition:
        address = int(definition['address'])
        fc = int(definition.get('fc') or definition.get('function_code') or 4)
        data_type = str(definition.get('type') or 'float32').lower()
        if definition.get('scale') not in (None, ''):
            scale = float(definition['scale'])
    else:
        return definition  # unknown shape: keep it, "Test connection" will report it
    if fc not in (3, 4) or data_type not in DATA_TYPES or not 0 <= address <= 65535:
        return definition
    return {'fc': fc, 'address': address, 'type': data_type, 'scale': scale}


def _split_host(raw, default_port):
    """'host', 'host:port', 'host:port#', 'host:port/path#' -> (host, port, path)."""
    value = (raw or '').strip().rstrip('#').strip()
    match = re.match(r'^(?P<host>[^:/\s]+)(?::(?P<port>\d{1,5}))?(?P<path>/[^\s#]*)?$', value)
    if not match:
        return value, default_port, ''
    return match['host'], int(match['port'] or default_port), match['path'] or ''


def forwards(apps, schema_editor):
    Meters = apps.get_model('dynamic', 'Meters')
    for meter in Meters.objects.all():
        mapping = meter.registerMapping if isinstance(meter.registerMapping, dict) else {}
        if meter.isScada:
            host, port, path = _split_host(meter.ip, 4862)
            meter.protocol = 'opcua'
            meter.ip = host
            meter.connection = {'port': port, 'path': path, 'username': '', 'password': '', 'timeout': 3.0}
            meter.registerMapping = {
                name: ({'node': d.strip(), 'scale': 1.0} if isinstance(d, str) and NODE_ID.match(d.strip()) else d)
                for name, d in mapping.items()
            }
        else:
            unit_id = meter.unit_id if meter.unit_id is not None and 0 <= meter.unit_id <= 255 else 1
            meter.protocol = 'modbus'
            meter.connection = {'port': 502, 'unit_id': unit_id, 'timeout': 2.0}
            meter.registerMapping = {name: _modbus_point(d) for name, d in mapping.items()}
        meter.save(update_fields=['protocol', 'ip', 'connection', 'registerMapping'])


def backwards(apps, schema_editor):
    Meters = apps.get_model('dynamic', 'Meters')
    for meter in Meters.objects.all():
        conn = meter.connection or {}
        meter.isScada = meter.protocol == 'opcua'
        meter.unit_id = conn.get('unit_id', 1)
        if meter.protocol == 'opcua':
            if conn.get('port', 4862) != 4862 or conn.get('path'):
                meter.ip = f"{meter.ip}:{conn.get('port')}{conn.get('path') or ''}#"
            meter.registerMapping = {
                name: (d['node'] if isinstance(d, dict) and 'node' in d else d)
                for name, d in (meter.registerMapping or {}).items()
            }
        meter.save(update_fields=['isScada', 'unit_id', 'ip', 'registerMapping'])


class Migration(migrations.Migration):

    dependencies = [
        ('dynamic', '0029_alter_meters_registermapping'),
    ]

    operations = [
        migrations.AddField(
            model_name='meters',
            name='protocol',
            field=models.CharField(choices=[('modbus', 'Modbus TCP'), ('bacnet', 'BACnet/IP'), ('knx', 'KNX'), ('dali', 'DALI / DALI-2'), ('mbus', 'M-Bus'), ('mqtt', 'MQTT'), ('opcua', 'OPC UA')], default='modbus', max_length=20),
        ),
        migrations.AddField(
            model_name='meters',
            name='connection',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='meters',
            name='isScada',
        ),
        migrations.RemoveField(
            model_name='meters',
            name='unit_id',
        ),
    ]
