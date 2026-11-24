"""Own-password rotation on fictional users; no recovery authority or email."""
import hashlib
import html
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordChangeView
from django.db import connection, connections
from django.db.models.query import QuerySet
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import resolve, reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django_otp.plugins.otp_totp.models import TOTPDevice

from catalog.models import EditorialGrant, Variety
from core.auth_throttle import LIMITS, attempt_identity, bucket_specs
from core.models import AuditEvent, Membership, Organization, RateWindow, RecoveryCode, User


OLD_PASSWORD = 'Fictional-Original-Password-For-Test-2026!'
NEW_PASSWORD = 'Different-Rotated-Test-Only-2026!'
OTHER_PASSWORD = 'Other-Test-Original-Password-2026!'
SECURITY = {
    'DEMO_MODE': False, 'DEBUG': False, 'MFA_REQUIRED': True,
    'EMAIL_BACKEND': 'core.email_backends.DisabledEmailBackend',
    'PASSWORD_HASHERS': ['django.contrib.auth.hashers.MD5PasswordHasher'],
}


def install_fixture(target):
    target.user = User.objects.create_user('password-clinician', 'password-clinician@example.test', password=OLD_PASSWORD)
    target.other = User.objects.create_user('password-family', 'password-family@example.test', password=OTHER_PASSWORD)
    target.organization = Organization.objects.create(name='Password rotation fixture · fictif')
    Membership.objects.create(organization=target.organization, user=target.user, role='clinician')
    target.variety = Variety.objects.create(code='password-fr-fixture', language='fr', label='Fictional French scope')
    EditorialGrant.objects.create(user=target.user, variety=target.variety, edit=True)
    target.device = TOTPDevice.objects.create(user=target.user, name='fictional-existing', confirmed=True)
    RecoveryCode.objects.create(user=target.user, digest=hashlib.sha256(b'fictional-existing-backup').hexdigest())


class PasswordChangeHelpers:
    def verified_client(self, user=None, *, enforce_csrf=True):
        user = user or self.user
        user.refresh_from_db()
        client = Client(enforce_csrf_checks=enforce_csrf)
        client.force_login(user)
        if user.pk == self.user.pk:
            session = client.session
            session['otp_device_id'] = self.device.persistent_id
            session.save()
        return client

    def payload(self, client, path, *, old=OLD_PASSWORD, new=NEW_PASSWORD, **changes):
        page = client.get(path)
        self.assertEqual(page.status_code, 200)
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())
        self.assertIsNotNone(match)
        return {'csrfmiddlewaretoken': html.unescape(match.group(1)), 'old_password': old,
                'new_password1': new, 'new_password2': new, **changes}

    def security_snapshot(self):
        return {
            'memberships': list(Membership.objects.order_by('pk').values()),
            'grants': list(EditorialGrant.objects.order_by('pk').values()),
            'permissions': list(User.user_permissions.through.objects.order_by('pk').values()),
            'groups': list(User.groups.through.objects.order_by('pk').values()),
            'devices': list(TOTPDevice.objects.order_by('pk').values()),
            'recovery': list(RecoveryCode.objects.order_by('pk').values()),
            'user_flags': list(User.objects.order_by('pk').values_list('pk', 'is_active', 'is_staff', 'is_superuser')),
        }

    def assert_password(self, expected=OLD_PASSWORD):
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(expected))


