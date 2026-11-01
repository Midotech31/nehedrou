"""Manual editorial links use fictional recipients and never a real mail transport."""
import hashlib
import json
import uuid
from contextlib import ExitStack
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from catalog.editorial_access import (
    accept_editorial_access_invitation, issue_editorial_access_invitation,
    issue_manual_editorial_access_invitation,
    revoke_editorial_invitation,
)
from catalog.models import EditorialAccessInvitation, EditorialGrant, Variety
from core.middleware import AccessMiddleware
from core.models import AuditEvent, Membership, User


@override_settings(DEMO_MODE=False, DEBUG=False, MFA_REQUIRED=False,
    EMAIL_BACKEND='core.email_backends.DisabledEmailBackend',
    PUBLIC_ORIGIN='https://editorial.example', LANGUAGE_CODE='en',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ManualEditorialHandoffTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('manual-manager', 'manual-manager@example.test')
        cls.manager.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.ordinary = User.objects.create_user('manual-ordinary', 'manual-ordinary@example.test')
        cls.variety = Variety.objects.create(code='manual-ar-fixture', language='ar', label='Fictional regional Arabic')
        cls.other_variety = Variety.objects.create(code='manual-fr-fixture', language='fr', label='Fictional regional French')

    def setUp(self):
        self.client.force_login(self.manager)
        self.path = '/en/operations/editorial-access/'

    def payload(self, **overrides):
        return {'email': 'manual-reviewer@example.test', 'variety': str(self.variety.pk),
                'capability': 'clinical_review', 'delivery_method': 'manual',
                'creation_id': str(uuid.uuid4()), **overrides}

    def issue(self, *, email='manual-reviewer@example.test', variety=None,
              capability='clinical_review', creation_id=None, actor=None):
        return issue_manual_editorial_access_invitation(
            actor or self.manager, email, variety or self.variety, capability,
            creation_id or uuid.uuid4())

    def snapshot(self):
        return (list(EditorialAccessInvitation.objects.order_by('pk').values()),
                list(AuditEvent.objects.order_by('pk').values()),
                list(User.objects.order_by('pk').values('pk', 'email', 'is_active', 'is_staff', 'is_superuser')),
                list(EditorialGrant.objects.order_by('pk').values()),
                list(Membership.objects.order_by('pk').values()))

    def prior(self, email, variety=None, capability='clinical_review'):
        invitation, token = EditorialAccessInvitation.issue(
            email, variety or self.variety, capability, self.manager)
        return invitation, token

    def test_initial_delivery_mode_uses_local_configuration_and_legacy_post_keeps_email(self):
        configurations = (
            ({'EMAIL_BACKEND': 'core.email_backends.DisabledEmailBackend'},
             'manual', 'unavailable'),
            ({'EMAIL_BACKEND': 'core.email_backends.ResendEmailBackend', 'RESEND_ENABLED': True,
              'RESEND_API_KEY': 're_fictional_invitation_config', 'EMAIL_HTTP_CONNECT_TIMEOUT': 5,
              'EMAIL_HTTP_READ_TIMEOUT': 10, 'DEFAULT_FROM_EMAIL': 'Access <access@fictional-mail.tld>'},
             'email', 'configuration_present'),
        )
        guarded_targets = ('django.core.mail.get_connection', 'django.core.mail.send_mail',
                           'socket.getaddrinfo', 'socket.create_connection',
                           'http.client.HTTPSConnection', 'smtplib.SMTP', 'smtplib.SMTP_SSL')
        for settings, expected_method, expected_state in configurations:
            with self.subTest(method=expected_method), override_settings(**settings):
                with ExitStack() as guards:
                    guarded = [guards.enter_context(patch(target)) for target in guarded_targets]
                    response = self.client.get(self.path)
                for operation in guarded:
                    operation.assert_not_called()
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="delivery_method"')
                self.assertEqual(response.context['form']['delivery_method'].value(), expected_method)
                report = response.context['invitation_delivery']
                self.assertEqual(report['state'], expected_state)
                self.assertEqual(report['known_unavailable'], expected_method == 'manual')
                self.assertFalse(report['network_attempted'])
                self.assertFalse(report['delivery_verified'])
                self.assertContains(response, '<option value="' + expected_method + '" selected>')
                self.assertFalse(EditorialAccessInvitation.objects.exists())
                if expected_method == 'manual':
                    self.assertContains(response,
                        'Email delivery is unavailable. You can create a link to hand over personally.')
                else:
                    self.assertNotContains(response,
                        'Email delivery is unavailable. You can create a link to hand over personally.')

        legacy = self.payload(email='legacy-editorial@example.test')
        legacy.pop('delivery_method')
        legacy.pop('creation_id')
        with patch('catalog.editorial_access_views.issue_editorial_access_invitation',
                   wraps=issue_editorial_access_invitation) as email_issue, \
                patch('catalog.editorial_access_views.issue_manual_editorial_access_invitation') as manual_issue:
            response = self.client.post(self.path, legacy)
        self.assertEqual(response.status_code, 302)
        email_issue.assert_called_once_with(self.manager, email=legacy['email'],
                                            variety=self.variety, capability=legacy['capability'])
        manual_issue.assert_not_called()
        self.assertEqual(EditorialAccessInvitation.objects.get(email=legacy['email']).delivery, 'failed')

    def test_manual_post_shows_link_once_with_recipient_scope_and_private_headers(self):
        payload = self.payload(email='  MANUAL-REVIEWER@EXAMPLE.TEST  ')
        with patch('catalog.editorial_access.send_mail') as send:
            response = self.client.post(self.path, payload)
        send.assert_not_called()
        self.assertEqual(response.status_code, 200)
        invitation = response.context['manual_invitation']
        link = response.context['manual_link']
        token = urlsplit(link).path.rstrip('/').split('/')[-1]
        self.assertEqual(invitation.pk, uuid.UUID(payload['creation_id']))
        self.assertEqual(invitation.email, 'manual-reviewer@example.test')
        self.assertEqual(invitation.delivery, 'manual')
        self.assertEqual(invitation.token_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertTrue(invitation.available)
        self.assertFalse(response.context['manual_already_created'])
        self.assertContains(response, link)
        self.assertContains(response, invitation.email)
        self.assertContains(response, self.variety.display_label)
        self.assertContains(response, invitation.get_capability_display())
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertIn('readonly', response.content.decode())
        self.assertIn('dir="ltr"', response.content.decode())
        self.assertNotEqual(str(response.context['form']['creation_id'].value()), payload['creation_id'])
        self.assertEqual(User.objects.count(), 2)
        self.assertFalse(EditorialGrant.objects.exists())
        self.assertFalse(Membership.objects.exists())
        persisted = json.dumps({'invitations': list(EditorialAccessInvitation.objects.values()),
                                'audit': list(AuditEvent.objects.values()),
                                'session': dict(self.client.session)}, default=str)
        self.assertNotIn(token, persisted)
        self.assertNotIn(token, str(response.cookies))
        self.assertNotIn(token, str(list(response.context['messages'])))
        for path in (self.path, self.path + '?creation_id=' + payload['creation_id']):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertFalse(page.context.get('manual_link'))
            self.assertEqual(page['Referrer-Policy'], 'same-origin')
            self.assertNotContains(page, token)
            self.assertNotContains(page, invitation.token_hash)

    def test_same_post_replay_keeps_first_link_without_revealing_it_again(self):
        payload = self.payload()
        first = self.client.post(self.path, payload)
        link = first.context['manual_link']
        invitation = first.context['manual_invitation']
        before = self.snapshot()
        repeated = self.client.post(self.path, payload)
        self.assertEqual(repeated.status_code, 200)
        self.assertTrue(repeated.context['manual_already_created'])
        self.assertFalse(repeated.context['manual_link'])
        self.assertNotContains(repeated, link)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.get(urlsplit(link).path).status_code, 200)
        invitation.refresh_from_db()
        self.assertFalse(invitation.revoked)

    def test_replay_after_acceptance_or_revocation_never_rotates_or_reactivates(self):
        for state in ('used', 'revoked'):
            with self.subTest(state=state):
                identifier = uuid.uuid4()
                invitation, token = self.issue(email=state + '@example.test', creation_id=identifier)
                if state == 'used':
                    user = User.objects.create_user(state, invitation.email)
                    accept_editorial_access_invitation(user, token)
                else:
                    revoke_editorial_invitation(self.manager, invitation.pk)
                before = self.snapshot()
                repeated, repeated_token = self.issue(email=invitation.email, creation_id=identifier)
                self.assertEqual(repeated.pk, invitation.pk)
                self.assertIsNone(repeated_token)
                self.assertEqual(self.snapshot(), before)

    def test_same_creation_id_changed_payload_or_actor_is_refused_before_any_revoke(self):
        identifier = uuid.uuid4()
        invitation, _token = self.issue(creation_id=identifier)
        another_manager = User.objects.create_user('another-manual-manager', 'another-manager@example.test')
        another_manager.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cases = [
            {'email': 'changed@example.test'}, {'variety': self.other_variety},
            {'capability': 'linguistic_review'}, {'actor': another_manager},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.prior(overrides.get('email', invitation.email),
                           overrides.get('variety', self.variety),
                           overrides.get('capability', 'clinical_review'))
                before = self.snapshot()
                with self.assertRaises(ValidationError):
                    self.issue(creation_id=identifier, **overrides)
                self.assertEqual(self.snapshot(), before)
        before = self.snapshot()
        response = self.client.post(self.path, self.payload(
            creation_id=str(identifier), email='changed@example.test'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(response.context.get('manual_link'))
        self.assertEqual(self.snapshot(), before)

    def test_creation_id_cannot_reuse_an_email_invitation(self):
        invitation, _token = self.prior('manual-reviewer@example.test')
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.issue(creation_id=invitation.pk)
        self.assertEqual(self.snapshot(), before)

    def test_new_creation_revokes_only_matching_live_triplet(self):
        invitation, old_token = self.issue()
        other_role, _ = self.issue(capability='linguistic_review')
        other_variety, _ = self.issue(variety=self.other_variety)
        other_email, _ = self.issue(email='other-reviewer@example.test')
        replacement, new_token = self.issue()
        invitation.refresh_from_db()
        self.assertTrue(invitation.revoked)
        self.assertNotEqual(new_token, old_token)
        self.assertTrue(replacement.available)
        for untouched in (other_role, other_variety, other_email):
            untouched.refresh_from_db()
            self.assertFalse(untouched.revoked)
            self.assertTrue(untouched.available)
        self.assertEqual(self.client.get(reverse('accept_editorial_invite', args=[old_token])).status_code, 410)
        self.assertEqual(self.client.get(reverse('accept_editorial_invite', args=[new_token])).status_code, 200)

    def test_permissions_and_csrf_are_required_before_creation(self):
        before = self.snapshot()
        self.client.logout()
        self.assertEqual(self.client.post(self.path, self.payload()).status_code, 302)
        self.client.force_login(self.ordinary)
        self.assertEqual(self.client.post(self.path, self.payload()).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.issue(actor=self.ordinary)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.manager)
        self.assertEqual(protected.post(self.path, self.payload()).status_code, 403)
        self.assertEqual(self.snapshot(), before)
        page = protected.get(self.path, secure=True)
        self.assertEqual(page.status_code, 200)
        data = self.payload(csrfmiddlewaretoken=protected.cookies['csrftoken'].value)
        created = protected.post(self.path, data, secure=True, HTTP_ORIGIN='https://testserver')
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created['Referrer-Policy'], 'no-referrer')
        self.assertNotIn('HTTP_REFERER', created.wsgi_request.META)
        self.assertTrue(created.wsgi_request.is_secure())
        self.assertEqual(EditorialAccessInvitation.objects.count(), 1)
        first_invitation = created.context['manual_invitation']
        next_id = str(created.context['form']['creation_id'].value())
        self.assertNotEqual(next_id, data['creation_id'])
        next_data = self.payload(creation_id=next_id,
                                 csrfmiddlewaretoken=protected.cookies['csrftoken'].value)
        next_created = protected.post(self.path, next_data, secure=True,
                                      HTTP_ORIGIN='https://testserver')
        self.assertEqual(next_created.status_code, 200)
        self.assertEqual(next_created['Referrer-Policy'], 'no-referrer')
        self.assertNotIn('HTTP_REFERER', next_created.wsgi_request.META)
        self.assertTrue(next_created.context['manual_link'])
        self.assertEqual(EditorialAccessInvitation.objects.count(), 2)
        first_invitation.refresh_from_db()
        self.assertTrue(first_invitation.revoked)
        self.assertTrue(next_created.context['manual_invitation'].available)

    def test_inactive_manager_cannot_issue_even_with_cached_permission(self):
        self.assertTrue(self.manager.has_perm('core.manage_entitlements'))
        self.manager.is_active = False
        before = self.snapshot()
        with self.assertRaises(PermissionDenied):
            self.issue()
        self.assertEqual(self.snapshot(), before)

    def test_manual_creation_requires_a_valid_explicit_uuid_and_delivery_mode(self):
        for value in ('', 'not-a-uuid'):
            with self.subTest(value=value):
                response = self.client.post(self.path, self.payload(creation_id=value))
                self.assertEqual(response.status_code, 200)
                self.assertIn('creation_id', response.context['form'].errors)
                self.assertEqual(response['Referrer-Policy'], 'no-referrer')
                self.assertIn('no-store', response['Cache-Control'])
                self.assertFalse(EditorialAccessInvitation.objects.exists())
        response = self.client.post(self.path, self.payload(delivery_method='unsupported'))
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(EditorialAccessInvitation.objects.exists())

    def test_only_three_limited_capabilities_are_assignable_and_variety_scoped(self):
        for capability in ('edit', 'clinical_review', 'linguistic_review'):
            with self.subTest(capability=capability), patch('catalog.editorial_access.send_mail') as send:
                invitation, token = self.issue(email=capability + '@example.test', capability=capability)
                user = User.objects.create_user(capability, invitation.email)
                grant = accept_editorial_access_invitation(user, token)
                self.assertEqual(grant.variety_id, self.variety.pk)
                self.assertEqual(grant.user_id, user.pk)
                for name in ('edit', 'clinical_review', 'linguistic_review', 'publish'):
                    self.assertEqual(getattr(grant, name), name == capability)
                self.assertFalse(EditorialGrant.objects.filter(user=user, variety=self.other_variety).exists())
                self.assertFalse(Membership.objects.filter(user=user).exists())
                self.assertFalse(user.is_staff or user.is_superuser or user.has_perm('core.manage_entitlements'))
                send.assert_not_called()
        for capability in ('publish', 'is_superuser', 'manage_entitlements'):
            with self.subTest(capability=capability):
                before = self.snapshot()
                with self.assertRaises(ValidationError):
                    self.issue(capability=capability)
                self.assertEqual(self.snapshot(), before)

    def test_disabled_recipient_cannot_be_invited_or_have_old_link_rotated(self):
        recipient = User.objects.create_user('inactive-manual', 'inactive-manual@example.test', is_active=False)
        self.prior(recipient.email)
        before = self.snapshot()
        with patch('catalog.editorial_access.send_mail') as send:
            with self.assertRaises(ValidationError):
                self.issue(email=recipient.email.upper())
        send.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        recipient.refresh_from_db()
        self.assertFalse(recipient.is_active)

    def test_account_disabled_after_issue_cannot_accept_or_be_reactivated(self):
        recipient = User.objects.create_user('later-inactive', 'later-inactive@example.test')
        invitation, token = self.issue(email=recipient.email)
        User.objects.filter(pk=recipient.pk).update(is_active=False)
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            accept_editorial_access_invitation(recipient, token)
        self.assertEqual(self.snapshot(), before)
        recipient.refresh_from_db()
        self.assertFalse(recipient.is_active)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)

    def test_publisher_for_same_variety_is_refused_without_changing_old_access(self):
        recipient = User.objects.create_user('manual-publisher', 'manual-publisher@example.test')
        grant = EditorialGrant.objects.create(user=recipient, variety=self.variety, publish=True)
        self.prior(recipient.email)
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.issue(email=recipient.email)
        self.assertEqual(self.snapshot(), before)
        grant.refresh_from_db()
        self.assertTrue(grant.publish)
        other_invitation, token = self.issue(email=recipient.email, variety=self.other_variety)
        other_grant = accept_editorial_access_invitation(recipient, token)
        self.assertEqual(other_grant.variety_id, other_invitation.variety_id)
        self.assertTrue(other_grant.clinical_review)
        grant.refresh_from_db()
        self.assertTrue(grant.publish)

    def test_publisher_added_after_issue_blocks_acceptance_and_preserves_permissions(self):
        recipient = User.objects.create_user('later-publisher', 'later-publisher@example.test')
        invitation, token = self.issue(email=recipient.email)
        grant = EditorialGrant.objects.create(user=recipient, variety=self.variety, publish=True)
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            accept_editorial_access_invitation(recipient, token)
        self.assertEqual(self.snapshot(), before)
        grant.refresh_from_db()
        self.assertTrue(grant.publish)
        self.assertFalse(grant.clinical_review)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.used_at)

    def test_token_is_email_bound_single_use_expiring_and_revocable(self):
        recipient = User.objects.create_user('bound-reviewer', 'bound-reviewer@example.test')
        invitation, token = self.issue(email=recipient.email)
        with self.assertRaises(ValidationError):
            accept_editorial_access_invitation(self.ordinary, token)
        self.assertFalse(EditorialGrant.objects.exists())
        accept_editorial_access_invitation(recipient, token)
        with self.assertRaises(ValidationError):
            accept_editorial_access_invitation(recipient, token)
        for mode in ('expired', 'revoked'):
            with self.subTest(mode=mode):
                other, other_token = self.issue(email=mode + '@example.test')
                if mode == 'expired':
                    other.expires_at = timezone.now() - timedelta(seconds=1)
                    other.save(update_fields=['expires_at'])
                else:
                    revoke_editorial_invitation(self.manager, other.pk)
                before = self.snapshot()
                self.assertEqual(self.client.get(reverse('accept_editorial_invite', args=[other_token])).status_code, 410)
                self.assertEqual(self.snapshot(), before)
        self.assertLessEqual(invitation.expires_at - timezone.now(), timedelta(days=7))
        self.assertGreater(invitation.expires_at - timezone.now(), timedelta(days=6, hours=23))

    def test_manual_link_allows_recipient_signup_only_on_acceptance(self):
        invitation, token = self.issue(capability='linguistic_review')
        self.assertFalse(User.objects.filter(email=invitation.email).exists())
        self.client.logout()
        response = self.client.post(reverse('accept_editorial_invite', args=[token]), {
            'username': 'manual-signup-reviewer', 'instruction_language': 'ar',
            'password1': 'Fictional-Reviewer-Password-583!x',
            'password2': 'Fictional-Reviewer-Password-583!x',
            'email': 'attacker@example.test', 'is_superuser': 'on', 'publish': 'on'})
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email=invitation.email)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertFalse(Membership.objects.filter(user=user).exists())
        grant = EditorialGrant.objects.get(user=user, variety=self.variety)
        self.assertTrue(grant.linguistic_review)
        self.assertFalse(grant.edit or grant.clinical_review or grant.publish)

    def test_manual_handoff_renders_three_languages_and_rtl_without_backend_details(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                response = self.client.post('/' + language + '/operations/editorial-access/',
                    self.payload(email=language + '-manual@example.test'))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['manual_link'])
                self.assertContains(response, _('Link created for manual handoff'))
                self.assertNotContains(response, 'DisabledEmailBackend')
                self.assertNotContains(response, 'RESEND_API_KEY')
                if language == 'ar':
                    self.assertContains(response, 'dir="rtl"')


class ManualEditorialReferrerPolicyTests(SimpleTestCase):
    def test_middleware_preserves_only_explicit_no_referrer_policy(self):
        for supplied, expected in ((None, 'same-origin'), ('unsafe-url', 'same-origin'),
                                   ('no-referrer', 'no-referrer')):
            for authenticated in (False, True):
                with self.subTest(supplied=supplied, authenticated=authenticated):
                    request = RequestFactory().get('/en/operations/editorial-access/')
                    request.user = User(username='unsaved-policy-fixture') if authenticated else AnonymousUser()
                    response = HttpResponse('Fictional policy fixture')
                    if supplied:
                        response.headers['Referrer-Policy'] = supplied
                    result = AccessMiddleware(lambda _request: response)(request)
                    self.assertEqual(result['Referrer-Policy'], expected)
                    if authenticated:
                        self.assertIn('private', result['Cache-Control'])
                        self.assertIn('no-store', result['Cache-Control'])
