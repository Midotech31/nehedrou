"""Scoped operator publishing changes on fictional accounts and disposable databases."""
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import CommandError, call_command
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django_otp.plugins.otp_totp.models import TOTPDevice

from catalog.integrity import integrity_scope
from catalog.models import EditorialGrant, Review, Variety
from catalog.services import allowed
from core.models import AuditEvent, Membership, User
from qualification.models import AvailabilityDecision, ReviewerCompetence, ReviewerCompetenceDecision
from qualification.services import has_competence, record_competence_decision


COMMAND = 'manage_editorial_publishing_access'


def install_fixtures(target):
    target.operator = User.objects.create_user('publishing-operator', 'publishing-operator@example.test',
                                               is_superuser=True, is_staff=True)
    target.account = User.objects.create_user('publishing-recipient', 'publishing-recipient@example.test')
    target.ordinary = User.objects.create_user('publishing-ordinary', 'publishing-ordinary@example.test')
    target.manager = User.objects.create_user('publishing-manager', 'publishing-manager@example.test')
    target.manager.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
    target.variety = Variety.objects.create(code='publishing-fr-fixture', language='fr', label='Fictional French scope')
    target.other_variety = Variety.objects.create(code='publishing-ar-fixture', language='ar', label='Fictional other scope')
    target.device = TOTPDevice.objects.create(user=target.account, name='fictional-confirmed', confirmed=True)


