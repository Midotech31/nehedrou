"""A03/A06 regressions use fictional accounts and isolated test databases only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django_otp.plugins.otp_totp.models import TOTPDevice

from care.models import Child, FamilyLink, Observation, Program
from catalog.models import Variety
from followup.models import ClinicalGoal
from .access import professional_children
from .auth_throttle import (LIMITS, WINDOW_SECONDS, bucket_specs, client_origin,
                            finish_attempt, reserve_attempt)
from .models import (AuditEvent, ChildResponsibilityTransfer, Membership,
                     Organization, PrivacyRequest, RateWindow, User)
from .services import resolve_privacy, revoke_membership, transfer_child

HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


def continuity_fixture(case):
    case.owner = User.objects.create_user(username='continuity-owner', email='owner@example.test')
    case.pro = User.objects.create_user(username='continuity-source', email='source@example.test')
    case.next = User.objects.create_user(username='continuity-next', email='next@example.test')
    case.foreign = User.objects.create_user(username='continuity-foreign', email='foreign@example.test')
    case.family = User.objects.create_user(username='continuity-family', email='family@example.test')
    case.org = Organization.objects.create(name='Fictional continuity practice')
    Membership.objects.create(user=case.owner, organization=case.org, role='owner')
    case.source_membership = Membership.objects.create(user=case.pro, organization=case.org, role='clinician')
    case.recipient_membership = Membership.objects.create(user=case.next, organization=case.org, role='clinician')
    other = Organization.objects.create(name='Fictional unrelated practice')
    Membership.objects.create(user=case.foreign, organization=other, role='owner')
    case.child = Child.objects.create(organization=case.org, responsible=case.pro, code='Continuity fictional child', age_years=5)
    case.archived = Child.objects.create(organization=case.org, responsible=case.pro, code='Archived fictional child', age_years=6, active=False)


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=HASHERS)
class ResponsibilityContinuityTests(TestCase):
    def setUp(self):
        continuity_fixture(self)

    def test_revocation_blocks_active_and_archived_without_disclosing_notes(self):
        self.client.force_login(self.owner)
        for child in (self.child, self.archived):
            with self.subTest(active=child.active):
                other = self.archived if child.active else self.child
                transfer_child(self.pro, other, self.next)
                try:
                    response = self.client.post(reverse('revoke_member', args=[self.source_membership.pk]), follow=True)
                    self.source_membership.refresh_from_db()
                    child.refresh_from_db()
                    self.assertTrue(self.source_membership.active)
                    self.assertEqual(child.responsible_id, self.pro.pk)
                    self.assertFalse(AuditEvent.objects.filter(action='member.revoked').exists())
                    self.assertContains(response, _('Transfer all assigned child profiles, including archived profiles, before revoking this practitioner. The responsible clinician must transfer each profile to an active practice member.'), status_code=200)
                    self.assertNotContains(response, child.code)
                    self.assertEqual(self.client.get(reverse('child_detail', args=[child.pk])).status_code, 404)
                finally:
                    transfer_child(self.next, other, self.pro)

    def test_transfer_preserves_goals_programs_private_notes_and_privacy_requests(self):
        variety = Variety.objects.create(code='fr-continuity', language='fr', label='Fictional French')
        self.child.varieties.add(variety)
        program = Program.objects.create(organization=self.org, child=self.child, variety=variety,
                                         created_by=self.pro, title='Original fictional program')
        note = Observation.objects.create(program=program, author=self.pro, text='Private fictional clinical note')
        objective = ClinicalGoal.objects.create(organization=self.org, child=self.child, author=self.pro,
            variety=variety, target_phoneme='p', target_position='initial', target_scope={'position': 'initial', 'context': 'isolated_word'}, rationale='Fictional rationale',
            expected_realization='/p/', functional_goal='Fictional goal')
        request = PrivacyRequest.objects.create(organization=self.org, child=self.child, requester=self.family, kind='export')
        FamilyLink.objects.create(child=self.child, user=self.family)
        transfer_child(self.pro, self.child, self.next)
        transfer_child(self.pro, self.archived, self.next)
        revoke_membership(self.owner, self.org, self.source_membership.pk)
        self.assertTrue(professional_children(self.next).filter(pk=self.child.pk).exists())
        self.assertTrue(professional_children(self.next).filter(pk=self.archived.pk).exists())
        self.assertFalse(professional_children(self.pro).exists())
        self.assertFalse(professional_children(self.owner).exists())
        self.assertFalse(professional_children(self.foreign).exists())
        for obj in (program, note, objective, request):
            obj.refresh_from_db()
        self.assertEqual(program.created_by_id, self.pro.pk)
        self.assertEqual(objective.author_id, self.pro.pk)
        self.assertEqual(note.author_id, self.pro.pk)
        self.assertEqual(request.child_id, self.child.pk)
        self.assertTrue(FamilyLink.objects.get(child=self.child, user=self.family).active)
        transfer = ChildResponsibilityTransfer.objects.get(child=self.child)
        self.assertEqual((transfer.previous_clinician_id, transfer.new_clinician_id, transfer.actor_id), (self.pro.pk, self.next.pk, self.pro.pk))
        self.client.force_login(self.next)
        self.assertContains(self.client.get(reverse('program_detail', args=[program.pk])), note.text)
        response = self.client.get(reverse('privacy_requests'))
        self.assertEqual(list(response.context['requests'].values_list('pk', flat=True)), [request.pk])
        resolve_privacy(self.next, request.pk, {'decision':'retain', 'reason':'Fictional continuity response', 'confirmation':''})
        for user in (self.pro, self.owner, self.foreign, self.family):
            self.client.force_login(user)
            self.assertNotContains(self.client.get(reverse('program_detail', args=[program.pk])), note.text,
                                   status_code=200 if user == self.family else 404)

    def test_only_current_responsible_can_transfer_to_a_current_same_practice_member(self):
        for actor, recipient in ((self.owner, self.next), (self.foreign, self.next), (self.pro, self.foreign)):
            with self.subTest(actor=actor.username, recipient=recipient.username), self.assertRaises(ValidationError):
                transfer_child(actor, self.child, recipient)
        # Simulates a valid submitted choice becoming revoked before the service locks.
        revoke_membership(self.owner, self.org, self.recipient_membership.pk)
        with self.assertRaises(ValidationError):
            transfer_child(self.pro, self.child, self.next)
        self.child.refresh_from_db()
        self.assertEqual(self.child.responsible_id, self.pro.pk)
        self.assertFalse(ChildResponsibilityTransfer.objects.exists())

    def test_technical_membership_save_cannot_orphan_dossiers(self):
        self.source_membership.active = False
        with self.assertRaises(ValidationError):
            self.source_membership.save()
        self.source_membership.refresh_from_db()
        self.assertTrue(self.source_membership.active)


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=HASHERS,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthenticationThrottleTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='auth-user', email='auth@example.test', password='fictional-password')
        self.other = User.objects.create_user(username='auth-other', email='other@example.test', password='fictional-password')

    def request(self, operation='login', identifier='auth-user', origin='203.0.113.10'):
        path = reverse(operation, args=['fictional-token']) if operation == 'invite' else reverse(operation)
        field = 'email' if operation == 'password_reset' else 'username'
        request = self.factory.post(path, {field:identifier}, REMOTE_ADDR=origin)
        request.resolver_match = resolve(path)
        request.user = self.user if operation.startswith('mfa_') else AnonymousUser()
        return request

    def test_normal_successes_on_shared_origin_do_not_spend_failure_budget(self):
        for index in range(25):
            self.client.logout()
            response = self.client.post(reverse('login'), {'username': self.user.username if index % 2 else self.other.username, 'password':'fictional-password'})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(sum(RateWindow.objects.values_list('count', flat=True)), 0)
        self.client.logout()
        self.assertEqual(self.client.post(reverse('login'), {'username':self.other.username, 'password':'fictional-password'}).status_code, 302)

    def test_successful_signups_spend_creation_budget_without_blocking_shared_origin_logins(self):
        origin = '203.0.113.44'
        password = 'Fictional-strong-test-only!2026'
        def signup(index, address=origin):
            return Client().post(reverse('signup'), {
                'username': 'created-user-' + str(index),
                'email': 'created-' + str(index) + '@example.test',
                'practice_name': 'Fictional practice ' + str(index),
                'instruction_language': 'fr', 'password1': password, 'password2': password,
            }, REMOTE_ADDR=address)
        # A small configured origin budget exercises real, valid account creation.
        with patch.dict(LIMITS, {'signup': (5, 10, 3)}):
            for index in range(3):
                response = signup(index)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(User.objects.filter(username='created-user-' + str(index)).exists())
            denied = signup(3)
            self.assertEqual(denied.status_code, 429)
            self.assertGreater(int(denied['Retry-After']), 0)
            self.assertFalse(User.objects.filter(username='created-user-3').exists())
            origin_key = next(key for key, _limit, scope in bucket_specs('signup', 'unused', origin) if scope == 'origin')
            self.assertEqual(RateWindow.objects.get(key=origin_key).count, 3)
            self.assertFalse(RateWindow.objects.exclude(blocked_until=None).exists())
            self.assertEqual(signup(4, '198.51.100.44').status_code, 302)
            for index in range(3):
                response = Client().post(reverse('login'), {'username': 'created-user-' + str(index), 'password': password}, REMOTE_ADDR=origin)
                self.assertEqual(response.status_code, 302)
            login_origin = next(key for key, _limit, scope in bucket_specs('login', 'unused', origin) if scope == 'origin')
            self.assertEqual(RateWindow.objects.get(key=login_origin).count, 0)

    def test_identifier_and_origin_cooldown_are_isolated_between_users_and_operations(self):
        base = timezone.now()
        with patch('core.auth_throttle.timezone.now', return_value=base):
            for _ in range(3):
                self.assertEqual(self.client.post(reverse('login'), {'username':self.user.username, 'password':'wrong'}).status_code, 200)
            denied = self.client.post(reverse('login'), {'username':self.user.username, 'password':'wrong'})
            self.assertEqual(denied.status_code, 429)
            self.assertGreater(int(denied['Retry-After']), 0)
            self.assertEqual(self.client.post(reverse('login'), {'username':self.other.username, 'password':'fictional-password'}).status_code, 302)
            self.client.logout()
            self.assertEqual(self.client.post(reverse('password_reset'), {'email':self.user.email}).status_code, 302)
        with patch('core.auth_throttle.timezone.now', return_value=base + timedelta(seconds=3)):
            self.assertEqual(self.client.post(reverse('login'), {'username':self.user.username, 'password':'wrong'}).status_code, 200)
            self.assertGreaterEqual(int(self.client.post(reverse('login'), {'username':self.user.username, 'password':'wrong'})['Retry-After']), 4)

    def test_identifier_limit_spans_origins_and_origin_limit_bounds_identifier_spray(self):
        for scope in ('identifier', 'origin'):
            RateWindow.objects.all().delete()
            specs = bucket_specs('login', self.user.username, '203.0.113.10')
            key, limit, _ = next(spec for spec in specs if spec[2] == scope)
            RateWindow.objects.create(key=key, count=limit)
            self.assertGreater(reserve_attempt(self.request()), 0)
            if scope == 'identifier':
                self.assertGreater(reserve_attempt(self.request(origin='198.51.100.20')), 0)
                self.assertIsNone(reserve_attempt(self.request(identifier='different-user')))
            else:
                self.assertGreater(reserve_attempt(self.request(identifier='different-user')), 0)
                self.assertIsNone(reserve_attempt(self.request(origin='198.51.100.20')))

    def test_refund_does_not_erase_another_request_or_a_new_window(self):
        first, second = self.request(), self.request()
        self.assertIsNone(reserve_attempt(first))
        self.assertIsNone(reserve_attempt(second))
        first.user = self.user
        finish_attempt(first, HttpResponse(status=302))
        self.assertEqual(set(RateWindow.objects.values_list('count', flat=True)), {1})
        future = timezone.now() + timedelta(seconds=WINDOW_SECONDS + 1)
        with patch('core.auth_throttle.timezone.now', return_value=future):
            third = self.request()
            self.assertIsNone(reserve_attempt(third))
            finish_attempt(second, HttpResponse(status=200))
            self.assertEqual(set(RateWindow.objects.values_list('count', flat=True)), {1})

    def test_exhausted_origin_cannot_create_rows_by_spraying_new_identifiers(self):
        key, limit, _ = next(spec for spec in bucket_specs('login', self.user.username, '203.0.113.10') if spec[2] == 'origin')
        RateWindow.objects.create(key=key, count=limit)
        for index in range(20):
            self.assertGreater(reserve_attempt(self.request(identifier='sprayed-' + str(index))), 0)
        self.assertEqual(RateWindow.objects.count(), 1)

    def test_reset_neutral_success_and_invite_token_abuse_remain_limited(self):
        for operation, data in [('password_reset', {'email':'absent@example.test'}), ('invite', {})]:
            RateWindow.objects.all().delete()
            path = reverse(operation, args=['nonexistent-token']) if operation == 'invite' else reverse(operation)
            with patch('core.auth_throttle.timezone.now', return_value=timezone.now()):
                for _ in range(3):
                    self.assertIn(self.client.post(path, data).status_code, (302, 404))
                self.assertEqual(self.client.post(path, data).status_code, 429)

    def test_mfa_success_refunds_and_failures_use_account_identity_not_token(self):
        TOTPDevice.objects.create(user=self.user, name='primary', confirmed=True)
        self.client.force_login(self.user)
        with patch('core.auth_throttle.timezone.now', return_value=timezone.now()):
            for token in ('incorrect-a', 'incorrect-b', 'incorrect-c'):
                self.assertEqual(self.client.post(reverse('mfa_verify'), {'token':token}).status_code, 200)
            self.assertEqual(self.client.post(reverse('mfa_verify'), {'token':'incorrect-d'}).status_code, 429)
        RateWindow.objects.all().delete()
        with patch('core.security.verify_token', return_value=TOTPDevice.objects.get(user=self.user)):
            self.assertEqual(self.client.post(reverse('mfa_verify'), {'token':'123456'}).status_code, 302)
        self.assertEqual(sum(RateWindow.objects.values_list('count', flat=True)), 0)

    def test_setup_and_recovery_credentials_and_reset_confirmation_are_throttled(self):
        self.client.force_login(self.user)
        # Account identity is stable when the attacker changes the submitted code.
        with patch('core.auth_throttle.timezone.now', return_value=timezone.now()):
            for code in ('000001', '000002', '000003'):
                self.assertEqual(self.client.post(reverse('mfa_setup'), {'password':'wrong', 'token':code}).status_code, 200)
            self.assertEqual(self.client.post(reverse('mfa_setup'), {'password':'wrong', 'token':'000004'}).status_code, 429)
        RateWindow.objects.all().delete()
        device = TOTPDevice.objects.get(user=self.user)
        device.confirmed = True
        device.save()
        session = self.client.session
        session['otp_device_id'] = device.persistent_id
        session.save()
        with patch('core.auth_throttle.timezone.now', return_value=timezone.now()):
            for _ in range(3):
                self.assertEqual(self.client.post(reverse('mfa_recovery'), {'password':'wrong'}).status_code, 200)
            self.assertEqual(self.client.post(reverse('mfa_recovery'), {'password':'wrong'}).status_code, 429)
        RateWindow.objects.all().delete()
        self.client.logout()
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        path = reverse('password_reset_confirm', args=[urlsafe_base64_encode(force_bytes(self.user.pk)), default_token_generator.make_token(self.user)])
        response = self.client.get(path)
        safe_path = response.url
        with patch('core.auth_throttle.timezone.now', return_value=timezone.now()):
            for _ in range(3):
                self.assertEqual(self.client.post(safe_path, {'new_password1':'short', 'new_password2':'different'}).status_code, 200)
            self.assertEqual(self.client.post(safe_path, {'new_password1':'short', 'new_password2':'different'}).status_code, 429)

    def test_proxy_headers_need_trusted_peer_and_rightmost_chain_validation(self):
        request = self.request()
        request.META['HTTP_X_FORWARDED_FOR'] = '192.0.2.99'
        self.assertEqual(client_origin(request), '203.0.113.10')
        request.META['REMOTE_ADDR'] = '10.0.0.2'
        with override_settings(AUTH_TRUSTED_PROXY_CIDRS=['10.0.0.0/8']):
            request.META['HTTP_X_FORWARDED_FOR'] = '192.0.2.99, 198.51.100.20, 10.0.0.1'
            self.assertEqual(client_origin(request), '198.51.100.20')
            request.META['HTTP_X_FORWARDED_FOR'] = '192.0.2.99, malformed'
            self.assertEqual(client_origin(request), '10.0.0.2')
        with override_settings(AUTH_TRUSTED_PROXY_CIDRS=['invalid-cidr']):
            self.assertEqual(client_origin(request), '10.0.0.2')


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=HASHERS)
class ConcurrentResponsibilityTests(TransactionTestCase):
    def setUp(self):
        continuity_fixture(self)

    def worker(self, fn, started):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
            started.set()
            try:
                fn()
                return 'accepted'
            except ValidationError:
                return 'refused'
        finally:
            connections.close_all()

    def test_transfer_waits_for_recipient_revocation_and_refuses(self):
        started = Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Organization.objects.select_for_update().get(pk=self.org.pk)
                revoke_membership(self.owner, self.org, self.recipient_membership.pk)
                future = pool.submit(self.worker, lambda:transfer_child(self.pro, self.child, self.next), started)
                self.assertTrue(started.wait(3))
            self.assertEqual(future.result(timeout=8), 'refused')
        self.child.refresh_from_db()
        self.assertEqual(self.child.responsible_id, self.pro.pk)

    def test_recipient_revocation_waits_for_transfer_and_refuses(self):
        started = Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                transfer_child(self.pro, self.child, self.next)
                future = pool.submit(self.worker, lambda:revoke_membership(self.owner, self.org, self.recipient_membership.pk), started)
                self.assertTrue(started.wait(3))
            self.assertEqual(future.result(timeout=8), 'refused')
        self.recipient_membership.refresh_from_db()
        self.assertTrue(self.recipient_membership.active)

    def test_source_revocation_waits_for_active_and_archived_transfers_then_succeeds(self):
        started = Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                transfer_child(self.pro, self.child, self.next)
                transfer_child(self.pro, self.archived, self.next)
                future = pool.submit(self.worker, lambda:revoke_membership(self.owner, self.org, self.source_membership.pk), started)
                self.assertTrue(started.wait(3))
            self.assertEqual(future.result(timeout=8), 'accepted')
        self.source_membership.refresh_from_db()
        self.assertFalse(self.source_membership.active)
        self.assertEqual(professional_children(self.next).count(), 2)


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
@override_settings(PASSWORD_HASHERS=HASHERS)
class ConcurrentAuthThrottleTests(TransactionTestCase):
    def test_new_bucket_admission_cannot_overshoot_under_concurrency(self):
        from threading import Barrier
        gate = Barrier(8)
        def attempt():
            connections.close_all()
            try:
                request = RequestFactory().post(reverse('login'), {'username':'same-user'}, REMOTE_ADDR='203.0.113.23')
                request.user = AnonymousUser()
                request.resolver_match = resolve(request.path)
                gate.wait(timeout=10)
                return reserve_attempt(request)
            finally:
                connections.close_all()
        # Use a budget below the simultaneous in-flight requests; none finish yet.
        with patch.dict(LIMITS, {'login': (5, 30, 120)}), ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _:attempt(), range(8)))
        self.assertEqual(results.count(None), 5)
        self.assertEqual(RateWindow.objects.count(), 3)
        self.assertEqual(set(RateWindow.objects.values_list('count', flat=True)), {5})
