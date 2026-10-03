from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import UserModel
from alarms.models import Alarms, AlarmsRange
from dashboard.models import store_reading
from dynamic.models import Areas, Buildings, Measurements, Meters, Site
from home import notifications
from ml.models import DeviceHealth


class NotificationRecipientTests(TestCase):
    def setUp(self):
        self.site_a = Site.objects.create(name='A', latitude='1', longitude='1')
        self.site_b = Site.objects.create(name='B', latitude='2', longitude='2')

        def make(username, role, site, superuser=False):
            u = (User.objects.create_superuser if superuser else User.objects.create_user)(username, username, 'x-Pass-123')
            UserModel.objects.create(user=u, name=username, email=username + '@example.com', role=role, site=site)

        make('root', 'Administrator', None, superuser=True)   # superuser
        make('boss', 'Administrator', self.site_b)            # administrator (all sites)
        make('opA', 'Operator', self.site_a)                  # site A user
        make('opB', 'Operator', self.site_b)                  # site B user (not relevant to A)

    def test_recipients_are_superusers_admins_and_site_users(self):
        emails = {e for e, _ in notifications.recipients_for_site(self.site_a)}
        self.assertEqual(emails, {'root@example.com', 'boss@example.com', 'opA@example.com'})
        self.assertNotIn('opB@example.com', emails)

    def test_recipients_without_site_are_superusers_and_admins(self):
        emails = {e for e, _ in notifications.recipients_for_site(None)}
        self.assertEqual(emails, {'root@example.com', 'boss@example.com'})


class NotificationTriggerTests(TestCase):
    def setUp(self):
        site = Site.objects.create(name='S', latitude='1', longitude='1')
        area = Areas.objects.create(name='Ar', building=Buildings.objects.create(name='B', site=site))
        self.meter = Meters.objects.create(name='M1', area=area, meterType='Electricity Meter', protocol='modbus')
        self.measurement = Measurements.objects.create(name='Voltage L1N', meter=self.meter)
        AlarmsRange.objects.create(meter=self.meter, measurement=self.measurement, minValue=200, maxValue=250)
        u = User.objects.create_superuser('root', 'root@example.com', 'x-Pass-123')
        UserModel.objects.create(user=u, name='root', email='root@example.com', role='Administrator', site=site)
        self.motor_health = DeviceHealth(meter=self.meter)

    def test_store_reading_emails_new_alarm(self):
        with mock.patch('home.notifications._send') as send:
            store_reading(self.meter, {'Voltage L1N': 260})   # above max -> new alarm
        self.assertTrue(Alarms.objects.filter(meter=self.meter).exists())
        self.assertEqual(send.call_count, 1)
        recipients = send.call_args.args[2]
        self.assertIn('root@example.com', [e for e, _ in recipients])

    def test_normal_reading_sends_nothing(self):
        with mock.patch('home.notifications._send') as send:
            store_reading(self.meter, {'Voltage L1N': 230})
        send.assert_not_called()

    def test_health_notifies_only_on_alert_and_escalation(self):
        h = DeviceHealth.objects.create(meter=self.meter, status=DeviceHealth.OK, risk='high',
                                        health_score=20, failure_probability=0.6, days_to_maintenance=2)
        with mock.patch('home.notifications._send') as send:
            notifications.notify_health(h, previous_risk='low')
            self.assertEqual(send.call_count, 1)
        h.risk = 'low'
        with mock.patch('home.notifications._send') as send:
            notifications.notify_health(h, previous_risk='high')
            send.assert_not_called()   # dropping to low does not notify