@override_settings(**SECURITY)
class PasswordChangeTests(PasswordChangeHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        install_fixture(cls)

    def test_form_preferences_link_and_done_route_exist_in_all_three_languages(self):
        client = self.verified_client()
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                path = reverse('password_change')
                self.assertEqual(path, '/' + language + '/password-change/')
                self.assertNotIn('/security/', path)
                self.assertTrue(issubclass(resolve(path).func.view_class, PasswordChangeView))
                page = client.get(path)
                self.assertEqual(page.status_code, 200)
                self.assertIsInstance(page.context['form'], PasswordChangeForm)
                self.assertContains(page, _('Change password'))
                self.assertContains(page, _('Enter your current password and choose a new password. No email is needed.'))
                for field in ('old_password', 'new_password1', 'new_password2'):
                    self.assertContains(page, 'name="' + field + '"')
                self.assertContains(client.get(reverse('preferences')), 'href="' + path + '"')
                self.assertEqual(client.get(reverse('password_change_done')).status_code, 200)

    def test_anonymous_requests_cannot_change_a_password_or_view_done(self):
        client = Client()
        for route in ('password_change', 'password_change_done'):
            page = client.get(reverse(route))
            self.assertEqual(page.status_code, 302)
            self.assertTrue(page.url.startswith(reverse('login')))
        response = client.post(reverse('password_change'), {
            'old_password': OLD_PASSWORD, 'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assert_password()
        self.assertFalse(AuditEvent.objects.exists())

    def test_existing_mfa_middleware_blocks_unverified_privileged_get_and_post(self):
        client = Client()
        client.force_login(self.user)
        before = self.security_snapshot()
        for method in (client.get, client.post):
            response = method(reverse('password_change'), {'old_password': OLD_PASSWORD,
                'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse('mfa_verify'))
        self.assertEqual(client.get(reverse('password_change_done')).url, reverse('mfa_verify'))
        self.assert_password()
        self.assertEqual(self.security_snapshot(), before)
        self.assertFalse(AuditEvent.objects.exists())

    def test_privileged_user_without_a_device_is_sent_to_existing_setup(self):
        self.device.delete()
        client = Client()
        client.force_login(self.user)
        for method in (client.get, client.post):
            self.assertEqual(method(reverse('password_change')).url, reverse('mfa_setup'))
        self.assert_password()
        self.assertFalse(AuditEvent.objects.exists())

    def test_wrong_current_password_is_rejected_in_each_language_without_mutation(self):
        client = self.verified_client()
        before = self.security_snapshot()
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                path = reverse('password_change')
                response = client.post(path, self.payload(client, path, old='Fictional-Wrong-Current-Password!'))
                self.assertEqual(response.status_code, 200)
                self.assertIn('old_password', response.context['form'].errors)
                self.assert_password()
        self.assertEqual(self.security_snapshot(), before)
        self.assertFalse(AuditEvent.objects.exists())

    def test_weak_or_mismatched_new_password_never_saves_or_audits(self):
        client = self.verified_client()
        path = reverse('password_change')
        for changes in ({'new': 'short'}, {'new_password2': 'Fictional-Different-Confirmation!'}):
            with self.subTest(changes=changes):
                response = client.post(path, self.payload(client, path, **changes))
                self.assertEqual(response.status_code, 200)
                self.assertIn('new_password2', response.context['form'].errors)
                self.assert_password()
        self.assertFalse(AuditEvent.objects.exists())

    def test_csrf_is_still_required_with_a_verified_authenticated_session(self):
        client = self.verified_client()
        client.get(reverse('password_change'))
        response = client.post(reverse('password_change'), {'old_password': OLD_PASSWORD,
            'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertEqual(response.status_code, 403)
        self.assert_password()
        self.assertFalse(AuditEvent.objects.exists())

    def test_password_mutation_accepts_only_the_throttled_post_method(self):
        client = self.verified_client()
        path = reverse('password_change')
        data = self.payload(client, path)
        response = client.put(path, data, HTTP_X_CSRFTOKEN=data['csrfmiddlewaretoken'])
        self.assertEqual(response.status_code, 405)
        self.assert_password()
        self.assertFalse(AuditEvent.objects.exists())

    def test_success_in_each_language_preserves_mfa_rights_and_uses_no_transport(self):
        old = OLD_PASSWORD
        with patch('django.core.mail.send_mail') as mail, patch('smtplib.SMTP') as smtp, \
                patch('http.client.HTTPSConnection') as https:
            for language in ('fr', 'en', 'ar'):
                with self.subTest(language=language), translation.override(language):
                    client = self.verified_client()
                    before = self.security_snapshot()
                    session_key = client.session.session_key
                    new = NEW_PASSWORD + '-' + language
                    path = reverse('password_change')
                    response = client.post(path, self.payload(client, path, old=old, new=new))
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.url, reverse('password_change_done'))
                    self.assert_password(new)
                    self.assertEqual(client.session['_auth_user_id'], str(self.user.pk))
                    self.assertEqual(client.session['otp_device_id'], self.device.persistent_id)
                    self.assertNotEqual(client.session.session_key, session_key)
                    done = client.get(response.url)
                    self.assertEqual(done.status_code, 200)
                    self.assertTrue(done.context['user'].is_verified())
                    self.assertContains(done, _('Password changed'))
                    self.assertEqual(client.get(reverse('preferences')).status_code, 200)
                    self.assertEqual(self.security_snapshot(), before)
                    event = AuditEvent.objects.filter(action='security.password_changed').latest('pk')
                    self.assertEqual((event.actor_id, event.actor_ref, event.object_id, event.purpose_code),
                                     (self.user.pk, str(self.user.pk), str(self.user.pk), 'account_security'))
                    old = new
            mail.assert_not_called(); smtp.assert_not_called(); https.assert_not_called()
        self.assertEqual(AuditEvent.objects.filter(action='security.password_changed').count(), 3)

    def test_other_sessions_and_prior_reset_tokens_are_invalidated(self):
        other_session = self.verified_client()
        client = self.verified_client()
        old_token = default_token_generator.make_token(self.user)
        path = reverse('password_change')
        response = client.post(path, self.payload(client, path))
        self.assertEqual(response.status_code, 302)
        self.assert_password(NEW_PASSWORD)
        self.assertFalse(default_token_generator.check_token(self.user, old_token))
        self.assertEqual(client.get(reverse('preferences')).status_code, 200)
        stale = other_session.get(reverse('preferences'))
        self.assertEqual(stale.status_code, 302)
        self.assertTrue(stale.url.startswith(reverse('login')))
        self.assertNotIn('_auth_user_id', other_session.session)
        fresh = Client()
        self.assertFalse(fresh.login(username=self.user.username, password=OLD_PASSWORD))
        self.assertTrue(fresh.login(username=self.user.username, password=NEW_PASSWORD))
        self.assertEqual(fresh.get(reverse('preferences')).url, reverse('mfa_verify'))

    def test_family_without_mfa_retains_existing_policy_and_can_change_own_password_only(self):
        client = self.verified_client(self.other)
        path = reverse('password_change')
        response = client.post(path, self.payload(client, path, old=OTHER_PASSWORD,
            user_id=self.user.pk, username=self.user.username))
        self.assertEqual(response.status_code, 302)
        self.other.refresh_from_db()
        self.assertTrue(self.other.check_password(NEW_PASSWORD))
        self.assert_password()
        self.assertFalse(TOTPDevice.objects.filter(user=self.other).exists())
        event = AuditEvent.objects.get(action='security.password_changed')
        self.assertEqual((event.actor_id, event.object_id), (self.other.pk, str(self.other.pk)))

    def test_audit_failure_rolls_back_without_rotating_the_current_session(self):
        client = self.verified_client()
        path = reverse('password_change')
        data = self.payload(client, path)
        session_key = client.session.session_key
        with patch('core.password_views.audit', side_effect=RuntimeError('Fictional audit failure')):
            with self.assertRaises(RuntimeError):
                client.post(path, data)
        self.assert_password()
        self.assertFalse(AuditEvent.objects.exists())
        self.assertEqual(client.session.session_key, session_key)
        self.assertEqual(client.get(reverse('preferences')).status_code, 200)

    def test_save_failure_rolls_back_the_preceding_audit(self):
        client = self.verified_client()
        path = reverse('password_change')
        data = self.payload(client, path)
        with patch.object(PasswordChangeForm, 'save', side_effect=RuntimeError('Fictional save failure')):
            with self.assertRaises(RuntimeError):
                client.post(path, data)
        self.assert_password()
        self.assertFalse(AuditEvent.objects.exists())

    def test_lock_loads_fresh_user_before_validating_current_password(self):
        client = self.verified_client()
        path = reverse('password_change')
        data = self.payload(client, path)
        real_get = QuerySet.get
        real_clean = PasswordChangeForm.clean_old_password
        events = []
        replacement = 'Fictional-Concurrent-Password-Already-Changed!2026'

        def locked_get(queryset, *args, **kwargs):
            if queryset.model is User and queryset.query.select_for_update:
                self.assertTrue(queryset.query.select_for_no_key_update)
                self.assertTrue(connection.in_atomic_block)
                # Simulate a change after authentication loaded its user but
                # before this request retrieves its authoritative locked row.
                User.objects.filter(pk=self.user.pk).update(password=make_password(replacement))
                result = real_get(queryset, *args, **kwargs)
                events.append(('locked', result))
                return result
            return real_get(queryset, *args, **kwargs)

        def clean(form):
            self.assertEqual(len(events), 1)
            self.assertIs(form.user, events[0][1])
            events.append(('validated', form.user))
            return real_clean(form)

        with patch.object(QuerySet, 'get', locked_get), patch.object(PasswordChangeForm, 'clean_old_password', clean):
            response = client.post(path, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('old_password', response.context['form'].errors)
        self.assertEqual([event[0] for event in events], ['locked', 'validated'])
        self.assert_password(replacement)
        self.assertFalse(AuditEvent.objects.exists())

    def test_throttle_is_bound_to_authenticated_user_not_submitted_username(self):
        request = RequestFactory().post(reverse('password_change'), {'username': self.other.username})
        request.user = self.user
        self.assertEqual(attempt_identity(request, 'password_change'), 'user:' + str(self.user.pk))
        request.user = self.other
        self.assertEqual(attempt_identity(request, 'password_change'), 'user:' + str(self.other.pk))
        self.assertIn('password_change', LIMITS)
        client = self.verified_client()
        path = reverse('password_change')
        data = self.payload(client, path, old='Fictional wrong password')
        for _index in range(3):
            self.assertEqual(client.post(path, data).status_code, 200)
        limited = client.post(path, data)
        self.assertEqual(limited.status_code, 429)
        self.assertIn('Retry-After', limited)
        self.assert_password()
        self.assertFalse(AuditEvent.objects.exists())

    def test_success_refunds_only_its_reservation_and_retains_prior_failure(self):
        client = self.verified_client()
        path = reverse('password_change')
        self.assertEqual(client.post(path, self.payload(client, path, old='Fictional wrong password')).status_code, 200)
        keys = [key for key, _limit, _scope in bucket_specs('password_change', 'user:' + str(self.user.pk), '127.0.0.1')]
        self.assertEqual(set(RateWindow.objects.filter(key__in=keys).values_list('count', flat=True)), {1})
        self.assertEqual(client.post(path, self.payload(client, path)).status_code, 302)
        self.assertEqual(set(RateWindow.objects.filter(key__in=keys).values_list('count', flat=True)), {1})


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL user row locks and independent connections.')
@override_settings(**SECURITY)
class PasswordChangeConcurrencyTests(PasswordChangeHelpers, TransactionTestCase):
    def setUp(self):
        install_fixture(self)
        self.clients = [self.verified_client() for _index in range(2)]
        path = reverse('password_change')
        self.payloads = [self.payload(client, path, new=NEW_PASSWORD + '-' + str(index))
                         for index, client in enumerate(self.clients)]

    def worker(self, index, start):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
            start.wait(timeout=5)
            response = self.clients[index].post(reverse('password_change'), self.payloads[index])
            return {'index': index, 'status': response.status_code,
                    'url': response.headers.get('Location'),
                    'old_password_error': bool(response.context and response.context.get('form')
                                               and 'old_password' in response.context['form'].errors)}
        finally:
            connections.close_all()

    def test_same_old_password_race_changes_once_after_both_requests_authenticated(self):
        before = self.security_snapshot()
        before_lock = Barrier(2)
        start = Barrier(2)
        record_lock = Lock()
        lock_attempts = []
        real_get = QuerySet.get

        def synchronized_get(queryset, *args, **kwargs):
            if queryset.model is User and queryset.query.select_for_update:
                with record_lock:
                    lock_attempts.append(kwargs.get('pk'))
                before_lock.wait(timeout=5)
            return real_get(queryset, *args, **kwargs)

        with patch.object(QuerySet, 'get', synchronized_get):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.worker, index, start) for index in range(2)]
                results = [future.result(timeout=20) for future in futures]
        self.assertEqual(lock_attempts, [self.user.pk, self.user.pk])
        self.assertCountEqual([result['status'] for result in results], [302, 200])
        winner = next(result for result in results if result['status'] == 302)
        loser = next(result for result in results if result['status'] == 200)
        self.assertEqual(winner['url'], reverse('password_change_done'))
        self.assertTrue(loser['old_password_error'])
        self.assert_password(NEW_PASSWORD + '-' + str(winner['index']))
        self.assertEqual(AuditEvent.objects.filter(action='security.password_changed').count(), 1)
        self.assertEqual(self.security_snapshot(), before)
