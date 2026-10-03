import importlib
import json

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from connections import drivers, protocols
from dynamic.models import Areas, Buildings, LoadType, Measurements, Meters, Site

migration = importlib.import_module('dynamic.migrations.0030_meters_protocol_connection')


class ProtocolValidationTests(SimpleTestCase):
    def test_every_protocol_has_a_driver_module_and_catalogue_entry(self):
        keys = [p['key'] for p in protocols.catalogue()]
        self.assertEqual(keys, ['modbus', 'bacnet', 'knx', 'dali', 'mbus', 'mqtt', 'opcua'])
        self.assertEqual(set(drivers.MODULES), set(keys))
        json.dumps(protocols.catalogue())  # must be serialisable for the form

    def test_connection_defaults_and_ranges(self):
        host, conn, errors = protocols.clean_connection('bacnet', '192.0.2.5', {})
        self.assertEqual(errors, [])
        self.assertEqual(conn['port'], 47808)
        _, _, errors = protocols.clean_connection('modbus', '192.0.2.5', {'port': 70000})
        self.assertTrue(any('TCP port' in e for e in errors))
        _, _, errors = protocols.clean_connection('knx', '', {})
        self.assertTrue(any('required' in e for e in errors))

    def test_conditional_fields(self):
        # serial M-Bus needs no host but a serial port; TCP needs a host
        _, conn, errors = protocols.clean_connection('mbus', '', {'transport': 'serial', 'serial_port': 'COM3'})
        self.assertEqual(errors, [])
        self.assertNotIn('port', conn)
        _, _, errors = protocols.clean_connection('mbus', '', {'transport': 'tcp'})
        self.assertTrue(errors)
        _, _, errors = protocols.clean_connection('mbus', '192.0.2.9', {'address_mode': 'secondary'})
        self.assertTrue(any('Secondary address' in e for e in errors))
        _, _, errors = protocols.clean_connection('bacnet', '192.0.2.9', {'network': 5})
        self.assertTrue(any('together' in e for e in errors))

    def test_points_are_validated_per_protocol(self):
        mapping, errors = protocols.clean_mapping('knx', {
            'Room temperature': {'group_address': '3/1/10', 'dpt': '9.001'},
            'Bad': {'group_address': 'x/y', 'dpt': '9.001'},
        })
        self.assertEqual(mapping['Room temperature']['scale'], 1)
        self.assertEqual(len(errors), 1)
        mapping, errors = protocols.clean_mapping('mqtt', {'Power': {'topic': 'plant/+/power'}})
        self.assertTrue(errors)  # wildcards are not a single value
        mapping, errors = protocols.clean_mapping('dali', {'Lamp': {'address': 64, 'value': 'active_power'}})
        self.assertTrue(errors)
        mapping, errors = protocols.clean_mapping('bacnet', {'Supply air': {'object_type': 'analog-input', 'instance': '4'}})
        self.assertEqual(errors, [])
        self.assertEqual(mapping['Supply air'], {'object_type': 'analog-input', 'instance': 4, 'property': 'present-value', 'scale': 1})

    def test_legacy_shapes_are_accepted(self):
        mapping, errors = protocols.clean_mapping('modbus', {'V': 55, 'I': [3, 19, 'int16', 0.1]})
        self.assertEqual(errors, [])
        self.assertEqual(mapping['I'], {'fc': 3, 'address': 19, 'type': 'int16', 'scale': 0.1})
        mapping, errors = protocols.clean_mapping('opcua', {'T': 'ns=2;s=Room.Temp'})
        self.assertEqual(mapping['T']['node'], 'ns=2;s=Room.Temp')

    def test_runtime_options_reach_the_driver(self):
        from unittest import mock
        with mock.patch('connections.drivers.mqtt.read', return_value=({'P': 1}, [])) as read:
            drivers.read_points('mqtt', 'broker.example.com', {'_one_shot': True}, {'P': {'topic': 'a/b'}})
        self.assertTrue(read.call_args.args[1]['_one_shot'])

    def test_knx_routing_needs_no_host(self):
        _, _, errors = protocols.clean_connection('knx', '', {'connection_type': 'routing'})
        self.assertEqual(errors, [])

    def test_dispatcher_scales_and_reports_bad_configuration(self):
        values, errors = drivers.read_points('knx', '', {}, {'T': {'group_address': '1/1/1', 'dpt': '9.001'}})
        self.assertEqual(values, {'T': None})
        self.assertTrue(any('required' in e for e in errors))
        self.assertEqual(drivers.scale_value(1500, 0.001), 1.5)
        self.assertEqual(drivers.scale_value(True, 1), 1.0)


