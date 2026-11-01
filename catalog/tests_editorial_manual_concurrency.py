"""Real PostgreSQL issuance races; all recipients and links are fictional."""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections
from django.test import TransactionTestCase, override_settings

from catalog.editorial_access import issue_manual_editorial_access_invitation
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
