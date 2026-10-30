"""An old process may omit the additive target field during a rolling deployment."""
import uuid
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from catalog.models import EditorialGrant, Variety
from core.models import User
from .models import AvailabilityDecision


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LegacyOpeningInsertTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(username='legacy-sql-actor', email='legacy-sql-actor@example.test')
        self.other = User.objects.create_user(username='legacy-sql-other', email='legacy-sql-other@example.test')
        self.variety = Variety.objects.create(code='fr-legacy-sql', language='fr', label='Fictional legacy SQL variety')
        for user in [self.actor, self.other]:
            EditorialGrant.objects.create(user=user, variety=self.variety, edit=True, publish=True)

    def old_insert(self):
        reference = uuid.uuid4()
        # Deliberately the pre-0003 column set: no model default and no target_snapshot.
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO qualification_availabilitydecision '
                '(id,module,variety_id,version,status,scope,reason,evidence,decided_by_id,created_at) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                [reference.hex, 'practice', self.variety.pk.hex, 'b'*64, 'blocked',
                 'Fictional old-process scope', 'Fictional old-process reason', '{}', self.actor.pk, timezone.now()])
        return AvailabilityDecision.objects.get(pk=reference)

    def test_old_column_insert_gets_empty_database_default_and_current_read_preserves_raw_history(self):
        decision = self.old_insert()
        self.assertEqual(decision.target_snapshot, {})
        self.assertEqual(decision.version, 'b'*64)
        self.client.force_login(self.actor)
        response = self.client.get(reverse('qualification:availability'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, _('Historical content target unavailable'))
        self.assertContains(response, decision.scope)
        self.assertContains(response, decision.reason)
        decision.refresh_from_db()
        self.assertEqual(decision.target_snapshot, {})  # Reading never infers provenance.
        self.assertEqual(AvailabilityDecision.objects.count(), 1)

    def test_old_insert_retains_legacy_owner_isolation_and_owner_can_append_withdrawal(self):
        decision = self.old_insert()
        path = reverse('qualification:availability_revoke', args=[decision.pk])
        self.client.force_login(self.other)
        response = self.client.get(reverse('qualification:availability'))
        self.assertNotContains(response, decision.scope)
        self.assertNotContains(response, decision.reason)
        self.assertNotContains(response, str(decision.pk))
        self.assertEqual(self.client.post(path, {'reason':'Fictional forbidden withdrawal'}).status_code, 404)
        self.client.force_login(self.actor)
        self.assertEqual(self.client.post(path, {'reason':'Fictional owner withdrawal'}).status_code, 302)
        withdrawal = AvailabilityDecision.objects.first()
        self.assertEqual((withdrawal.status, withdrawal.version, withdrawal.target_snapshot), ('revoked', 'b'*64, {}))
        decision.refresh_from_db()
        self.assertEqual((decision.status, decision.target_snapshot), ('blocked', {}))

    def test_new_instance_defaults_are_separate_empty_metadata_without_inferred_decisions(self):
        first, second = AvailabilityDecision(), AvailabilityDecision()
        self.assertEqual((first.target_snapshot, second.target_snapshot), ({}, {}))
        first.target_snapshot['local-test-only'] = 'Not a qualification or human review'
        self.assertEqual(second.target_snapshot, {})
        self.assertFalse(AvailabilityDecision.objects.exists())
