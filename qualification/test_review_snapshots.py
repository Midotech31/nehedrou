"""Exact-content review contracts; fictional changes requests confer no approval."""
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import Activity, EditorialGrant, Variety
from catalog.integrity import integrity_scope
from catalog.services import allowed, review_version, transition
from core.models import AuditEvent, User
from followup.models import ProbeDefinition
from followup.services import review_definition, transition_definition, update_definition
from .models import LexicalCandidate, LexicalPack
from .services import change_pack_state, review_pack


class ReviewSnapshotContract:
    form_key = 'form'

    def setUp(self):
        self.variety = Variety.objects.create(code='fr-snapshot-test', language='fr', label='Fictional test variety')
        self.actor = User.objects.create_user(username='fictional-reviewer', email='reviewer@fictional.example')
        EditorialGrant.objects.create(user=self.actor, variety=self.variety, edit=True, clinical_review=True)
        self.client.force_login(self.actor)
        self.content = self.create_content()

    def payload(self, digest):
        return {'expected_digest': digest, 'kind': 'clinical', 'note': 'Fictional changes request; no clinical approval.'}

    def test_stale_get_after_draft_edit_and_resubmission_records_no_review_or_audit(self):
        opened = self.client.get(self.path)
        self.assertEqual(opened.status_code, 200)
        displayed_digest = opened.context[self.form_key]['expected_digest'].value()
        self.assertEqual(displayed_digest, self.content.fingerprint())
        self.revise_and_resubmit()
        self.content.refresh_from_db()
        self.assertNotEqual(displayed_digest, self.content.fingerprint())
        audit_count = AuditEvent.objects.count()

        stale = self.client.post(self.path, self.payload(displayed_digest))

        self.assertEqual(stale.status_code, 200)
        self.assertTrue(stale.context['review_snapshot_changed'])
        self.assertEqual(stale.context[self.form_key]['expected_digest'].value(), displayed_digest)
        self.assertContains(stale, 'Reload current content')
        self.assertFalse(self.content.reviews.exists())
        self.assertEqual(AuditEvent.objects.count(), audit_count)

    def test_missing_digest_is_required_and_records_no_review_or_audit(self):
        payload = self.payload(self.content.fingerprint())
        del payload['expected_digest']
        audit_count = AuditEvent.objects.count()

        response = self.client.post(self.path, payload)

        self.assertEqual(response.status_code, 200)
        self.assertIn('expected_digest', response.context[self.form_key].errors)
        self.assertFalse(self.content.reviews.exists())
        self.assertEqual(AuditEvent.objects.count(), audit_count)

    def test_reloaded_current_content_can_receive_a_legitimate_changes_request(self):
        self.revise_and_resubmit()
        self.content.refresh_from_db()
        reloaded = self.client.get(self.path)
        digest = reloaded.context[self.form_key]['expected_digest'].value()
        audit_count = AuditEvent.objects.count()

        accepted = self.client.post(self.path, self.payload(digest))

        self.assertEqual(accepted.status_code, 302)
        review = self.content.reviews.get()
        self.assertFalse(review.approved)
        self.assertEqual(review.content_digest, self.content.fingerprint())
        self.assertEqual(AuditEvent.objects.count(), audit_count + 1)

    def test_service_refetches_content_and_refuses_a_stale_snapshot_without_audit(self):
        digest = self.content.fingerprint()
        self.revise_and_resubmit()
        audit_count = AuditEvent.objects.count()

        with self.assertRaisesMessage(ValidationError, 'This content changed.'):
            self.submit_review(digest)

        self.assertFalse(self.content.reviews.exists())
        self.assertEqual(AuditEvent.objects.count(), audit_count)

    def test_service_discards_prelock_permission_cache(self):
        digest = self.content.fingerprint()
        audit_count = AuditEvent.objects.count()
        with integrity_scope():
            self.assertTrue(allowed(self.actor, self.variety, 'clinical_review'))
            EditorialGrant.objects.filter(user=self.actor, variety=self.variety).update(clinical_review=False)
            with self.assertRaises(PermissionDenied):
                self.submit_review(digest)
        self.assertFalse(self.content.reviews.exists())
        self.assertEqual(AuditEvent.objects.count(), audit_count)


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, LANGUAGE_CODE='en')
class ActivityReviewSnapshotTests(ReviewSnapshotContract, TestCase):
    def create_content(self):
        activity = Activity.objects.create(variety=self.variety, series=uuid.uuid4(),
            title='Fictional unapproved activity', contrast='p/b', word_a='pa', word_b='ba',
            instructions={'en': 'Fictional illustration only; no clinical approval.'}, is_demo=True)
        self.path = reverse('editorial_detail', args=[activity.pk])
        return transition(self.actor, activity.pk, 'review')

    def revise_and_resubmit(self):
        activity = transition(self.actor, self.content.pk, 'draft')
        activity.word_a = 'Fictional revised word'
        activity.save()
        transition(self.actor, activity.pk, 'review')

    def submit_review(self, digest):
        return review_version(self.actor, self.content, 'clinical', False, 'Fictional changes request', expected_digest=digest)


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, LANGUAGE_CODE='en')
class ProbeReviewSnapshotTests(ReviewSnapshotContract, TestCase):
    form_key = 'review_form'

    def create_content(self):
        probe = ProbeDefinition.objects.create(variety=self.variety, title='Fictional unapproved protocol',
            protocol='Fictional procedure; never clinically approved.', task='picture_naming',
            target_phoneme='p', target_position='initial', target_scope={'position': 'initial', 'context': 'isolated_word'},
            items=[{'id': 'fictional-item', 'word': 'pa', 'ipa': '/pa/', 'target_definition': 'Fictional first occurrence',
                'target_occurrence_index': 0, 'selected_attempt': 1, 'exposure_plan': 'trained', 'accepted_variants': [],
                'image_asset': None, 'audio_asset': None, 'familiarity_verified': False, 'reviewed': False}], is_demo=True)
        self.path = reverse('followup:definition_detail', args=[probe.pk])
        return transition_definition(self.actor, probe, 'review')

    def payload(self, digest):
        return {**super().payload(digest), 'competence': 'Fictional scope note only; not independently checked.'}

    def revise_and_resubmit(self):
        probe = transition_definition(self.actor, self.content, 'draft')
        probe = update_definition(self.actor, probe, {'protocol': 'Changed fictional procedure; never clinically approved.'})
        transition_definition(self.actor, probe, 'review')

    def submit_review(self, digest):
        return review_definition(self.actor, self.content, 'clinical', False, 'Fictional changes request',
            'Fictional scope note only', expected_digest=digest)


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, LANGUAGE_CODE='en')
class PackReviewSnapshotTests(ReviewSnapshotContract, TestCase):
    def create_content(self):
        pack = LexicalPack.objects.create(variety=self.variety, series=uuid.uuid4(), created_by=self.actor,
            title='Fictional unapproved pack', region='Fictional region', scope='Fictional community',
            population='Fictional participants only', indications='Unreviewed working material', limits='No clinical approval')
        self.candidate = LexicalCandidate.objects.create(pack=pack, word='pa', meaning='Fictional meaning',
            role='training', provenance='Fictional working proposal')
        self.path = reverse('qualification:pack_detail', args=[pack.pk])
        return change_pack_state(self.actor, pack.pk, 'review')

    def revise_and_resubmit(self):
        change_pack_state(self.actor, self.content.pk, 'draft')
        response = self.client.post(reverse('qualification:candidate_edit', args=[self.content.pk, self.candidate.pk]),
            {'word': 'Fictional revised word', 'meaning': 'Changed fictional meaning', 'role': 'training',
             'provenance': 'Fictional working proposal; no clinical approval'})
        self.assertEqual(response.status_code, 302)
        change_pack_state(self.actor, self.content.pk, 'review')

    def submit_review(self, digest):
        return review_pack(self.actor, self.content, 'clinical', False, 'Fictional changes request', expected_digest=digest)