class CommandHelpers:
    def invoke(self, operation='grant', *, actor=None, account=None, variety=None, **options):
        output = io.StringIO()
        call_command(COMMAND, operation,
                     actor=(actor or self.operator).username,
                     account=(account or self.account).username,
                     variety=(variety or self.variety).code,
                     stdout=output, **options)
        return json.loads(output.getvalue())

    def apply_preview(self, preview, operation='grant', **options):
        return self.invoke(operation, apply=True, expect_plan=preview['plan_sha256'], **options)

    def snapshot(self):
        return {
            'grants': list(EditorialGrant.objects.order_by('pk').values()),
            'audits': list(AuditEvent.objects.order_by('pk').values()),
            'accounts': list(User.objects.order_by('pk').values('pk', 'is_active', 'is_staff', 'is_superuser')),
            'user_permissions': list(User.user_permissions.through.objects.order_by('pk').values()),
            'memberships': list(Membership.objects.order_by('pk').values()),
            'reviews': list(Review.objects.order_by('pk').values()),
            'competence_decisions': list(ReviewerCompetenceDecision.objects.order_by('pk').values()),
            'availability': list(AvailabilityDecision.objects.order_by('pk').values()),
        }

    def assert_audit(self, action):
        event = AuditEvent.objects.get(action=action)
        self.assertEqual(event.actor_id, self.operator.pk)
        self.assertEqual(event.actor_ref, str(self.operator.pk))
        self.assertEqual(event.object_id, f'{self.account.pk}:{self.variety.pk}')
        self.assertEqual(event.purpose_code, 'content_review')
        self.assertIsNone(event.organization_id)
        return event


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class PublishingAccessCommandTests(CommandHelpers, TestCase):
    @classmethod
    def setUpTestData(cls):
        install_fixtures(cls)

    def test_preview_is_stable_scoped_and_has_no_side_effects_or_secret_fields(self):
        before = self.snapshot()
        first = self.invoke()
        self.assertEqual(first, self.invoke())
        self.assertFalse(first['changed'])
        self.assertRegex(first['plan_sha256'], r'^[0-9a-f]{64}$')
        plan = first['plan']
        self.assertEqual(plan['operation'], 'grant')
        self.assertEqual(plan['actor_id'], str(self.operator.pk))
        self.assertEqual(plan['account_id'], str(self.account.pk))
        self.assertEqual(plan['variety_id'], str(self.variety.pk))
        self.assertEqual(plan['variety_code'], self.variety.code)
        self.assertFalse(plan['publishing_enabled'])
        self.assertIsNone(plan['grant_id'])
        self.assertLessEqual(set(plan), {'operation', 'actor_id', 'account_id', 'variety_id',
                                        'variety_code', 'publishing_enabled', 'grant_id', 'limited_capabilities'})
        self.assertEqual(self.snapshot(), before)

    def test_management_staff_or_scoped_publishing_permission_is_not_operator_authority(self):
        self.ordinary.is_staff = True
        self.ordinary.save(update_fields=['is_staff'])
        EditorialGrant.objects.create(user=self.ordinary, variety=self.variety, publish=True)
        before = self.snapshot()
        for actor in (self.ordinary, self.manager, self.account):
            with self.subTest(actor=actor.username), self.assertRaises(CommandError):
                self.invoke(actor=actor)
        self.assertEqual(self.snapshot(), before)

    def test_inactive_operator_cannot_preview_or_apply_an_existing_plan(self):
        preview = self.invoke()
        self.operator.is_active = False
        self.operator.save(update_fields=['is_active'])
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.invoke()
        with self.assertRaises(CommandError):
            self.apply_preview(preview)
        self.assertEqual(self.snapshot(), before)

    def test_missing_actor_account_or_variety_is_refused_without_creating_anything(self):
        before = self.snapshot()
        for overrides in ({'actor': 'unknown-operator'}, {'account': 'unknown-recipient'},
                          {'variety': 'unknown-variety'}):
            kwargs = {'actor': self.operator.username, 'account': self.account.username,
                      'variety': self.variety.code, **overrides}
            with self.subTest(overrides=overrides), self.assertRaises(CommandError):
                call_command(COMMAND, 'grant', stdout=io.StringIO(), **kwargs)
        self.assertEqual(self.snapshot(), before)

    def test_grant_rejects_self_global_admin_inactive_or_unconfirmed_account(self):
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.invoke(account=self.operator)
        self.assertEqual(self.snapshot(), before)
        self.account.is_active = False
        self.account.save(update_fields=['is_active'])
        with self.assertRaises(CommandError):
            self.invoke()
        self.account.is_active = True
        self.account.is_superuser = True
        self.account.save(update_fields=['is_active', 'is_superuser'])
        with self.assertRaises(CommandError):
            self.invoke()
        self.account.is_superuser = False
        self.account.save(update_fields=['is_superuser'])
        self.device.confirmed = False
        self.device.save(update_fields=['confirmed'])
        with self.assertRaises(CommandError):
            self.invoke()
        self.device.delete()
        with self.assertRaises(CommandError):
            self.invoke()
        self.assertFalse(EditorialGrant.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_apply_requires_the_exact_preview_hash_and_explicit_apply(self):
        preview = self.invoke()
        before = self.snapshot()
        for options in ({'apply': True}, {'apply': True, 'expect_plan': '0' * 64},
                        {'apply': True, 'expect_plan': 'invalid'}, {'expect_plan': preview['plan_sha256']}):
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.invoke(**options)
            self.assertEqual(self.snapshot(), before)

    def test_plan_cannot_be_reused_for_another_account_variety_or_operation(self):
        other = User.objects.create_user('other-publishing-recipient', 'other-publishing-recipient@example.test')
        TOTPDevice.objects.create(user=other, name='fictional-confirmed', confirmed=True)
        preview = self.invoke()
        before = self.snapshot()
        for operation, options in [('grant', {'account': other}), ('grant', {'variety': self.other_variety}),
                                   ('revoke', {})]:
            with self.subTest(operation=operation, options=options), self.assertRaises(CommandError):
                self.apply_preview(preview, operation, **options)
            self.assertEqual(self.snapshot(), before)

    def test_grant_creates_only_one_scoped_capability_with_a_stable_composite_audit(self):
        users_before = self.snapshot()['accounts']
        preview = self.invoke()
        result = self.apply_preview(preview)
        self.assertTrue(result['changed'])
        self.assertEqual(result['plan'], preview['plan'])
        grant = EditorialGrant.objects.get(user=self.account, variety=self.variety)
        self.assertEqual((grant.edit, grant.clinical_review, grant.linguistic_review, grant.publish),
                         (False, False, False, True))
        self.assertTrue(allowed(self.account, self.variety, 'publish'))
        self.assertFalse(allowed(self.account, self.other_variety, 'publish'))
        self.assertEqual(EditorialGrant.objects.count(), 1)
        self.assertEqual(self.snapshot()['accounts'], users_before)
        self.assertFalse(Membership.objects.exists())
        self.assertFalse(Review.objects.exists())
        self.assertFalse(ReviewerCompetence.objects.exists())
        self.assertFalse(AvailabilityDecision.objects.exists())
        self.assertEqual(AuditEvent.objects.count(), 1)
        self.assert_audit('catalog.publishing_access_granted')

    def test_existing_capabilities_grant_identity_and_other_variety_are_preserved(self):
        grant = EditorialGrant.objects.create(user=self.account, variety=self.variety,
                                              edit=True, clinical_review=True, linguistic_review=True)
        other = EditorialGrant.objects.create(user=self.account, variety=self.other_variety,
                                              edit=True, linguistic_review=True)
        other_before = EditorialGrant.objects.filter(pk=other.pk).values().get()
        preview = self.invoke()
        self.assertEqual(preview['plan']['grant_id'], str(grant.pk))
        self.apply_preview(preview)
        grant.refresh_from_db()
        self.assertEqual((grant.edit, grant.clinical_review, grant.linguistic_review, grant.publish),
                         (True, True, True, True))
        self.assertEqual(EditorialGrant.objects.filter(pk=other.pk).values().get(), other_before)
        self.assertEqual(EditorialGrant.objects.count(), 2)

    def test_repeated_refreshed_grant_or_revoke_is_a_noop_without_duplicate_audit(self):
        self.apply_preview(self.invoke())
        before = self.snapshot()
        refreshed = self.invoke()
        self.assertTrue(refreshed['plan']['publishing_enabled'])
        self.assertFalse(self.apply_preview(refreshed)['changed'])
        self.assertEqual(self.snapshot(), before)
        self.apply_preview(self.invoke('revoke'), 'revoke')
        before = self.snapshot()
        self.assertFalse(self.apply_preview(self.invoke('revoke'), 'revoke')['changed'])
        self.assertEqual(self.snapshot(), before)

    def test_grant_changes_invalidate_old_plan_without_a_second_mutation(self):
        preview = self.invoke()
        self.apply_preview(preview)
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.apply_preview(preview)
        self.assertEqual(self.snapshot(), before)

    def test_account_disabled_or_authenticator_unconfirmed_after_preview_blocks_apply(self):
        preview = self.invoke()
        self.account.is_active = False
        self.account.save(update_fields=['is_active'])
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.apply_preview(preview)
        self.assertEqual(self.snapshot(), before)
        self.account.is_active = True
        self.account.save(update_fields=['is_active'])
        TOTPDevice.objects.filter(pk=self.device.pk).update(confirmed=False)
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.apply_preview(preview)
        self.assertEqual(self.snapshot(), before)

    def test_revoke_deletes_the_last_grant_and_retains_a_resolvable_subject_scope(self):
        self.apply_preview(self.invoke())
        grant_id = EditorialGrant.objects.get(user=self.account, variety=self.variety).pk
        preview = self.invoke('revoke')
        self.assertEqual(preview['plan']['grant_id'], str(grant_id))
        self.assertTrue(self.apply_preview(preview, 'revoke')['changed'])
        self.assertFalse(EditorialGrant.objects.filter(pk=grant_id).exists())
        self.assertFalse(allowed(self.account, self.variety, 'publish'))
        self.assertFalse(EditorialGrant.objects.filter(user=self.account).exists())
        self.assert_audit('catalog.publishing_access_revoked')

    def test_revoke_works_when_account_is_inactive_without_mfa_and_preserves_limited_access(self):
        self.apply_preview(self.invoke())
        grant = EditorialGrant.objects.get(user=self.account, variety=self.variety)
        grant.edit = True
        grant.linguistic_review = True
        grant.save(update_fields=['edit', 'linguistic_review'])
        self.account.is_active = False
        self.account.save(update_fields=['is_active'])
        self.device.delete()
        self.assertTrue(self.apply_preview(self.invoke('revoke'), 'revoke')['changed'])
        grant.refresh_from_db()
        self.assertEqual((grant.publish, grant.edit, grant.clinical_review, grant.linguistic_review),
                         (False, True, False, True))
        self.assert_audit('catalog.publishing_access_revoked')

    def test_audit_failure_rolls_back_the_permission_change(self):
        preview = self.invoke()
        before = self.snapshot()
        with patch('catalog.publishing_access.audit', side_effect=RuntimeError('Fictional audit failure')):
            with self.assertRaises(RuntimeError):
                self.apply_preview(preview)
        self.assertEqual(self.snapshot(), before)

    def test_mutation_invalidates_an_existing_request_permission_cache(self):
        with integrity_scope():
            self.assertFalse(allowed(self.account, self.variety, 'publish'))
            self.apply_preview(self.invoke())
            self.assertTrue(allowed(self.account, self.variety, 'publish'))
            self.apply_preview(self.invoke('revoke'), 'revoke')
            self.assertFalse(allowed(self.account, self.variety, 'publish'))

    def test_publication_authority_can_verify_another_declaration_but_never_its_own(self):
        reviewer = User.objects.create_user('independent-reviewer', 'independent-reviewer@example.test')
        EditorialGrant.objects.create(user=reviewer, variety=self.variety, clinical_review=True)
        declaration = ReviewerCompetence.objects.create(
            user=reviewer, variety=self.variety, discipline='clinical',
            professional_role='Fictional clinician', experience='Fictional experience for this variety')
        own = ReviewerCompetence.objects.create(
            user=self.account, variety=self.variety, discipline='clinical',
            professional_role='Fictional publication lead', experience='Fictional experience to be checked independently')
        arguments = ('verified', 'Fictional independent identity and regional experience check.', date(2026, 1, 1))
        with self.assertRaises(PermissionDenied):
            record_competence_decision(self.account, declaration.pk, *arguments,
                                       expected_digest=declaration.fingerprint())
        self.apply_preview(self.invoke())
        with self.assertRaises(ValidationError):
            record_competence_decision(self.account, own.pk, *arguments, expected_digest=own.fingerprint())
        self.assertFalse(has_competence(self.account, self.variety, 'clinical'))
        record_competence_decision(self.account, declaration.pk, *arguments,
                                   expected_digest=declaration.fingerprint())
        self.assertTrue(has_competence(reviewer, self.variety, 'clinical'))
        self.apply_preview(self.invoke('revoke'), 'revoke')
        with self.assertRaises(PermissionDenied):
            record_competence_decision(self.account, declaration.pk, *arguments,
                                       expected_digest=declaration.fingerprint())
        self.assertEqual(ReviewerCompetenceDecision.objects.count(), 1)
        self.assertFalse(Review.objects.exists())
        self.assertFalse(AvailabilityDecision.objects.exists())


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks and independent connections.')
@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class PublishingAccessConcurrencyTests(CommandHelpers, TransactionTestCase):
    def setUp(self):
        install_fixtures(self)

    def worker(self, preview, start):
        connections.close_all()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8s'")
                cursor.execute("SET statement_timeout = '12s'")
            start.wait(timeout=5)
            try:
                return {'outcome': 'applied', 'report': self.apply_preview(preview)}
            except CommandError as error:
                return {'outcome': 'refused', 'stale_plan': 'plan changed' in str(error).lower()}
        finally:
            connections.close_all()

    def test_same_plan_race_grants_once_and_refuses_the_stale_second_application(self):
        preview = self.invoke()
        start = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, preview, start) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertCountEqual([result['outcome'] for result in results], ['applied', 'refused'])
        applied = next(result['report'] for result in results if result['outcome'] == 'applied')
        refused = next(result for result in results if result['outcome'] == 'refused')
        self.assertTrue(applied['changed'])
        self.assertTrue(refused['stale_plan'])
        grant = EditorialGrant.objects.get(user=self.account, variety=self.variety)
        self.assertEqual((grant.edit, grant.clinical_review, grant.linguistic_review, grant.publish),
                         (False, False, False, True))
        self.assertEqual(EditorialGrant.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 1)
        self.assert_audit('catalog.publishing_access_granted')
        self.assertFalse(Membership.objects.exists())
        self.assertFalse(ReviewerCompetenceDecision.objects.exists())
        self.assertFalse(AvailabilityDecision.objects.exists())
