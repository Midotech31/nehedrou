"""Fiction-only collaborative pack media editing; no clinical approvals or live services."""
import uuid

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from catalog.models import EditorialGrant, Variety
from core.models import User
from .models import LexicalCandidate, LexicalPack
from .services import clone_pack
from .test_support import media_fixture


@override_settings(
    DEMO_MODE=True,
    MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class CollaborativeCandidateMediaTests(TestCase):
    def setUp(self):
        self.variety = Variety.objects.create(code='fr-pack-fixture', language='fr', label='Fictional pack variety')
        self.author = User.objects.create_user(username='pack-original-author', email='pack-author@example.test')
        self.editor = User.objects.create_user(username='pack-collaborating-editor', email='pack-editor@example.test')
        for user in (self.author, self.editor):
            EditorialGrant.objects.create(user=user, variety=self.variety, edit=True)
        self.pack = LexicalPack.objects.create(
            variety=self.variety, title='Fictional collaborative draft', series=uuid.uuid4(),
            region='Fictional region', scope='Software regression only',
            population='No real participants', indications='No clinical indication claimed',
            limits='Unreviewed fixture only', created_by=self.author,
        )
        self.image = media_fixture(self.variety, self.author, 'image', word='maison')
        self.audio = media_fixture(self.variety, self.author, 'audio', word='maison')
        self.candidate = LexicalCandidate.objects.create(
            pack=self.pack, word='maison', meaning='Fictional house concept', role='training',
            provenance='Fictional original author', image=self.image, audio=self.audio,
        )
        self.client.force_login(self.editor)

    def payload(self, candidate=None):
        candidate = candidate or self.candidate
        return {
            'word': candidate.word, 'meaning': 'Updated draft wording, not clinical approval',
            'ipa': candidate.ipa, 'role': candidate.role, 'provenance': candidate.provenance,
            'image': str(candidate.image_id), 'audio': str(candidate.audio_id),
            'segment_list': '', 'target_list': '', 'variant_list': '', 'synonym_list': '',
        }

    def test_other_editor_can_preserve_existing_media_in_every_interface_language(self):
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language), translation.override(language):
                path = reverse('qualification:candidate_edit', args=[self.pack.pk, self.candidate.pk])
                page = self.client.get(path)
                self.assertEqual(page.status_code, 200)
                form = page.context['form']
                self.assertIn(self.image.pk, form.fields['image'].queryset.values_list('pk', flat=True))
                self.assertIn(self.audio.pk, form.fields['audio'].queryset.values_list('pk', flat=True))
                response = self.client.post(path, self.payload())
                self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
                self.candidate.refresh_from_db()
                self.assertEqual((self.candidate.image_id, self.candidate.audio_id), (self.image.pk, self.audio.pk))
                self.assertEqual(self.candidate.meaning, 'Updated draft wording, not clinical approval')
                self.pack.refresh_from_db()
                self.assertEqual(self.pack.state, 'draft')
                self.assertEqual(self.pack.reviews.count(), 0)

    def test_unlinked_other_user_media_stay_unselectable_for_new_and_existing_candidates(self):
        unrelated = media_fixture(self.variety, self.author, 'image', word='unrelated')
        for candidate in (None, self.candidate):
            with self.subTest(existing=bool(candidate)):
                path = reverse('qualification:candidate_edit', args=[self.pack.pk, candidate.pk]) if candidate else reverse('qualification:candidate_new', args=[self.pack.pk])
                page = self.client.get(path)
                self.assertNotIn(unrelated.pk, page.context['form'].fields['image'].queryset.values_list('pk', flat=True))
                before = LexicalCandidate.objects.count()
                response = self.client.post(path, {**self.payload(), 'image': str(unrelated.pk)})
                self.assertEqual(response.status_code, 200)
                self.assertIn('image', response.context['form'].errors)
                self.assertEqual(LexicalCandidate.objects.count(), before)
                self.candidate.refresh_from_db()
                self.assertEqual(self.candidate.image_id, self.image.pk)

    def test_new_pack_version_keeps_linked_media_editable_without_changing_source(self):
        clone = clone_pack(self.editor, self.pack)
        candidate = clone.candidates.get()
        path = reverse('qualification:candidate_edit', args=[clone.pk, candidate.pk])
        response = self.client.post(path, self.payload(candidate))
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        candidate.refresh_from_db()
        self.assertEqual((candidate.image_id, candidate.audio_id), (self.image.pk, self.audio.pk))
        self.assertEqual(candidate.meaning, 'Updated draft wording, not clinical approval')
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.meaning, 'Fictional house concept')
        self.assertEqual((clone.state, clone.reviews.count()), ('draft', 0))
