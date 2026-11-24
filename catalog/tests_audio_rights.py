"""Exact rights completion on a saved fictional recording without recording it again."""
import csv
import io
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from core.models import AuditEvent, User
from qualification.models import AvailabilityDecision, EvidenceDocument
from qualification.test_support import evidence_fixture, media_fixture
from .guided_audio import media_reference
from .models import Activity, EditorialGrant, MediaAsset, Review, Variety
from .readiness import reference_asset_id
from .review_dossier import review_dossier


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False, LANGUAGE_CODE='en', PUBLIC_ORIGIN='https://fictional.example',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class DraftAudioRightsTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user('draft-audio-editor', email='editor@fictional.test')
        self.other = User.objects.create_user('draft-audio-reviewer', email='reviewer@fictional.test')
        self.variety = Variety.objects.create(code='ar-dz-audio-rights', language='ar', label='Fictional Darija')
        self.foreign = Variety.objects.create(code='ar-msa-audio-rights', language='ar', label='Fictional MSA')
        EditorialGrant.objects.create(user=self.editor, variety=self.variety, edit=True)
        EditorialGrant.objects.create(user=self.other, variety=self.variety, linguistic_review=True)
        self.word = 'باب'
        self.source = media_fixture(self.variety, self.other, 'audio', word=self.word)
        self.source.rights_status = 'unknown'
        self.source.rights_validity = 'unknown'
        self.source.rights_evidence = None
        # The real browser just sees fictional bytes in tests. No real human voice is used.
        self.profile = {'source': 'human', 'text': self.word, 'variety': self.variety.code,
                        'region': 'Fictional locality', 'retained_marker': 'Fictional historic metadata'}
        self.source.provenance = {'audio': self.profile.copy()}
        self.source.save()
        self.reference = media_reference(self.source)
        values = {'variety': self.variety, 'title': 'Fictional saved recording', 'word_a': self.word, 'word_b': 'مفتاح',
                  'contrast': 'Fictional fixture', 'instructions': {'en': 'Fictional'}, 'is_demo': False,
                  'audio_a': self.reference}
        self.draft = Activity.objects.create(series=uuid4(), **values)
        self.sibling = Activity.objects.create(series=uuid4(), **values)
        self.document = evidence_fixture(self.variety, self.editor, 'rights')
        self.path = reverse('editorial_audio_rights', args=[self.draft.pk, 'a'])
        self.client.force_login(self.editor)

    def payload(self):
        view = self.client.get(self.path, secure=True)
        self.assertEqual(view.status_code, 200)
        return {'rights_context': view.context['rights_context'], 'rights': 'Fictional documented use',
            'rights_status': 'original_documented', 'rights_validity': 'unlimited', 'rights_evidence': self.document.pk,
            'confirm_adult_consent': 'on',
            **{'rights_' + key: 'Fictional test permission'
               for key in ('holder', 'licence', 'permitted_use', 'territory', 'duration', 'attribution', 'adult_speaker_permission')}}

    def worksheet(self):
        response = self.client.get(reverse('editorial_review_pack'), {'activity': self.draft.pk}, secure=True)
        self.assertEqual(response.status_code, 200)
        with ZipFile(io.BytesIO(response.content)) as archive:
            rows = csv.DictReader(io.StringIO(archive.read('recording_prompts.csv').decode('utf-8-sig')))
            return {row['side']: row for row in rows}

    def assert_original_unchanged(self):
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.audio_a, self.reference)
        self.assertEqual(MediaAsset.objects.filter(kind='audio').count(), 1)
        self.assertFalse(AuditEvent.objects.filter(action='catalog.audio_rights_documented').exists())

    def test_reuses_exact_bytes_and_preserves_voice_scope_history(self):
        for code, title in [('fr', 'Documenter les droits de l’enregistrement'),
                            ('en', 'Document recording rights'), ('ar', 'توثيق حقوق التسجيل')]:
            with translation.override(code):
                detail = self.client.get(reverse('editorial_detail', args=[self.draft.pk]), secure=True)
                self.assertContains(detail, 'data-draft-audio-rights="a"')
                view = self.client.get(reverse('editorial_audio_rights', args=[self.draft.pk, 'a']), secure=True)
                self.assertContains(view, title)
                self.assertContains(view, 'data-audio-rights-form')
                self.assertNotContains(view, 'type="file"')
                self.assertNotContains(view, 'name="audio_source"')
                self.assertIn('private', view['Cache-Control'])
        before = self.worksheet()
        self.assertEqual(before['a']['audio_documentation_url'], 'https://fictional.example' + self.path)
        self.assertEqual(before['a']['audio_collection_url'], '')
        self.assertEqual(before['b']['audio_documentation_url'], '')
        self.assertTrue(before['b']['audio_collection_url'])
        payload = self.payload()
        # Browser-supplied extra fields cannot change the already recorded content.
        result = self.client.post(self.path, {**payload, 'audio_text': 'Other text',
            'audio_source': 'synthetic', 'audio_variety': self.foreign.pk}, secure=True)
        self.assertRedirects(result, reverse('editorial_detail', args=[self.draft.pk]), fetch_redirect_response=False)
        self.draft.refresh_from_db()
        self.sibling.refresh_from_db()
        self.source.refresh_from_db()
        copy = MediaAsset.objects.get(pk=reference_asset_id(self.draft.audio_a, 'audio'))
        self.assertEqual(copy.audio_predecessor_id, self.source.pk)
        media = next(row for row in review_dossier(self.draft)['media'] if row['field'] == 'audio_a')
        self.assertEqual(media['audio_origin'], {'predecessor_asset_id': str(self.source.pk),
            'predecessor_sha256': self.source.technical_metadata['sha256']})
        with self.assertRaises(ValidationError):
            MediaAsset.objects.create(kind='audio', uploaded_by=self.editor, rights='Fictional permission',
                audio_predecessor=self.source, provenance={'audio': self.profile}, file=self.source.file.name)
        self.assertEqual(copy.provenance['audio'], self.profile)
        self.assertEqual(copy.rights_evidence_id, self.document.pk)
        self.assertEqual(copy.technical_metadata, self.source.technical_metadata)
        self.assertNotEqual(copy.file.name, self.source.file.name)
        with copy.file.open('rb') as new, self.source.file.open('rb') as old:
            self.assertEqual(new.read(), old.read())
        self.assertTrue(copy.documented)
        self.assertEqual(self.source.rights_status, 'unknown')
        self.assertEqual(self.sibling.audio_a, self.reference)
        self.assertEqual(self.draft.audio_b, '')
        self.assertEqual(self.draft.state, 'draft')
        self.assertFalse(Review.objects.exists())
        self.assertFalse(AvailabilityDecision.objects.exists())
        self.assertEqual(self.worksheet()['a']['audio_documentation_url'], '')
        detail = self.client.get(reverse('editorial_detail', args=[self.draft.pk]), secure=True)
        self.assertNotContains(detail, 'data-draft-audio-rights="a"')
        self.assertEqual(self.client.post(self.path, payload, secure=True).status_code, 409)
        self.assertEqual(AuditEvent.objects.filter(action='catalog.audio_rights_documented').count(), 1)
        self.assertEqual(MediaAsset.objects.filter(kind='audio').count(), 2)
        copy.provenance['audio']['text'] = 'Changed word'
        with self.assertRaises(ValidationError):
            copy.save()

    def test_worksheet_never_offers_rights_action_for_other_roles_or_ineligible_audio(self):
        self.client.force_login(self.other)
        detail = self.client.get(reverse('editorial_detail', args=[self.draft.pk]), secure=True)
        self.assertNotContains(detail, 'data-draft-audio-rights')
        self.assertEqual(self.worksheet()['a']['audio_documentation_url'], '')
        self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)
        self.client.force_login(self.editor)
        for status in ('synthetic', 'excluded', 'mismatch', 'revoked'):
            with self.subTest(status=status):
                self.source.provenance['audio'] = self.profile.copy()
                self.source.rights_status = 'unknown'
                self.source.revoked = False
                if status == 'synthetic':
                    self.source.provenance['audio']['source'] = 'synthetic'
                elif status == 'excluded':
                    self.source.rights_status = 'excluded'
                elif status == 'mismatch':
                    self.source.provenance['audio']['text'] = 'Different recorded word'
                else:
                    self.source.revoked = True
                    self.source.revocation_reason = 'Fictional withdrawal'
                self.source.save()
                self.assertEqual(self.worksheet()['a']['audio_documentation_url'], '')
                self.assertEqual(self.client.get(self.path, secure=True).status_code, 404)
        self.assert_original_unchanged()

    def test_requires_current_exact_variety_evidence_and_adult_confirmation(self):
        expired = EvidenceDocument.objects.create(variety=self.variety, category='rights',
            title='Fictional expired rights', provenance='Fictional only', uploaded_by=self.editor,
            validity='limited', valid_until=timezone.localdate() - timedelta(days=1),
            file=SimpleUploadedFile('expired.txt', b'Fictional rights document'))
        foreign = evidence_fixture(self.foreign, self.editor, 'rights')
        payload = self.payload()
        for changes in ({'rights_evidence': expired.pk}, {'rights_evidence': foreign.pk},
                        {'confirm_adult_consent': ''}):
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post(self.path, {**payload, **changes}, secure=True).status_code, 422)
                self.assert_original_unchanged()

    def test_fails_closed_on_stale_recording_or_rolled_back_update(self):
        data = self.payload()
        storage = self.source.file.storage
        with (patch.object(storage, 'save', wraps=storage.save) as saved,
                patch.object(storage, 'delete', wraps=storage.delete) as deleted,
                patch('catalog.image_rights.audit', side_effect=IntegrityError('Fictional audit failure'))):
            self.assertEqual(self.client.post(self.path, data, secure=True).status_code, 503)
        self.assertEqual(saved.call_count, 1)
        deleted.assert_called_once()
        self.assertFalse(storage.exists(deleted.call_args.args[0]))
        self.assertTrue(storage.exists(self.source.file.name))
        self.assert_original_unchanged()
        self.source.provenance['audio']['region'] = 'Different fictional history'
        self.source.save()
        self.assertEqual(self.client.post(self.path, data, secure=True).status_code, 409)
        self.assert_original_unchanged()
