"""Fictitious privacy requests through the normal intake and decision routes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from care.models import Child, FamilyLink
from core.models import AuditEvent, Membership, Organization, PrivacyRequest, User
from core.services import audit, create_erasure_request, resolve_privacy


SETTINGS = {'DEMO_MODE': False, 'MFA_REQUIRED': False, 'SECURE_SSL_REDIRECT': False}


class PrivacyFixture:
    @classmethod
    def setup_practice(cls):
        cls.org = Organization.objects.create(name='Fictional privacy practice', retention_days=0)
        cls.clinician = User.objects.create_user('privacy-clinician', 'privacy-clinician@example.test')
        cls.owner = User.objects.create_user('privacy-owner', 'privacy-owner@example.test')
        cls.first = User.objects.create_user('privacy-first', 'privacy-first@example.test')
        cls.second = User.objects.create_user('privacy-second', 'privacy-second@example.test')
        Membership.objects.create(organization=cls.org, user=cls.clinician, role='clinician')
        Membership.objects.create(organization=cls.org, user=cls.owner, role='owner')
        cls.child = cls.make_child('Fictional privacy dossier')
        for caregiver in (cls.first, cls.second):
            FamilyLink.objects.create(child=cls.child, user=caregiver)

    @classmethod
    def make_child(cls, code, organization=None):
        return Child.objects.create(organization=organization or cls.org, responsible=cls.clinician,
            age_years=5, code=code, created_at=timezone.now() - timedelta(days=2))

    def account(self, user):
        client = Client()
        client.force_login(user)
        return client

    @property
    def intake(self):
        return f'/en/children/{self.child.pk}/privacy/'

    def resolution(self, item, language='en'):
        return f'/{language}/requests/{item.pk}/'

    def erasure(self):
        return {'decision': 'erase', 'confirmation': self.child.code,
                'reason': 'A fictional decision note belonging only to the selected request.'}

    def request_from(self, user):
        response = self.account(user).post(self.intake)
        self.assertEqual(response.status_code, 302)
        return PrivacyRequest.objects.get(requester=user, child=self.child, kind='erasure')


@override_settings(**SETTINGS)
class PrivacyErasureRequestsTests(PrivacyFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.setup_practice()

    def test_erase_fulfils_exact_pending_erasure_requests_and_preserves_other_decisions(self):
        first = self.request_from(self.first)
        second = self.request_from(self.second)
        separate_child = self.make_child('Fictional separate dossier')
        other_practice = Organization.objects.create(name='Fictional other practice')
        Membership.objects.create(organization=other_practice, user=self.clinician, role='clinician')
        other_child = self.make_child('Fictional other practice dossier', other_practice)
        historical_date = timezone.now() - timedelta(days=1)
        preserved = [
            PrivacyRequest.objects.create(organization=self.org, requester=self.first,
                child=self.child, kind='export'),
            PrivacyRequest.objects.create(organization=self.org, requester=self.first,
                child=self.child, kind='erasure', status='resolved', resolved_at=historical_date,
                decision_reason='Original historical decision.'),
            PrivacyRequest.objects.create(organization=self.org, requester=self.first, kind='erasure'),
            PrivacyRequest.objects.create(organization=self.org, requester=self.first,
                child=separate_child, kind='erasure'),
            PrivacyRequest.objects.create(organization=other_practice, requester=self.first,
                child=other_child, kind='erasure'),
        ]
        preserved_ids = [item.pk for item in preserved]
        fields = ('organization_id', 'requester_id', 'kind', 'status', 'resolved_at', 'decision_reason')
        original = list(PrivacyRequest.objects.filter(pk__in=preserved_ids).order_by('pk').values_list(*fields))
        actor = self.account(self.clinician)
        for language in ('fr', 'en', 'ar'):
            self.assertContains(actor.get(self.resolution(first, language)), 'value="erase"')
        result = actor.post(self.resolution(first), self.erasure())
        self.assertRedirects(result, '/en/requests/', fetch_redirect_response=False)
        self.assertFalse(Child.objects.filter(pk=self.child.pk).exists())
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.requester_id, self.first.pk)
        self.assertEqual(second.requester_id, self.second.pk)
        self.assertEqual(first.decision_reason, self.erasure()['reason'])
        self.assertEqual(second.decision_reason, 'The dossier was erased while processing another request for the same profile.')
        self.assertEqual(first.resolved_at, second.resolved_at)
        self.assertIsNotNone(first.resolved_at)
        for item in (first, second):
            self.assertIsNone(item.child_id)
            self.assertEqual(item.status, 'resolved')
        self.assertEqual(list(PrivacyRequest.objects.filter(pk__in=preserved_ids).order_by('pk')
            .values_list(*fields)), original)
        self.assertEqual(list(PrivacyRequest.objects.filter(pk__in=preserved_ids[:3])
            .values_list('child_id', flat=True)), [None, None, None])
        self.assertTrue(PrivacyRequest.objects.filter(pk=preserved[3].pk, child=separate_child).exists())
        self.assertTrue(PrivacyRequest.objects.filter(pk=preserved[4].pk, child=other_child).exists())
        self.assertCountEqual(AuditEvent.objects.filter(organization=self.org, action='privacy.resolved')
            .values_list('object_id', 'actor_id', 'purpose_code'), [
                (str(first.pk), self.clinician.pk, 'data_rights'),
                (str(second.pk), self.clinician.pk, 'data_rights'),
            ])
        self.assertEqual(AuditEvent.objects.filter(action='child.erased', object_id=str(self.child.pk)).count(), 1)

    def test_export_decision_cannot_be_erasure_and_retention_only_resolves_selected_request(self):
        erasure = self.request_from(self.first)
        sibling = self.request_from(self.second)
        export = PrivacyRequest.objects.create(organization=self.org, requester=self.first,
            child=self.child, kind='export')
        clinician = self.account(self.clinician)
        owner = self.account(self.owner)
        for actor, item in ((clinician, export), (owner, erasure)):
            for language in ('fr', 'en', 'ar'):
                with self.subTest(request=item.kind, language=language):
                    response = actor.get(self.resolution(item, language))
                    self.assertContains(response, 'value="retain"')
                    self.assertNotContains(response, 'value="erase"')
                    self.assertNotContains(response, 'name="confirmation"')
        self.assertEqual(clinician.post(self.resolution(export), self.erasure()).status_code, 200)
        with self.assertRaises(ValidationError):
            resolve_privacy(self.clinician, export.pk, self.erasure())
        self.assertEqual(clinician.get(self.intake).status_code, 405)
        self.assertTrue(Child.objects.filter(pk=self.child.pk).exists())
        self.assertFalse(AuditEvent.objects.filter(action='child.erased').exists())
        self.assertTrue(PrivacyRequest.objects.filter(pk=export.pk, status='pending', child=self.child).exists())
        retained = owner.post(self.resolution(erasure), {'decision': 'retain', 'reason': 'Fictional decision to retain.'})
        self.assertRedirects(retained, '/en/requests/', fetch_redirect_response=False)
        self.assertTrue(PrivacyRequest.objects.filter(pk=erasure.pk, status='resolved', child=self.child).exists())
        self.assertTrue(PrivacyRequest.objects.filter(pk=sibling.pk, status='pending', child=self.child).exists())
        self.assertTrue(PrivacyRequest.objects.filter(pk=export.pk, status='pending', child=self.child).exists())

    def test_stale_actor_cannot_submit_or_erase(self):
        request = self.request_from(self.first)
        User.objects.filter(pk__in=[self.second.pk, self.clinician.pk]).update(is_active=False)
        self.assertTrue(self.second.is_active)
        self.assertTrue(self.clinician.is_active)
        with self.assertRaises(ValidationError):
            create_erasure_request(self.second, self.child)
        with self.assertRaises(ValidationError):
            resolve_privacy(self.clinician, request.pk, self.erasure())
        self.assertTrue(Child.objects.filter(pk=self.child.pk).exists())
        self.assertEqual(PrivacyRequest.objects.filter(status='pending').count(), 1)
        self.assertFalse(AuditEvent.objects.filter(action='child.erased').exists())

    def test_companion_audit_failure_rolls_back_erasure_and_all_decisions(self):
        selected = self.request_from(self.first)
        companion = self.request_from(self.second)

        def fail_after_companion_audit(actor, action, obj, organization):
            event = audit(actor, action, obj, organization)
            if action == 'privacy.resolved' and obj.pk == companion.pk:
                raise RuntimeError('Fictitious companion audit failure')
            return event

        with patch('core.services.audit', side_effect=fail_after_companion_audit):
            with self.assertRaisesRegex(RuntimeError, 'Fictitious companion audit failure'):
                resolve_privacy(self.clinician, selected.pk, self.erasure())
        self.assertTrue(Child.objects.filter(pk=self.child.pk).exists())
        self.assertEqual(FamilyLink.objects.filter(child=self.child, active=True).count(), 2)
        self.assertEqual(PrivacyRequest.objects.filter(child=self.child, status='pending',
            resolved_at__isnull=True, decision_reason='').count(), 2)
        self.assertFalse(AuditEvent.objects.filter(action__in=['child.erased', 'privacy.resolved']).exists())
        resolve_privacy(self.clinician, selected.pk, self.erasure())
        self.assertEqual(PrivacyRequest.objects.filter(child__isnull=True, status='resolved').count(), 2)


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
@override_settings(**SETTINGS)
class ConcurrentPrivacyErasureRequestsTests(PrivacyFixture, TransactionTestCase):
    def setUp(self):
        self.setup_practice()
        self.selected = self.request_from(self.first)
        self.clinician_client = self.account(self.clinician)
        self.caregiver_client = self.account(self.second)

    def worker(self, client, path, data, pid, connected):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '7s'")
                cursor.execute("SET statement_timeout = '12s'")
                cursor.execute('SELECT pg_backend_pid()')
                pid.append(cursor.fetchone()[0])
            connected.set()
            return client.post(path, data).status_code
        finally:
            connections.close_all()

    def race(self, action_to_hold, first_post, second_post):
        held, release = Event(), Event()
        first_connected, second_connected = Event(), Event()
        first_pid, second_pid = [], []

        def hold_after_audit(actor, action, obj, organization):
            event = audit(actor, action, obj, organization)
            if action == action_to_hold:
                held.set()
                if not release.wait(9):
                    raise RuntimeError('The competing privacy transaction never reached its lock.')
            return event

        with patch('core.services.audit', side_effect=hold_after_audit):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.worker, *first_post, first_pid, first_connected)
                try:
                    self.assertTrue(first_connected.wait(3))
                    self.assertTrue(held.wait(4))
                    second = pool.submit(self.worker, *second_post, second_pid, second_connected)
                    self.assertTrue(second_connected.wait(3))
                    with connection.cursor() as cursor:
                        deadline = monotonic() + 4
                        while monotonic() < deadline:
                            cursor.execute('SELECT %s = ANY(pg_blocking_pids(%s))', [first_pid[0], second_pid[0]])
                            if cursor.fetchone()[0]:
                                break
                            sleep(0.02)
                        else:
                            self.fail('The two actual requests did not contend for the same practice lock.')
                finally:
                    release.set()
                return first.result(timeout=12), second.result(timeout=12)

    def test_intake_wins_and_new_request_is_closed_with_erasure(self):
        statuses = self.race('privacy.requested', (self.caregiver_client, self.intake, {}),
            (self.clinician_client, self.resolution(self.selected), self.erasure()))
        self.assertEqual(statuses, (302, 302))
        self.assertEqual(PrivacyRequest.objects.filter(status='resolved', child__isnull=True).count(), 2)
        companion = PrivacyRequest.objects.get(requester=self.second)
        self.assertTrue(AuditEvent.objects.filter(action='privacy.resolved', object_id=str(companion.pk)).exists())
        self.assertFalse(Child.objects.filter(pk=self.child.pk).exists())

    def test_erasure_wins_and_queued_intake_cannot_insert_an_orphan(self):
        statuses = self.race('child.erased', (self.clinician_client, self.resolution(self.selected), self.erasure()),
            (self.caregiver_client, self.intake, {}))
        self.assertEqual(statuses, (302, 404))
        self.selected.refresh_from_db()
        self.assertEqual(self.selected.status, 'resolved')
        self.assertIsNone(self.selected.child_id)
        self.assertFalse(PrivacyRequest.objects.filter(requester=self.second).exists())
        self.assertFalse(AuditEvent.objects.filter(action='privacy.requested', actor=self.second).exists())
        self.assertFalse(Child.objects.filter(pk=self.child.pk).exists())
