from django.contrib.auth.models import User
from django.test import TestCase

from accounts.models import LoginHistory
from home.models import GlobalConfiguration


class GlobalConfigurationTests(TestCase):
    def test_missing_configuration_row_does_not_loop(self):
        GlobalConfiguration.objects.all().delete()
        response = self.client.get('/', follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertLess(len(response.redirect_chain), 3)
        self.assertEqual(GlobalConfiguration.objects.count(), 1)

    def test_revoked_subscription_page(self):
        config = GlobalConfiguration.load()
        config.subscribed = False
        config.save()
        self.client.force_login(User.objects.create_superuser('root', 'r@example.com', 'VeryStrong#Pass1'))
        response = self.client.get('/dashboard/', follow=True)
        self.assertContains(response, 'subscription is over')


class LoginTests(TestCase):
    def test_login_records_history_and_shows_errors(self):
        User.objects.create_user('ops@example.com', 'ops@example.com', 'VeryStrong#Pass1')
        response = self.client.post('/accounts/login', {'username': 'ops@example.com', 'password': 'wrong'})
        self.assertContains(response, 'Invalid username or password')
        response = self.client.post('/accounts/login', {'username': 'ops@example.com', 'password': 'VeryStrong#Pass1'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LoginHistory.objects.count(), 1)

    def test_login_ignores_external_next(self):
        User.objects.create_user('a', 'a@example.com', 'VeryStrong#Pass1')
        response = self.client.post('/accounts/login?next=https://evil.example.com/', {'username': 'a', 'password': 'VeryStrong#Pass1', 'next': 'https://evil.example.com/'})
        self.assertEqual(response['Location'], '/')


class FeatureGateTests(TestCase):
    def setUp(self):
        self.config = GlobalConfiguration.load()
        self.root = User.objects.create_superuser('root', 'r@example.com', 'VeryStrong#Pass1')
        self.client.force_login(self.root)

    def disable(self, **flags):
        for flag, value in flags.items():
            setattr(self.config, flag, value)
        self.config.save()

    def test_disabled_module_urls_are_blocked_even_when_typed(self):
        self.disable(dashboard=False, alarm=False, report=False, billing=False, scada=False, siteLocations=False)
        for url in ('/dashboard/', '/dashboard/1', '/dashboard/1/fetchLatestReadings/1/', '/alarms/allAlarms',
                    '/reports/', '/reports/viewSavedReports', '/billing/', '/billing/3', '/scada/', '/scada/status',
                    '/location/', '/location/alarmStatus'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, url)
            self.assertContains(response, 'module is disabled', status_code=403)

    def test_json_requests_get_json_error(self):
        self.disable(scada=False)
        response = self.client.get('/scada/status', HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'error': 'The SCADA module is disabled.'})

    def test_posts_to_disabled_module_are_blocked(self):
        self.disable(alarm=False)
        response = self.client.post('/alarms/ackAllAlarms/')
        self.assertEqual(response.status_code, 403)

    def test_enabled_modules_and_settings_still_work(self):
        self.disable(billing=False)
        self.assertEqual(self.client.get('/reports/').status_code, 200)
        self.assertEqual(self.client.get('/settings/configurations').status_code, 200)
        self.assertNotContains(self.client.get('/reports/'), 'href="/billing"')

    def test_start_page_skips_disabled_modules(self):
        self.disable(siteLocations=False, dashboard=False)
        self.assertRedirects(self.client.get('/'), '/scada/' if self.config.scada else '/alarms/allAlarms',
                             fetch_redirect_response=False)
        self.disable(scada=False, alarm=False, report=False, billing=False)
        self.assertContains(self.client.get('/'), 'No modules are enabled')

    def test_machine_learning_module_can_be_toggled(self):
        self.assertEqual(self.client.get('/ml/').status_code, 200)  # on by default, superuser
        self.disable(machineLearning=False)
        response = self.client.get('/ml/')
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Machine Learning module is disabled', status_code=403)
        self.assertEqual(self.client.get('/ml/status/1', HTTP_ACCEPT='application/json').status_code, 403)
        self.assertNotContains(self.client.get('/settings/configurations'), 'href="/ml/"')

    def test_ml_is_not_a_landing_target(self):
        self.disable(dashboard=False, siteLocations=False, scada=False, alarm=False, report=False, billing=False)
        self.assertContains(self.client.get('/'), 'No modules are enabled')

    def test_anonymous_user_is_sent_to_login(self):
        self.disable(dashboard=False)
        self.client.logout()
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login', response['Location'])
