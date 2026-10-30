"""Opening decisions use real scoped fictional targets and explicit human input."""
import uuid
from copy import deepcopy
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.translation import gettext as _
from catalog.models import Activity, EditorialGrant
from core.models import User, Organization, Membership, AuditEvent
from followup.models import ProbeDefinition
from .models import AvailabilityDecision
from .opening import record_decision, revoke_decision, target_key, target_snapshot
from .services import REQUIRED_EVIDENCE, availability_for
from .test_support import evidence_fixture, competence_fixture


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class OpeningDecisionTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(username='opening-actor', email='opening-actor@example.test')
        self.other = User.objects.create_user(username='opening-other', email='opening-other@example.test')
        self.family = User.objects.create_user(username='opening-family', email='opening-family@example.test')
        from catalog.models import Variety
        self.variety = Variety.objects.create(code='fr-opening', language='fr', label='Fictional opening variety')
        self.foreign_variety = Variety.objects.create(code='en-opening', language='en', label='Other fictional variety')
        competence_fixture(self.actor, self.variety, 'clinical')
        competence_fixture(self.other, self.variety, 'clinical')
        self.organization = Organization.objects.create(name='Fictional opening cabinet A')
        self.other_organization = Organization.objects.create(name='Fictional opening cabinet B')
        self.membership = Membership.objects.create(organization=self.organization, user=self.actor, role='clinician')
        Membership.objects.create(organization=self.other_organization, user=self.other, role='clinician')
        self.activity = self.activity_fixture('Fictional selected draft')
        self.documents = [evidence_fixture(self.variety, self.actor, category) for category in REQUIRED_EVIDENCE]
        self.path = reverse('qualification:availability')
        self.client.force_login(self.actor)

    def activity_fixture(self, title, **kwargs):
        values = dict(variety=self.variety, series=uuid.uuid4(), title=title, contrast='p/b', word_a='pa', word_b='ba',
            instructions={'fr':'Fictif', 'en':'Fictional', 'ar':'مثال وهمي'}, population='Fictional only', rights='Unqualified fixture', is_demo=False)
        values.update(kwargs)
        return Activity.objects.create(**values)

    def probe_fixture(self, organization=None, author=None, title='Fictional selected protocol'):
        item = {'id':'fictional-item', 'word':'pa', 'ipa':'/pa/', 'target_definition':'Fictional initial target',
            'target_occurrence_index':0, 'exposure_plan':'reserved', 'accepted_variants':[]}
        return ProbeDefinition.objects.create(variety=self.variety, organization=organization, authored_by=author or self.actor,
            title=title, protocol='Original fictional draft', task='picture_naming', target_phoneme='p',
            target_position='initial', target_scope={'position':'initial', 'context':'isolated_word'},
            items=[item], is_demo=False)

    def data(self, content=None, module='practice', **changes):
        content = content or self.activity
        data = {'target': target_key(module, content), 'expected_version': content.fingerprint(), 'status':'blocked',
            'scope':'Fictional scope explicitly entered', 'reason':'Fictional human reason', 'documents':[], 'acknowledge':'on'}
        data.update(changes)
        return data

    def service_data(self, status='blocked'):
        return {'status':status, 'scope':'Fictional scope', 'reason':'Fictional reason',
            'documents':self.documents if status == 'available' else []}

    def legacy(self, **changes):
        values = dict(module='practice', variety=self.variety, version='a'*64, status='blocked',
            scope='LEGACY-PRIVATE-SCOPE', reason='LEGACY-PRIVATE-REASON', decided_by=self.actor)
        values.update(changes)
        obj = AvailabilityDecision(**values)
        AvailabilityDecision.objects.bulk_create([obj])  # Simulate an unchanged pre-binding migration row.
        return obj

    def test_preparation_lists_real_scoped_content_and_creates_no_decision(self):
        demo = self.activity_fixture('DEMO-NOT-A-TARGET', is_demo=True)
        foreign = self.activity_fixture('OTHER-VARIETY-NOT-A-TARGET', variety=self.foreign_variety)
        response = self.client.get(self.path, {'target':target_key('practice', self.activity)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.activity.title)
        self.assertContains(response, self.activity.fingerprint())
        self.assertContains(response, reverse('editorial_detail', args=[self.activity.pk]))
        self.assertNotContains(response, demo.title)
        self.assertNotContains(response, foreign.title)
        self.assertFalse(AvailabilityDecision.objects.exists())
        self.assertFalse(response.context['form'].initial.get('acknowledge', False))

    def test_model_rejects_orphan_hash_even_with_five_usable_documents(self):
        from .services import evidence_snapshot
        with self.assertRaises(ValidationError):
            AvailabilityDecision.objects.create(module='practice', variety=self.variety, version='0'*64,
                status='available', scope='Fictional orphan', reason='Fictional attempt', decided_by=self.actor,
                evidence=evidence_snapshot(self.documents))
        self.assertFalse(AvailabilityDecision.objects.exists())

    def test_post_derives_module_variety_hash_and_preserves_immutable_identity(self):
        data = self.data()
        data.update(module='production_followup', variety=str(self.foreign_variety.pk), version='0'*64)
        response = self.client.post(self.path, data)
        self.assertEqual(response.status_code, 302)
        decision = AvailabilityDecision.objects.get()
        self.assertEqual((decision.module, decision.variety_id, decision.version),
            ('practice', self.variety.pk, self.activity.fingerprint()))
        self.assertEqual(decision.target_snapshot, target_snapshot('practice', self.activity))
        self.assertEqual(decision.evidence, {})
        decision.reason = 'Silent revision'
        with self.assertRaises(ValidationError):
            decision.save()

    def test_available_before_publication_requires_human_input_and_does_not_bypass_content_gates(self):
        response = self.client.post(self.path, self.data(status='available', documents=[str(doc.pk) for doc in self.documents]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(availability_for('practice', self.variety, self.activity.fingerprint())['available'])
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.state, 'draft')
        self.assertFalse(self.activity.usable)
        self.assertEqual(self.activity.reviews.count(), 0)
        data = self.data(acknowledge='')
        self.assertEqual(self.client.post(self.path, data).status_code, 200)
        self.assertEqual(AvailabilityDecision.objects.count(), 1)

    def test_changed_content_conflicts_without_record_and_keeps_user_reason(self):
        old = self.data()
        self.activity.title = 'Revised fictional draft'
        self.activity.save()
        response = self.client.post(self.path, old)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, old['reason'], status_code=409)
        self.assertContains(response, self.activity.fingerprint(), status_code=409)
        self.assertFalse(AvailabilityDecision.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action__startswith='qualification.availability_').exists())

    def test_wrong_variety_documents_demo_and_inaccessible_targets_cannot_be_submitted(self):
        wrong = evidence_fixture(self.foreign_variety, self.actor, 'rights')
        response = self.client.post(self.path, self.data(documents=[str(wrong.pk)]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('documents', response.context['form'].errors)
        for content in [self.activity_fixture('Hidden other variety', variety=self.foreign_variety),
                        self.activity_fixture('Hidden demo', is_demo=True)]:
            self.assertEqual(self.client.post(self.path, self.data(content)).status_code, 200)
        self.assertFalse(AvailabilityDecision.objects.exists())

    def test_real_protocol_binds_to_followup_and_links_its_version(self):
        probe = self.probe_fixture()
        response = self.client.post(self.path, self.data(probe, module='production_followup'))
        self.assertEqual(response.status_code, 302)
        decision = AvailabilityDecision.objects.get()
        self.assertEqual(decision.module, 'production_followup')
        self.assertEqual(decision.target_snapshot['id'], str(probe.pk))
        self.assertContains(self.client.get(self.path), reverse('followup:definition_detail', args=[probe.pk]))

    def test_other_cabinet_cannot_list_prepare_or_revoke_private_protocol_decision(self):
        probe = self.probe_fixture(self.organization, title='PRIVATE-CABINET-TARGET-TITLE')
        record = record_decision(self.actor, target_key('production_followup', probe), probe.fingerprint(), self.service_data())
        record_reason = record.reason
        self.client.force_login(self.other)
        response = self.client.get(self.path)
        for text in [probe.title, self.organization.name, record_reason, str(record.pk), str(probe.pk), record.scope]:
            self.assertNotContains(response, text)
        self.assertEqual(self.client.post(self.path, self.data(probe, module='production_followup')).status_code, 200)
        revoke_path = reverse('qualification:availability_revoke', args=[record.pk])
        self.assertEqual(self.client.post(revoke_path, {'reason':'Other cabinet withdrawal'}).status_code, 404)
        with self.assertRaises(PermissionDenied):
            revoke_decision(self.other, record.pk, 'Forbidden direct service attempt')
        with self.assertRaises(ValidationError):
            AvailabilityDecision.objects.create(module=record.module, variety=record.variety, version=record.version,
                status='revoked', scope=record.scope, reason='Forbidden direct model attempt', decided_by=self.other,
                target_snapshot=deepcopy(record.target_snapshot))
        self.assertEqual(AvailabilityDecision.objects.count(), 1)

    def test_private_cabinet_access_is_rechecked_after_membership_revocation(self):
        probe = self.probe_fixture(self.organization)
        record = record_decision(self.actor, target_key('production_followup', probe), probe.fingerprint(), self.service_data())
        self.membership.active = False
        self.membership.save()
        self.assertNotContains(self.client.get(self.path), probe.title)
        self.assertEqual(self.client.post(reverse('qualification:availability_revoke', args=[record.pk]), {'reason':'Late withdrawal'}).status_code, 404)

    def test_deleted_private_target_retains_history_and_can_be_revoked_in_its_cabinet(self):
        probe = self.probe_fixture(self.organization)
        record = record_decision(self.actor, target_key('production_followup', probe), probe.fingerprint(), self.service_data())
        snapshot, digest = deepcopy(record.target_snapshot), record.version
        probe.delete()
        response = self.client.get(self.path)
        self.assertContains(response, _('Historical content target unavailable'))
        self.assertContains(response, digest)
        self.assertEqual(self.client.post(reverse('qualification:availability_revoke', args=[record.pk]), {'reason':'Fictional target removed'}).status_code, 302)
        latest = AvailabilityDecision.objects.first()
        self.assertEqual((latest.status, latest.version, latest.target_snapshot), ('revoked', digest, snapshot))
        record.refresh_from_db()
        self.assertEqual(record.status, 'blocked')

    def test_legacy_unknown_target_is_not_backfilled_and_only_owner_can_read_or_revoke(self):
        legacy = self.legacy()
        response = self.client.get(self.path)
        self.assertContains(response, _('Historical content target unavailable'))
        self.assertContains(response, legacy.version)
        self.client.force_login(self.other)
        response = self.client.get(self.path)
        self.assertNotContains(response, legacy.reason)
        self.assertNotContains(response, legacy.scope)
        self.assertNotContains(response, str(legacy.pk))
        self.assertEqual(self.client.post(reverse('qualification:availability_revoke', args=[legacy.pk]), {'reason':'Forbidden'}).status_code, 404)
        self.client.force_login(self.actor)
        self.assertEqual(self.client.post(reverse('qualification:availability_revoke', args=[legacy.pk]), {'reason':'Fictional legacy withdrawal'}).status_code, 302)
        self.assertEqual(AvailabilityDecision.objects.first().target_snapshot, {})
        legacy.refresh_from_db()
        self.assertEqual((legacy.version, legacy.target_snapshot), ('a'*64, {}))

    def test_changed_or_withdrawn_target_can_still_be_revoked_without_rewriting_old_hash(self):
        record = record_decision(self.actor, target_key('practice', self.activity), self.activity.fingerprint(), self.service_data())
        digest = record.version
        self.activity.title = 'Changed after historical decision'
        self.activity.state = 'withdrawn'
        self.activity.save()
        with self.assertRaises(ValidationError):
            record_decision(self.actor, target_key('practice', self.activity), self.activity.fingerprint(), self.service_data('available'))
        revoked = revoke_decision(self.actor, record.pk, 'Fictional withdrawal of old exact scope')
        self.assertEqual(revoked.version, digest)
        self.assertEqual(revoked.target_snapshot, record.target_snapshot)

    def test_nonpublisher_and_noneditor_do_not_gain_write_access(self):
        EditorialGrant.objects.filter(user=self.actor, variety=self.variety).update(publish=False)
        self.assertEqual(self.client.post(self.path, self.data()).status_code, 403)
        self.client.force_login(self.family)
        response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('decisions', response.context)
        self.assertEqual(self.client.post(self.path, self.data()).status_code, 403)

    def test_legacy_owner_lost_then_restored_publishing_authority_rechecks_withdrawal(self):
        legacy = self.legacy()
        grant = EditorialGrant.objects.get(user=self.actor, variety=self.variety)
        grant.publish = False
        grant.save()
        with self.assertRaises(PermissionDenied):
            revoke_decision(self.actor, legacy.pk, 'Fictional withdrawn authority')
        grant.publish = True
        grant.save()
        revoked = revoke_decision(self.actor, legacy.pk, 'Fictional restored authority withdrawal')
        self.assertEqual((revoked.version, revoked.target_snapshot, revoked.status), (legacy.version, {}, 'revoked'))
