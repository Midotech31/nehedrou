"""Draft illustration documentation against fictional local bytes only."""
import io
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from core.models import AuditEvent, User
from qualification.models import AvailabilityDecision
from qualification.test_support import evidence_fixture
from .models import Activity, EditorialGrant, MediaAsset, Review, Variety
from .readiness import reference_asset_id


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False, LANGUAGE_CODE='en',
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ImageRightsTests(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user('image-rights-editor', email='editor@fictional.test')
        self.other = User.objects.create_user('image-rights-other', email='other@fictional.test')
        self.variety = Variety.objects.create(code='ar-draft-rights-fixture', language='ar', label='Fictional Arabic variety')
        self.other_variety = Variety.objects.create(code='fr-draft-rights-fixture', language='fr', label='Other fictional variety')
        EditorialGrant.objects.create(user=self.editor, variety=self.variety, edit=True)
        EditorialGrant.objects.create(user=self.other, variety=self.variety, linguistic_review=True)
        buffer = io.BytesIO()
        Image.new('RGB', (24, 24), 'teal').save(buffer, format='PNG')
        self.bytes = buffer.getvalue()
        self.source = MediaAsset.objects.create(uploaded_by=self.other, kind='image', rights='Unknown fixture',
            file=SimpleUploadedFile('fictional-source.png', self.bytes))
        self.other_image = MediaAsset.objects.create(uploaded_by=self.editor, kind='image', rights='Unknown fixture',
            file=SimpleUploadedFile('fictional-sibling.png', self.bytes))
        values = {'variety': self.variety, 'title': 'Fictional illustration activity', 'word_a': 'أ', 'word_b': 'ب',
            'contrast': 'Fictional data', 'instructions': {'en': 'Fictional instructions'}, 'is_demo': False,
            'image_a': 'editorial/asset-' + str(self.source.pk),
            'image_b': 'editorial/asset-' + str(self.other_image.pk)}
        self.activity = Activity.objects.create(series=uuid4(), **values)
        self.sibling = Activity.objects.create(series=uuid4(), **values)
        self.proof = evidence_fixture(self.variety, self.editor, 'rights')
        self.path = reverse('editorial_image_rights', args=[self.activity.pk, 'a'])
        self.client.force_login(self.editor)

    def payload(self):
        response = self.client.get(self.path, secure=True)
        self.assertEqual(response.status_code, 200)
        return {'rights_context': response.context['rights_context'], 'rights': 'Fictional declarations for regression only',
            'rights_status': 'original_documented', 'rights_evidence': str(self.proof.pk), 'rights_validity': 'unlimited',
            **{'rights_' + key: 'Fictional scope' for key in ('holder', 'licence', 'permitted_use', 'territory', 'duration', 'attribution')}}

    def assert_originals_retained(self):
        self.activity.refresh_from_db()
        self.sibling.refresh_from_db()
        self.assertEqual(reference_asset_id(self.activity.image_a, 'image'), self.source.pk)
        self.assertEqual(reference_asset_id(self.sibling.image_a, 'image'), self.source.pk)
        self.assertEqual(MediaAsset.objects.count(), 2)
        self.assertFalse(AuditEvent.objects.filter(action='catalog.image_rights_documented').exists())

    def test_scoped_editor_documents_exact_copy_without_file_input_or_approval(self):
        before = self.activity.fingerprint()
        for language, title in [('fr', 'Documenter les droits de l’illustration'),
                                ('en', 'Document illustration rights'), ('ar', 'توثيق حقوق الصورة')]:
            url = f'/{language}/editorial/{self.activity.pk}/image/a/rights/'
            response = self.client.get(url, secure=True)
            self.assertContains(response, title)
            self.assertContains(response, 'data-image-rights-form')
            self.assertNotContains(response, 'type="file"')
            self.assertIn('private', response['Cache-Control'])
        response = self.client.get(reverse('editorial_detail', args=[self.activity.pk]), secure=True)
        self.assertContains(response, 'data-draft-image-rights="a"')
        payload = self.payload()
        response = self.client.post(self.path, payload, secure=True)
        self.assertRedirects(response, reverse('editorial_detail', args=[self.activity.pk]), fetch_redirect_response=False)
        self.activity.refresh_from_db()
        self.sibling.refresh_from_db()
        self.source.refresh_from_db()
        replacement = MediaAsset.objects.get(pk=reference_asset_id(self.activity.image_a, 'image'))
        self.assertEqual(replacement.rights_evidence_id, self.proof.pk)
        self.assertEqual(replacement.uploaded_by_id, self.editor.pk)
        self.assertTrue(replacement.documented)
        self.assertNotEqual(replacement.file.name, self.source.file.name)
        with replacement.file.open('rb') as file:
            self.assertEqual(file.read(), self.bytes)
        self.assertEqual(replacement.technical_metadata, self.source.technical_metadata)
        self.assertEqual(self.source.rights_status, 'unknown')
        self.assertEqual(reference_asset_id(self.sibling.image_a, 'image'), self.source.pk)
        self.assertEqual(reference_asset_id(self.activity.image_b, 'image'), self.other_image.pk)
        self.assertEqual(self.activity.state, 'draft')
        self.assertNotEqual(self.activity.fingerprint(), before)
        self.assertFalse(Review.objects.exists())
        self.assertFalse(AvailabilityDecision.objects.exists())
        self.assertEqual(AuditEvent.objects.filter(action='catalog.image_rights_documented', object_id=self.activity.pk).count(), 1)
        self.assertEqual(self.client.post(self.path, payload, secure=True).status_code, 409)
        self.assertEqual(MediaAsset.objects.count(), 3)

    def test_source_and_evidence_are_rechecked_after_preparation(self):
        for change in ('draft', 'revoked', 'bytes'):
            with self.subTest(change=change):
                payload = self.payload()
                if change == 'draft':
                    Activity.objects.filter(pk=self.activity.pk).update(title='Changed fictional draft')
                elif change == 'revoked':
                    self.source.revoked = True
                    self.source.revocation_reason = 'Fictional withdrawal'
                    self.source.save()
                else:
                    with self.source.file.open('wb') as file:
                        file.write(b'Fictional altered image')
                self.assertEqual(self.client.post(self.path, payload, secure=True).status_code, 409)
                self.assert_originals_retained()
                if change == 'revoked':
                    MediaAsset.objects.filter(pk=self.source.pk).update(revoked=False, revocation_reason='')

    def test_wrong_scope_and_revoked_evidence_cannot_be_bound(self):
        foreign = evidence_fixture(self.other_variety, self.editor, 'rights')
        response = self.client.post(self.path, {**self.payload(), 'rights_evidence': str(foreign.pk)}, secure=True)
        self.assertEqual(response.status_code, 422)
        payload = self.payload()
        self.proof.revoked = True
        self.proof.revocation_reason = 'Fictional test withdrawal'
        self.proof.save()
        self.assertEqual(self.client.post(self.path, payload, secure=True).status_code, 422)
        self.assert_originals_retained()

    def test_reviewers_and_non_drafts_have_no_documentation_action(self):
        payload = self.payload()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.path, secure=True).status_code, 403)
        self.assertEqual(self.client.post(self.path, payload, secure=True).status_code, 403)
        self.client.force_login(self.editor)
        Activity.objects.filter(pk=self.activity.pk).update(state='review')
        self.assertEqual(self.client.get(self.path, secure=True).status_code, 404)
        self.assertEqual(self.client.post(self.path, payload, secure=True).status_code, 409)
        self.assert_originals_retained()

    def test_storage_or_database_failure_does_not_leave_link_asset_or_file(self):
        storage = self.source.file.storage
        payload = self.payload()
        with patch.object(storage, 'save', side_effect=OSError('Fictional unavailable storage')):
            self.assertEqual(self.client.post(self.path, payload, secure=True).status_code, 503)
        self.assert_originals_retained()
        with patch.object(storage, 'save', wraps=storage.save) as saved, patch.object(storage, 'delete', wraps=storage.delete) as deleted, \
                patch('catalog.image_rights.audit', side_effect=IntegrityError('Fictional audit write failure')):
            self.assertEqual(self.client.post(self.path, payload, secure=True).status_code, 503)
        self.assertEqual(saved.call_count, 1)
        deleted.assert_called_once()
        self.assertFalse(storage.exists(deleted.call_args.args[0]))
        self.assertTrue(storage.exists(self.source.file.name))
        self.assert_originals_retained()
