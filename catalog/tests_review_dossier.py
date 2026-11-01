"""Fictional editorial evidence only; no human validation is manufactured."""
import csv
import hashlib
import io
import json
import uuid
import zipfile
from datetime import date
from unittest.mock import patch
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from catalog.integrity import integrity_scope, prepare_activities
from catalog.models import Activity, EditorialGrant, MediaAsset, Review, Variety
from catalog.quality import completeness
from catalog.readiness import referenced_asset
from catalog.review_dossier import review_dossier
from catalog.services import review_version, transition
from core.models import User
from qualification.models import AvailabilityDecision, EvidenceDocument, _digest_file
from qualification.test_support import availability_fixture, competence_fixture, prepare_activity_fixture


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PUBLIC_ORIGIN='https://demo.example',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class EvidenceDossierTests(TestCase):
    def setUp(self):
        self.variety = Variety.objects.create(code='dossier-fr', language='fr', label='Fictional French')
        self.foreign = Variety.objects.create(code='dossier-other', language='en', label='Other scope')
        self.editor = User.objects.create_user(username='dossier-editor', email='private-editor@example.test')
        self.linguist = User.objects.create_user(username='dossier-linguist', email='private-linguist@example.test')
        self.outsider = User.objects.create_user(username='dossier-family', email='private-family@example.test')
        competence_fixture(self.editor, self.variety, 'clinical')
        competence_fixture(self.linguist, self.variety, 'linguistic')
        self.client.force_login(self.editor)

    def activity(self, complete=False, **extra):
        values = dict(variety=self.variety, series=uuid.uuid4(), title='Fictional dossier',
            word_a='pa', word_b='ba', contrast='p/b', is_demo=False,
            population='Fictional software test only', rights='Written claim without permission evidence',
            instructions={'fr':'Fictif', 'en':'Fictional', 'ar':'مثال'})
        values.update(extra)
        activity = Activity.objects.create(**values)
        if complete:
            prepare_activity_fixture(activity, self.editor, self.linguist)
            availability_fixture('practice', self.variety, activity.fingerprint(), self.editor)
        return activity

    def archive(self, activity=None, **params):
        if activity:
            params['activity'] = str(activity.pk)
        response = self.client.get(reverse('editorial_review_pack'), params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        return zipfile.ZipFile(io.BytesIO(response.content))

    def test_written_rights_and_present_audio_do_not_hide_actual_gaps(self):
        activity = self.activity(complete=True)
        audio = referenced_asset(activity.audio_a, 'audio')
        audio.rights_status = 'unknown'
        audio.provenance['audio']['text'] = 'another exact word'
        audio.provenance['holder'] = ''
        audio.save()
        # Existing completeness remains explicitly a field/file presence measure.
        self.assertTrue(next(check['complete'] for check in completeness(activity)['checks'] if check['key'] == 'rights'))
        self.assertTrue(next(check['complete'] for check in completeness(activity)['checks'] if check['key'] == 'audio'))
        dossier = review_dossier(activity)
        task = next(row for row in dossier['tasks'] if row['key'] == 'audio_a')
        self.assertTrue({'rights_status', 'rights_fields', 'audio_binding'} <= set(task['reason_codes']))
        self.assertIn('review_stale', next(row for row in dossier['tasks'] if row['key'] == 'review_clinical')['reason_codes'])
        self.assertEqual(dossier['clinical_validation'], 'not_assessed_by_dossier')
        activity.refresh_from_db()
        self.assertEqual(activity.state, 'review')
        self.assertEqual(activity.reviews.count(), 2)

    def test_identical_side_specific_family_candidates_are_sent_to_linguistic_review(self):
        activity = self.activity()
        candidates = [{'word': 'cat', 'family_alternatives': ['kitty'], 'scope': 'Fictional local proposal'}]
        activity.item_metadata = {
            'a': {'meaning': 'cat', 'family_word_candidates': candidates},
            'b': {'meaning': 'dog', 'family_word_candidates': candidates},
        }
        activity.save(update_fields=['item_metadata'])
        dossier = review_dossier(activity)
        task = next(row for row in dossier['tasks'] if row['key'] == 'family_candidate_lists')
        self.assertIn('candidate_list_reuse', task['reason_codes'])
        self.assertEqual(dossier['clinical_validation'], 'not_assessed_by_dossier')
        self.assertEqual(activity.state, 'draft')
        self.assertFalse(activity.reviews.exists())

        activity.is_demo = True  # The fixture may use the demo-only review path.
        activity.save(update_fields=['is_demo'])
        transition(self.editor, activity.pk, 'review')
        review_version(self.linguist, activity, 'linguistic', True,
            'Fictional confirmation: shared candidates are intentional.')
        dossier = review_dossier(activity)
        self.assertNotIn('family_candidate_lists', [row['key'] for row in dossier['tasks']])
        activity.refresh_from_db()
        self.assertEqual(activity.state, 'review')  # A review decision does not publish content.

    def test_valid_recorded_gates_never_become_a_dossier_approval(self):
        activity = self.activity(complete=True)
        dossier = review_dossier(activity)
        self.assertEqual(dossier['tasks'], [])
        self.assertEqual(dossier['blocking_reasons'], [])
        self.assertNotIn('approved', dossier)
        self.assertNotIn('can_publish', dossier)
        self.assertEqual(dossier['clinical_validation'], 'not_assessed_by_dossier')
        self.assertFalse(activity.usable)  # Still in review; the dossier performs no transition.
        page = self.client.get('/en/editorial/quality/', {'activity': activity.pk})
        self.assertContains(page, 'dossier-'+str(activity.pk))
        self.assertContains(page, 'Human evidence dossier')
        self.assertContains(page, 'publication workflow still apply')

    def test_expiry_revocation_and_changed_bytes_are_specific_and_fresh(self):
        activity = self.activity(complete=True)
        asset = referenced_asset(activity.image_a, 'image')
        asset.rights_validity = 'limited'
        asset.rights_valid_until = date(2026, 10, 30)
        asset.save()
        with patch('qualification.validity.timezone.localdate', return_value=date(2026, 10, 30)):
            with integrity_scope():
                prepare_activities([activity])
                row = next(row for row in review_dossier(activity)['media'] if row['field'] == 'image_a')
                self.assertNotIn('expired', row['reason_codes'])
        with patch('qualification.validity.timezone.localdate', return_value=date(2026, 10, 31)):
            with integrity_scope():
                prepare_activities([activity])
                row = next(row for row in review_dossier(activity)['media'] if row['field'] == 'image_a')
                self.assertIn('expired', row['reason_codes'])
        with asset.file.storage.open(asset.file.name, 'wb') as stream:
            stream.write(b'Changed fixture bytes')
        with integrity_scope():
            prepare_activities([activity])
            row = next(row for row in review_dossier(activity)['media'] if row['field'] == 'image_a')
            self.assertIn('media_bytes', row['reason_codes'])
        proof = asset.rights_evidence
        proof.revoked = True
        proof.revocation_reason = 'Fictional withdrawal'
        proof.save()
        with integrity_scope():
            prepare_activities([activity])
            row = next(row for row in review_dossier(activity)['media'] if row['field'] == 'image_a')
            self.assertIn('revoked', row['reason_codes'])

    def test_latest_rejection_and_same_person_do_not_appear_complete(self):
        activity = self.activity(complete=True)
        review_version(self.editor, activity, 'clinical', False, 'Private reviewer note')
        dossier = review_dossier(activity)
        task = next(row for row in dossier['tasks'] if row['key'] == 'review_clinical')
        self.assertIn('changes_requested', task['reason_codes'])
        competence_fixture(self.editor, self.variety, 'linguistic')
        review_version(self.editor, activity, 'clinical', True, 'Fictional test only')
        review_version(self.editor, activity, 'linguistic', True, 'Fictional test only')
        dossier = review_dossier(activity)
        self.assertIn('independent_reviews', [row['key'] for row in dossier['tasks']])
        self.assertTrue(dossier['blocking_reasons'])

    def test_familiarity_and_availability_require_exact_evidence_bindings(self):
        activity = self.activity(complete=True)
        activity.item_metadata['a']['familiarity']['sha256'] = '0'*64
        activity.save()
        dossier = review_dossier(activity)
        self.assertIn('evidence_binding', next(row for row in dossier['tasks'] if row['key'] == 'familiarity_a')['reason_codes'])
        # A previous version's evidence does not silently qualify the new digest.
        self.assertEqual(len([row for row in dossier['tasks'] if row['category'] == 'availability_evidence']), 5)
        self.assertIn('availability', [row['key'] for row in dossier['tasks']])

    def test_zip_contains_scoped_exact_tasks_blank_decisions_and_no_private_provenance(self):
        activity = self.activity(complete=True, word_a='=1+1')
        asset = referenced_asset(activity.audio_a, 'audio')
        asset.provenance['holder'] = 'Private contract name / SECRET-CREDENTIAL-DO-NOT-EXPORT'
        asset.provenance['audio']['region'] = 'Private speaker address'
        asset.save()
        foreign = self.activity(variety=self.foreign, title='Foreign unpublished private proposal')
        counts = (Activity.objects.count(), Review.objects.count(), EvidenceDocument.objects.count(), AvailabilityDecision.objects.count())
        with self.archive(activity) as archive:
            payload = archive.read('evidence_dossiers.json')
            data = json.loads(payload)
            self.assertEqual(len(data['activities']), 1)
            self.assertEqual(data['activities'][0]['activity_id'], str(activity.pk))
            self.assertEqual(data['activities'][0]['content_sha256'], activity.fingerprint())
            self.assertEqual(hashlib.sha256(payload).hexdigest(), archive.read('evidence_dossiers.sha256').decode())
            rows = list(csv.DictReader(io.StringIO(archive.read('evidence_tasks.csv').decode('utf-8-sig'))))
            self.assertTrue(rows)
            self.assertTrue(all(row['assigned_person'] == row['actual_evidence_reference'] == row['human_decision'] == row['decision_date'] == '' for row in rows))
            self.assertIn("'=1+1", archive.read('media_requirements.csv').decode('utf-8-sig'))
            combined = b''.join(archive.read(name) for name in archive.namelist())
            for secret in (b'SECRET-CREDENTIAL-DO-NOT-EXPORT', b'Private speaker address', b'private-editor@example.test', str(foreign.pk).encode()):
                self.assertNotIn(secret, combined)
            self.assertEqual(archive.testzip(), None)
        self.assertEqual(counts, (Activity.objects.count(), Review.objects.count(), EvidenceDocument.objects.count(), AvailabilityDecision.objects.count()))

    def test_foreign_evidence_metadata_is_redacted_and_does_not_qualify(self):
        activity = self.activity(complete=True)
        asset = referenced_asset(activity.image_a, 'image')
        proof = asset.rights_evidence
        EvidenceDocument.objects.filter(pk=proof.pk).update(variety=self.foreign)
        with integrity_scope():
            prepare_activities([activity])
            row = next(row for row in review_dossier(activity)['media'] if row['field'] == 'image_a')
        self.assertEqual(row['evidence'], {})
        self.assertIn('evidence_scope', row['reason_codes'])
        self.assertFalse(row['complete'])

    def test_http_scope_active_grants_methods_and_exact_version_links(self):
        activity = self.activity()
        foreign = self.activity(variety=self.foreign)
        for endpoint in ('editorial_quality', 'editorial_review_pack'):
            url = reverse(endpoint)
            self.assertEqual(self.client.get(url, {'activity': foreign.pk}).status_code, 404)
            self.assertEqual(self.client.get(url, {'activity': 'not-a-uuid'}).status_code, 404)
            self.assertEqual(self.client.post(url).status_code, 405)
        page = self.client.get(reverse('editorial_quality'), {'activity': activity.pk})
        self.assertContains(page, '?activity='+str(activity.pk))
        self.assertContains(self.client.get(reverse('editorial_detail', args=[activity.pk])), 'quality/?activity='+str(activity.pk))
        self.client.force_login(self.outsider)
        for endpoint in ('editorial_quality', 'editorial_review_pack'):
            self.assertEqual(self.client.get(reverse(endpoint), {'activity': activity.pk}).status_code, 404)
        self.client.force_login(self.editor)
        EditorialGrant.objects.filter(user=self.editor).delete()
        self.assertEqual(self.client.get(reverse('editorial_review_pack'), {'activity': activity.pk}).status_code, 404)

    def test_four_activity_dossiers_reuse_only_the_current_scope_graph(self):
        activities = [self.activity(complete=True) for _ in range(4)]
        with integrity_scope(), CaptureQueriesContext(connection) as queries, patch('qualification.models._digest_file', wraps=_digest_file) as digests:
            loaded = prepare_activities(Activity.objects.filter(pk__in=[row.pk for row in activities]).select_related('variety'))
            dossiers = [review_dossier(row) for row in loaded]
        self.assertTrue(all(not row['tasks'] for row in dossiers))
        self.assertLessEqual(len(queries), 7)
        self.assertEqual(digests.call_count, 44)
        # No patient/cabinet table is consulted to build a content dossier.
        self.assertFalse(any('care_' in query['sql'].lower() for query in queries))

    def test_http_page_checks_media_only_after_pagination(self):
        for _ in range(4):
            self.activity(complete=True, title='A fictional recorded version')
        for _ in range(32):
            self.activity(title='Z fictional incomplete version')
        with CaptureQueriesContext(connection) as queries, patch('qualification.models._digest_file', wraps=_digest_file) as digests, patch('catalog.quality.completeness', wraps=completeness) as checked:
            response = self.client.get(reverse('editorial_quality'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_content'], 36)
        self.assertEqual(len(response.context['page']), 16)
        self.assertEqual(checked.call_count, 16)
        self.assertEqual(digests.call_count, 44)
        self.assertLessEqual(len(queries), 25)
        with patch('qualification.models._digest_file', wraps=_digest_file) as digests, patch('catalog.quality.completeness', wraps=completeness) as checked:
            response = self.client.get(reverse('editorial_quality'), {'page':2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(checked.call_count, 16)
        self.assertEqual(digests.call_count, 0)
        self.assertEqual(response.context['missing_audio'], 16)
        with patch('catalog.quality.completeness', wraps=completeness) as checked:
            response = self.client.get(reverse('editorial_quality'), {'gap':'guide'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(checked.call_count, 16)
