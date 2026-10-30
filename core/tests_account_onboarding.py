"""Account onboarding regressions use fictional users and isolated databases only."""
from base64 import b32encode
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import AuditEvent, RecoveryCode, User


SECURITY = {'DEMO_MODE': False, 'MFA_REQUIRED': True,
            'PASSWORD_HASHERS': ['django.contrib.auth.hashers.MD5PasswordHasher']}
PASSWORD = 'Fictional-Onboarding-Only!2026'


def account():
    return User.objects.create_user(username='onboarding-professional', email='onboarding@example.test',
                                    password=PASSWORD, is_staff=True)


@override_settings(**SECURITY)
class MFAOnboardingTests(TestCase):
    def setUp(self):
        self.user = account()
        self.client.force_login(self.user)

    def test_repeated_initial_setup_and_qr_keep_one_pending_key(self):
        first = self.client.get(reverse('mfa_setup'))
        second = self.client.get(reverse('mfa_setup'))
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        device = TOTPDevice.objects.get(user=self.user, name='primary', confirmed=False)
        self.assertEqual(first.context['secret'], b32encode(device.bin_key).decode())
        self.assertEqual(second.context['secret'], first.context['secret'])
        self.assertEqual(self.client.get(reverse('mfa_qr')).status_code, 200)
        self.assertFalse(RecoveryCode.objects.filter(user=self.user).exists())

    def test_existing_pending_duplicates_remain_intact_and_setup_uses_first_key(self):
        first = TOTPDevice.objects.create(user=self.user, name='primary', confirmed=False)
        second = TOTPDevice.objects.create(user=self.user, name='primary', confirmed=False)
        before = list(TOTPDevice.objects.filter(user=self.user).order_by('pk').values_list('pk', 'key', 'confirmed'))
        response = self.client.get(reverse('mfa_setup'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['secret'], b32encode(first.bin_key).decode())
        self.assertEqual(list(TOTPDevice.objects.filter(user=self.user).order_by('pk').values_list('pk', 'key', 'confirmed')), before)
        self.assertNotEqual(first.key, second.key)
        from segno import make
        self.assertEqual(self.client.get(reverse('mfa_qr'))['Content-Type'], 'image/svg+xml')
        with patch('segno.make', wraps=make) as qr:
            self.client.get(reverse('mfa_qr'))
        self.assertEqual(qr.call_args.args[0], first.config_url)

    def test_activation_with_pending_duplicates_confirms_only_chosen_key(self):
        first = TOTPDevice.objects.create(user=self.user, name='primary', confirmed=False)
        second = TOTPDevice.objects.create(user=self.user, name='primary', confirmed=False)
        previous_second_key = second.key
        with patch.object(TOTPDevice, 'verify_token', autospec=True, return_value=True) as verify:
            response = self.client.post(reverse('mfa_setup'), {'password': PASSWORD, 'token': '123456'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(verify.call_args.args[0].pk, first.pk)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertTrue(first.confirmed)
        self.assertFalse(second.confirmed)
        self.assertEqual(second.key, previous_second_key)
        self.assertEqual(TOTPDevice.objects.filter(user=self.user).count(), 2)
        self.assertEqual(self.client.session['otp_device_id'], first.persistent_id)
        self.assertEqual(RecoveryCode.objects.filter(user=self.user).count(), 8)
        self.assertEqual(AuditEvent.objects.filter(actor=self.user, action='security.mfa_enabled').count(), 1)
        self.assertEqual(len(response.context['codes']), 8)

    def test_confirmed_and_pending_keys_never_allow_provisioning_or_reveal_a_secret(self):
        confirmed = TOTPDevice.objects.create(user=self.user, name='primary', confirmed=True)
        pending = TOTPDevice.objects.create(user=self.user, name='primary', confirmed=False)
        before = list(TOTPDevice.objects.filter(user=self.user).order_by('pk').values_list('pk', 'key', 'confirmed'))
        self.assertNotIn('otp_device_id', self.client.session)
        qr_response = self.client.get(reverse('mfa_qr'))
        self.assertEqual(qr_response.status_code, 404)
        for response in [self.client.get(reverse('mfa_setup')),
                         self.client.post(reverse('mfa_setup'), {'password': PASSWORD, 'token': '123456'})]:
            self.assertRedirects(response, reverse('mfa_verify'), fetch_redirect_response=False)
            self.assertNotIn(b32encode(confirmed.bin_key).decode(), response.content.decode())
            self.assertNotIn(b32encode(pending.bin_key).decode(), response.content.decode())
        self.assertNotIn('otp_device_id', self.client.session)
        self.assertEqual(list(TOTPDevice.objects.filter(user=self.user).order_by('pk').values_list('pk', 'key', 'confirmed')), before)
        self.assertFalse(RecoveryCode.objects.filter(user=self.user).exists())
        self.assertFalse(AuditEvent.objects.filter(actor=self.user, action='security.mfa_enabled').exists())

    def test_existing_confirmed_devices_are_preserved_and_never_render_setup_secret(self):
        for _index in range(2):
            TOTPDevice.objects.create(user=self.user, name='primary', confirmed=True)
        before = list(TOTPDevice.objects.filter(user=self.user).order_by('pk').values_list('pk', 'key', 'confirmed'))
        self.assertRedirects(self.client.get(reverse('mfa_setup')), reverse('mfa_verify'), fetch_redirect_response=False)
        self.assertRedirects(self.client.post(reverse('mfa_setup'), {'password': PASSWORD, 'token': '123456'}), reverse('mfa_verify'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('mfa_qr')).status_code, 404)
        self.assertEqual(list(TOTPDevice.objects.filter(user=self.user).order_by('pk').values_list('pk', 'key', 'confirmed')), before)
        self.assertFalse(RecoveryCode.objects.filter(user=self.user).exists())


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL user row locks')
@override_settings(**SECURITY)
class ConcurrentMFAOnboardingTests(TransactionTestCase):
    def setUp(self):
        self.user = account()
        self.clients = [Client(), Client()]
        for client in self.clients:
            client.force_login(self.user)

    def test_simultaneous_first_setup_views_share_one_pending_key(self):
        started = Barrier(2)
        both_creating = Event()
        guard = Lock()
        creation_calls = 0
        original_save = TOTPDevice.save

        def observe_new_device(device, *args, **kwargs):
            nonlocal creation_calls
            if device.pk is None and device.user_id == self.user.pk and device.name == 'primary':
                with guard:
                    creation_calls += 1
                    if creation_calls == 2:
                        both_creating.set()
                # Widen the original check/create race without requiring a second creator.
                # With the user lock the second view waits and this bounded wait expires.
                both_creating.wait(0.75)
            return original_save(device, *args, **kwargs)

        def visit(client):
            close_old_connections()
            try:
                started.wait(10)
                response = client.get(reverse('mfa_setup'))
                import re
                secrets = re.findall(r'<code dir="ltr">([^<]+)</code>', response.content.decode())
                return response.status_code, secrets
            finally:
                connections.close_all()

        with patch.object(TOTPDevice, 'save', new=observe_new_device), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(visit, self.clients))
        self.assertEqual([status for status, _secrets in results], [200, 200])
        self.assertEqual(TOTPDevice.objects.filter(user=self.user, name='primary', confirmed=False).count(), 1)
        self.assertEqual(creation_calls, 1)
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(len(results[0][1]), 1)
        self.assertFalse(RecoveryCode.objects.filter(user=self.user).exists())
