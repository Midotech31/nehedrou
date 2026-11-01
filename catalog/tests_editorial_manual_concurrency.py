"""Real PostgreSQL issuance races; all recipients and links are fictional."""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.db.models.query import QuerySet
from django.test import TransactionTestCase, override_settings

from catalog import editorial_access
from catalog.editorial_access import (
    accept_editorial_access_invitation, issue_manual_editorial_access_invitation,
    revoke_editorial_capability,
)
from catalog.models import EditorialAccessInvitation, EditorialGrant, Variety
from core.models import AuditEvent, Membership, User


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL uniqueness and row locks.')
@override_settings(DEMO_MODE=False, DEBUG=False, MFA_REQUIRED=False,
    EMAIL_BACKEND='core.email_backends.DisabledEmailBackend',
    LANGUAGE_CODE='en', PUBLIC_ORIGIN='https://editorial.example',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ManualEditorialHandoffConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.manager = User.objects.create_user('concurrent-manual-manager', 'concurrent-manager@example.test')
        self.manager.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        self.variety = Variety.objects.create(code='manual-race-fr', language='fr', label='Fictional race French')
        self.other_variety = Variety.objects.create(code='manual-race-ar', language='ar', label='Fictional race Arabic')

    def worker(self, identifier, variety_id, start, email='concurrent-reviewer@example.test'):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
            actor = User.objects.get(pk=self.manager.pk)
            variety = Variety.objects.get(pk=variety_id)
            start.wait(timeout=5)
            try:
                invitation, token = issue_manual_editorial_access_invitation(
                    actor, email, variety, 'clinical_review', identifier)
                return {'outcome': 'accepted', 'id': invitation.pk,
                        'variety': invitation.variety_id, 'token': token}
            except ValidationError:
                return {'outcome': 'refused', 'variety': variety_id}
        finally:
            connections.close_all()

    def prior(self, variety):
        invitation, _token = EditorialAccessInvitation.issue(
            'concurrent-reviewer@example.test', variety, 'clinical_review', self.manager)
        return invitation

    def test_simultaneous_same_post_issues_one_link_and_replay_does_not_revoke_it(self):
        previous = self.prior(self.variety)
        identifier = uuid.uuid4()
        start = threading.Barrier(2)
        with patch('catalog.editorial_access.send_mail') as send:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.worker, identifier, self.variety.pk, start) for _ in range(2)]
                results = [future.result(timeout=18) for future in futures]
        send.assert_not_called()
        self.assertEqual([result['outcome'] for result in results], ['accepted', 'accepted'])
        self.assertEqual([result['id'] for result in results], [identifier, identifier])
        self.assertEqual(sum(bool(result['token']) for result in results), 1)
        self.assertEqual(EditorialAccessInvitation.objects.count(), 2)
        invitation = EditorialAccessInvitation.objects.get(pk=identifier)
        self.assertTrue(invitation.available)
        previous.refresh_from_db()
        self.assertTrue(previous.revoked)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.editorial_invitation_created').count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.editorial_invitation_revoked').count(), 1)
        self.assertFalse(EditorialGrant.objects.exists())
        self.assertFalse(Membership.objects.exists())
        self.assertEqual(User.objects.count(), 1)

    def test_cross_variety_primary_key_collision_rolls_back_losing_revocations(self):
        previous = {variety.pk: self.prior(variety) for variety in (self.variety, self.other_variety)}
        before = {key: EditorialAccessInvitation.objects.values().get(pk=value.pk)
                  for key, value in previous.items()}
        identifier = uuid.uuid4()
        start = threading.Barrier(2)
        before_insert = threading.Barrier(2)
        collisions = []
        original_save_table = EditorialAccessInvitation._save_table

        def save_table(invitation, *args, **kwargs):
            # Both scopes passed existence/validation checks before either INSERT.
            if invitation.pk == identifier and invitation._state.adding:
                before_insert.wait(timeout=5)
            try:
                return original_save_table(invitation, *args, **kwargs)
            except IntegrityError:
                collisions.append(invitation.variety_id)
                raise

        with patch.object(EditorialAccessInvitation, '_save_table', save_table), \
                patch('catalog.editorial_access.send_mail') as send:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.worker, identifier, variety.pk, start)
                           for variety in (self.variety, self.other_variety)]
                results = [future.result(timeout=18) for future in futures]
        send.assert_not_called()
        self.assertCountEqual([result['outcome'] for result in results], ['accepted', 'refused'])
        self.assertEqual(len(collisions), 1, 'The losing INSERT must hit a real PostgreSQL unique constraint.')
        winner = next(result for result in results if result['outcome'] == 'accepted')
        loser = next(result for result in results if result['outcome'] == 'refused')
        self.assertEqual(collisions, [loser['variety']])
        created = EditorialAccessInvitation.objects.get(pk=identifier)
        self.assertEqual(created.variety_id, winner['variety'])
        self.assertTrue(created.available)
        self.assertTrue(winner['token'])
        kept = previous[loser['variety']]
        self.assertEqual(EditorialAccessInvitation.objects.values().get(pk=kept.pk), before[loser['variety']])
        revoked = previous[winner['variety']]
        revoked.refresh_from_db()
        self.assertTrue(revoked.revoked)
        self.assertEqual(EditorialAccessInvitation.objects.count(), 3)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.editorial_invitation_created').count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.editorial_invitation_revoked').count(), 1)
        self.assertFalse(EditorialGrant.objects.exists())
        self.assertFalse(Membership.objects.exists())

    def test_distinct_explicit_creations_serialize_the_same_triplet(self):
        identifiers = (uuid.uuid4(), uuid.uuid4())
        start = threading.Barrier(2)
        with patch('catalog.editorial_access.send_mail') as send:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.worker, identifier, self.variety.pk, start)
                           for identifier in identifiers]
                results = [future.result(timeout=18) for future in futures]
        send.assert_not_called()
        self.assertEqual([result['outcome'] for result in results], ['accepted', 'accepted'])
        self.assertTrue(all(result['token'] for result in results))
        self.assertEqual(EditorialAccessInvitation.objects.filter(pk__in=identifiers).count(), 2)
        self.assertEqual(EditorialAccessInvitation.objects.filter(revoked=False, used_at__isnull=True).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.editorial_invitation_created').count(), 2)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.editorial_invitation_revoked').count(), 1)


    def service_worker(self, operation, pids, name, ready):
        """Run the real service on its own bounded PostgreSQL connection."""
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
                cursor.execute('SELECT pg_backend_pid()')
                pids[name] = cursor.fetchone()[0]
            ready.set()
            try:
                return 'accepted', operation()
            except ValidationError:
                return 'refused', None
        finally:
            connections.close_all()

    def assert_blocked_by(self, pids, waiting, holding):
        """Observe the actual lock edge, rather than assume timing from a sleep."""
        deadline = time.monotonic() + 4
        with connection.cursor() as cursor:
            while time.monotonic() < deadline:
                cursor.execute('SELECT %s = ANY(pg_blocking_pids(%s))',
                               [pids[holding], pids[waiting]])
                if cursor.fetchone()[0]:
                    return
                time.sleep(0.01)
        self.fail('%s did not wait for the real PostgreSQL lock held by %s.' % (waiting, holding))

    def manual_recipient(self, *, manager=False):
        recipient = User.objects.create_user('manual-lock-recipient', 'manual-lock-recipient@example.test')
        if manager:
            recipient.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        invitation, token = issue_manual_editorial_access_invitation(
            self.manager, recipient.email, self.variety, 'clinical_review', uuid.uuid4())
        return recipient, invitation, token

    def test_acceptance_before_replacement_serializes_without_deadlock(self):
        recipient, invitation, token = self.manual_recipient()
        self.assertFalse(EditorialGrant.objects.filter(user=recipient).exists())
        replacement_id = uuid.uuid4()
        paused = threading.Event()
        release = threading.Event()
        pids = {}
        accept_ready, issue_ready = threading.Event(), threading.Event()
        original_get_or_create = QuerySet.get_or_create

        def get_or_create(queryset, *args, **kwargs):
            if queryset.model is EditorialGrant:
                paused.set()
                if not release.wait(8):
                    raise AssertionError('Acceptance pause was not released.')
            return original_get_or_create(queryset, *args, **kwargs)

        with patch.object(QuerySet, 'get_or_create', get_or_create):
            with ThreadPoolExecutor(max_workers=2) as pool:
                accepting = pool.submit(self.service_worker,
                    lambda: accept_editorial_access_invitation(recipient, token),
                    pids, 'accept', accept_ready)
                try:
                    self.assertTrue(accept_ready.wait(4))
                    self.assertTrue(paused.wait(4), 'Acceptance must hold its locks before replacement starts.')
                    issuing = pool.submit(self.service_worker,
                        lambda: issue_manual_editorial_access_invitation(
                            self.manager, recipient.email, self.variety, 'clinical_review', replacement_id),
                        pids, 'issue', issue_ready)
                    self.assertTrue(issue_ready.wait(4))
                    self.assert_blocked_by(pids, 'issue', 'accept')
                finally:
                    release.set()
                self.assertEqual(accepting.result(timeout=15)[0], 'accepted')
                self.assertEqual(issuing.result(timeout=15)[0], 'refused')
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)
        self.assertFalse(invitation.revoked)
        self.assertFalse(EditorialAccessInvitation.objects.filter(pk=replacement_id).exists())
        self.assertEqual(EditorialAccessInvitation.objects.count(), 1)
        grant = EditorialGrant.objects.get(user=recipient, variety=self.variety)
        self.assertTrue(grant.clinical_review)
        self.assertFalse(grant.edit or grant.linguistic_review or grant.publish)

    def test_manager_revocation_audit_can_commit_while_acceptance_waits_for_grant(self):
        recipient, invitation, token = self.manual_recipient(manager=True)
        grant = EditorialGrant.objects.create(user=recipient, variety=self.variety, edit=True)
        paused = threading.Event()
        release = threading.Event()
        pids = {}
        revoke_ready, accept_ready = threading.Event(), threading.Event()
        original_audit = editorial_access.audit

        def audit(actor, action, obj, *args, **kwargs):
            if action == 'catalog.editorial_access_revoked' and obj.pk == grant.pk:
                paused.set()
                if not release.wait(8):
                    raise AssertionError('Revocation audit pause was not released.')
            return original_audit(actor, action, obj, *args, **kwargs)

        with patch('catalog.editorial_access.audit', audit):
            with ThreadPoolExecutor(max_workers=2) as pool:
                revoking = pool.submit(self.service_worker,
                    lambda: revoke_editorial_capability(recipient, grant.pk, 'edit'),
                    pids, 'revoke', revoke_ready)
                try:
                    self.assertTrue(revoke_ready.wait(4))
                    self.assertTrue(paused.wait(4), 'Revocation must hold the real grant row lock.')
                    accepting = pool.submit(self.service_worker,
                        lambda: accept_editorial_access_invitation(recipient, token),
                        pids, 'accept', accept_ready)
                    self.assertTrue(accept_ready.wait(4))
                    self.assert_blocked_by(pids, 'accept', 'revoke')
                finally:
                    release.set()
                self.assertEqual(revoking.result(timeout=15)[0], 'accepted')
                self.assertEqual(accepting.result(timeout=15)[0], 'accepted')
        final_grant = EditorialGrant.objects.get(user=recipient, variety=self.variety)
        self.assertFalse(final_grant.edit or final_grant.linguistic_review or final_grant.publish)
        self.assertTrue(final_grant.clinical_review)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.used_at)
        self.assertFalse(invitation.revoked)
        self.assertEqual(AuditEvent.objects.filter(
            actor=recipient, action='catalog.editorial_access_revoked').count(), 1)
        self.assertEqual(AuditEvent.objects.filter(
            actor=recipient, action='catalog.editorial_invitation_accepted').count(), 1)

    def test_replacement_before_acceptance_revokes_old_token_without_creating_grant(self):
        recipient, invitation, token = self.manual_recipient()
        self.assertFalse(EditorialGrant.objects.filter(user=recipient).exists())
        replacement_id = uuid.uuid4()
        inserted = threading.Event()
        release = threading.Event()
        pids = {}
        issue_ready, accept_ready = threading.Event(), threading.Event()
        original_issue = EditorialAccessInvitation.issue

        def issue(model, *args, **kwargs):
            result = original_issue(*args, **kwargs)
            if result[0].pk == replacement_id:
                inserted.set()
                if not release.wait(8):
                    raise AssertionError('Replacement insertion pause was not released.')
            return result

        with patch.object(EditorialAccessInvitation, 'issue', classmethod(issue)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                issuing = pool.submit(self.service_worker,
                    lambda: issue_manual_editorial_access_invitation(
                        self.manager, recipient.email, self.variety, 'clinical_review', replacement_id),
                    pids, 'issue', issue_ready)
                try:
                    self.assertTrue(issue_ready.wait(4))
                    self.assertTrue(inserted.wait(4), 'Replacement must really be inserted while holding its variety lock.')
                    accepting = pool.submit(self.service_worker,
                        lambda: accept_editorial_access_invitation(recipient, token),
                        pids, 'accept', accept_ready)
                    self.assertTrue(accept_ready.wait(4))
                    self.assert_blocked_by(pids, 'accept', 'issue')
                finally:
                    release.set()
                self.assertEqual(issuing.result(timeout=15)[0], 'accepted')
                self.assertEqual(accepting.result(timeout=15)[0], 'refused')
        invitation.refresh_from_db()
        self.assertTrue(invitation.revoked)
        self.assertIsNone(invitation.used_at)
        self.assertFalse(EditorialGrant.objects.filter(user=recipient).exists())
        self.assertEqual(EditorialAccessInvitation.objects.count(), 2)
        self.assertTrue(EditorialAccessInvitation.objects.get(pk=replacement_id).available)
        self.assertFalse(AuditEvent.objects.filter(action='catalog.editorial_invitation_accepted').exists())

    def test_acceptance_waits_for_real_account_deactivation_then_refuses(self):
        recipient, invitation, token = self.manual_recipient()
        pids = {}
        accept_ready = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                User.objects.filter(pk=recipient.pk).update(is_active=False)
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pids['deactivate'] = cursor.fetchone()[0]
                accepting = pool.submit(self.service_worker,
                    lambda: accept_editorial_access_invitation(recipient, token),
                    pids, 'accept', accept_ready)
                self.assertTrue(accept_ready.wait(4))
                self.assert_blocked_by(pids, 'accept', 'deactivate')
            self.assertEqual(accepting.result(timeout=15)[0], 'refused')
        recipient.refresh_from_db()
        invitation.refresh_from_db()
        self.assertFalse(recipient.is_active)
        self.assertIsNone(invitation.used_at)
        self.assertFalse(invitation.revoked)
        self.assertFalse(EditorialGrant.objects.filter(user=recipient).exists())
        self.assertFalse(AuditEvent.objects.filter(action='catalog.editorial_invitation_accepted').exists())
