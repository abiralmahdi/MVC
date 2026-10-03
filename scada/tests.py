from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import UserModel
from dynamic.models import Buildings, Site
from home.models import GlobalConfiguration
from scada.models import Motor


class ScadaSecurityTests(TestCase):
    def setUp(self):
        GlobalConfiguration.objects.update_or_create(pk=GlobalConfiguration.load().pk, defaults={'scada': True})
        self.site = Site.objects.create(name='S', latitude='0', longitude='0')
        self.building = Buildings.objects.create(name='Pump house', site=self.site)
        self.motor = Motor.objects.create(
            motorName='Pump 1', building=self.building, ip='192.0.2.10', dbNo=1, rack=0, slot=1, dataSize=8,
            motorOnOffset={'byte': 0, 'bit': 0}, motorOffOffset={'byte': 0, 'bit': 1},
            runFeedbackOffset={'byte': 0, 'bit': 2}, tripOffset={'byte': 0, 'bit': 3}, fields={},
        )

    def _user(self, role, site=None):
        user = User.objects.create_user(role.lower(), f'{role}@example.com', 'VeryStrong#Pass1')
        UserModel.objects.create(user=user, name=role, email=user.email, role=role, site=site or self.site)
        return user

    def test_anonymous_cannot_control_or_view(self):
        response = self.client.post('/scada/controlMotor/', {'motor_id': self.motor.id, 'action': 'start'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get('/scada/').status_code, 302)
        self.assertEqual(self.client.get(f'/scada/fetchMotorAndTankData/{self.motor.id}').status_code, 401)

    def test_control_requires_csrf_token(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self._user('Operator'))
        response = client.post('/scada/controlMotor/', {'motor_id': self.motor.id, 'action': 'start'})
        self.assertEqual(response.status_code, 403)

    def test_read_only_roles_cannot_control(self):
        self.client.force_login(self._user('Quality Manager'))
        response = self.client.post('/scada/controlMotor/', {'motor_id': self.motor.id, 'action': 'start'})
        self.assertEqual(response.status_code, 403)

    def test_other_site_motor_is_hidden(self):
        other = Site.objects.create(name='Other', latitude='0', longitude='0')
        self.client.force_login(self._user('Operator', site=other))
        response = self.client.post('/scada/controlMotor/', {'motor_id': self.motor.id, 'action': 'stop'})
        self.assertEqual(response.status_code, 404)

    def test_operator_command_writes_only_command_byte(self):
        self.client.force_login(self._user('Operator'))
        client = mock.MagicMock()
        client.get_connected.return_value = True
        client.read_area.side_effect = lambda area, db, start, size: bytearray(size)
        with mock.patch('snap7.client.Client', return_value=client):
            response = self.client.post('/scada/controlMotor/', {'motor_id': self.motor.id, 'action': 'start'})
        self.assertEqual(response.status_code, 200, response.content)
        written = [call.args for call in client.write_area.call_args_list]
        self.assertEqual(len(written), 1)
        _, db, start, data = written[0]
        self.assertEqual((db, start, len(data)), (1, 0, 1))
        self.assertEqual(data[0] & 0b11, 0b01)  # ON bit set, OFF bit cleared

    def test_unreachable_plc_returns_json_error(self):
        self.client.force_login(User.objects.create_superuser('root', 'r@example.com', 'VeryStrong#Pass1'))
        client = mock.MagicMock()
        client.connect.side_effect = RuntimeError('timeout')
        client.get_connected.return_value = False
        with mock.patch('snap7.client.Client', return_value=client):
            response = self.client.get('/scada/status')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Cannot connect', response.json()['motors'][str(self.motor.id)]['error'])
