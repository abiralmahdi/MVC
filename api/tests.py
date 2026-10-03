import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts.models import UserModel
from home.models import GlobalConfiguration

KEY = 'test-master-key-123'


@override_settings(MVC_MASTER_API_KEY=KEY)
class MasterApiSecurityTests(TestCase):
    def test_add_user_requires_api_key(self):
        payload = {'username': 'intruder@example.com', 'password': 'VeryStrong#Pass1', 'superuser': True}
        for headers in ({}, {'HTTP_X_API_KEY': 'wrong'}):
            response = self.client.post('/api/addUser', payload, content_type='application/json', **headers)
            self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='intruder@example.com').exists())

    @override_settings(MVC_MASTER_API_KEY='')
    def test_api_is_closed_when_no_key_configured(self):
        response = self.client.get('/api/getAllUsers', HTTP_X_API_KEY='')
        self.assertEqual(response.status_code, 403)

    def test_add_user_with_key_hashes_password(self):
        payload = {'username': 'ops@example.com', 'password': 'VeryStrong#Pass1', 'role': 'Operator', 'superuser': False}
        response = self.client.post('/api/addUser', payload, content_type='application/json', HTTP_X_API_KEY=KEY)
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username='ops@example.com')
        self.assertTrue(user.check_password('VeryStrong#Pass1'))
        self.assertEqual(user.userModel.first().password, 'VeryStrong#Pass1')
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.userModel.first().role, 'Operator')

    def test_user_list_never_contains_passwords(self):
        user = User.objects.create_user('a@example.com', 'a@example.com', 'VeryStrong#Pass1')
        UserModel.objects.create(user=user, name='A', email='a@example.com', role='Operator')
        response = self.client.get('/api/getAllUsers', HTTP_X_API_KEY=KEY)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('password', json.dumps(response.json()))
        self.assertNotIn('VeryStrong', response.content.decode())

    def test_subscription_update_requires_key(self):
        GlobalConfiguration.load()
        response = self.client.post('/api/global-config/update', {'subscribed': False}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertTrue(GlobalConfiguration.load().subscribed)

        response = self.client.post('/api/global-config/update', {'subscribed': False}, content_type='application/json', HTTP_X_API_KEY=KEY)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GlobalConfiguration.load().subscribed)