class MigrationConversionTests(SimpleTestCase):
    def test_host_split(self):
        self.assertEqual(migration._split_host('opcuaserver.com:48010#', 4862), ('opcuaserver.com', 48010, ''))
        self.assertEqual(migration._split_host('opcua.demo-this.com:51210/UA/SampleServer#', 4862),
                         ('opcua.demo-this.com', 51210, '/UA/SampleServer'))
        self.assertEqual(migration._split_host('192.168.0.70', 4862), ('192.168.0.70', 4862, ''))

    def test_modbus_points(self):
        self.assertEqual(migration._modbus_point(55), {'fc': 4, 'address': 55, 'type': 'float32', 'scale': 1.0})
        self.assertEqual(migration._modbus_point([3, 7, 'INT16']), {'fc': 3, 'address': 7, 'type': 'int16', 'scale': 1.0})
        self.assertEqual(migration._modbus_point({'fc': 9, 'address': 1}), {'fc': 9, 'address': 1})  # kept, reported later


class MeterFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('root', 'root@example.com', 'x-test-pass-1')
        self.client.force_login(self.user)
        site = Site.objects.create(name='S', latitude='23.8', longitude='90.4')
        self.area = Areas.objects.create(name='A', building=Buildings.objects.create(name='B', site=site))
        self.load = LoadType.objects.create(name='Lighting')

    def post_meter(self, url, protocol, host, connection, mapping, **extra):
        data = {
            'meter_name': extra.get('name', 'Lighting DB-1'), 'meterType': 'Electricity Meter', 'area_id': self.area.id,
            'load_id': self.load.id, 'protocol': protocol, 'meter_ip': host,
            'connection': json.dumps(connection), 'register_mapping': json.dumps(mapping),
        }
        return self.client.post(url, data)

    def test_add_meter_for_each_protocol(self):
        cases = {
            'bacnet': ('192.0.2.30', {'port': 47808}, {'Supply Air Temp': {'object_type': 'analog-input', 'instance': 1}}),
            'knx': ('192.0.2.31', {'connection_type': 'tunneling'}, {'Active Power': {'group_address': '1/2/3', 'dpt': '14.056'}}),
            'dali': ('192.0.2.32', {}, {'Active Power': {'address': 3, 'value': 'active_power'}}),
            'mbus': ('', {'transport': 'serial', 'serial_port': '/dev/ttyUSB0', 'primary_address': 7},
                     {'Energy': {'record': 0, 'scale': 0.001}}),
            'mqtt': ('broker.example.com', {'port': 8883, 'tls': True, 'password': 's3cret'},
                     {'Active Power': {'topic': 'plant/db1/power', 'json_path': 'ENERGY.Power'}}),
            'opcua': ('scada.example.com', {'port': 4840, 'path': '/UA/Server'}, {'Voltage L1N': {'node': 'ns=2;s=V1'}}),
            'modbus': ('192.0.2.33', {'unit_id': 4}, {'Voltage L1N': {'fc': 3, 'address': 100, 'type': 'float32'}}),
        }
        for protocol, (host, connection, mapping) in cases.items():
            response = self.post_meter('/settings/hierarchy/addMeter', protocol, host, connection, mapping, name=f'M {protocol}')
            self.assertEqual(response.status_code, 302, protocol)
            meter = Meters.objects.get(name=f'M {protocol}')
            self.assertEqual(meter.protocol, protocol)
            self.assertEqual(set(meter.registerMapping), set(mapping))
            self.assertTrue(Measurements.objects.filter(meter=meter).exists())
        self.assertEqual(Meters.objects.get(name='M mbus').connection['baudrate'], 2400)
        self.assertEqual(Meters.objects.get(name='M modbus').connection, {'port': 502, 'unit_id': 4, 'timeout': 3})

    def test_invalid_configuration_is_rejected(self):
        self.post_meter('/settings/hierarchy/addMeter', 'knx', '192.0.2.31', {}, {'P': {'group_address': 'nope', 'dpt': '9.001'}})
        self.assertFalse(Meters.objects.exists())
        self.post_meter('/settings/hierarchy/addMeter', 'zigbee', '192.0.2.31', {}, {})
        self.assertFalse(Meters.objects.exists())

    def test_edit_keeps_stored_password_when_left_empty(self):
        self.post_meter('/settings/hierarchy/addMeter', 'mqtt', 'broker.example.com', {'username': 'mvc', 'password': 's3cret'},
                        {'Power': {'topic': 'a/b'}})
        meter = Meters.objects.get()
        self.post_meter(f'/settings/hierarchy/editMeter/{meter.id}', 'mqtt', 'broker.example.com', {'username': 'mvc', 'password': ''},
                        {'Power': {'topic': 'a/c'}})
        meter.refresh_from_db()
        self.assertEqual(meter.connection['password'], 's3cret')
        self.assertEqual(meter.registerMapping['Power']['topic'], 'a/c')

    def test_hierarchy_page_renders_protocols_without_secrets(self):
        self.post_meter('/settings/hierarchy/addMeter', 'mqtt', 'broker.example.com', {'password': 'top-secret-value'},
                        {'Power': {'topic': 'a/b'}})
        response = self.client.get('/settings/hierarchy')
        self.assertContains(response, 'protocol-catalogue')
        self.assertContains(response, 'MQTT')
        self.assertNotContains(response, 'top-secret-value')
