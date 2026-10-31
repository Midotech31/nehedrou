import io
import os
import uuid
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from catalog.authoring import ActivityAuthoringForm, GUIDE_LABELS
from catalog.models import Activity, EditorialGrant, MediaAsset, Variety, Review
from catalog.services import transition
from core.models import User, Organization, Membership
from core.management.commands.seed_demo_roles import ROLE_PRACTICE_ID, ROLE_PRACTICE_NAME


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class OriginalActivityAuthoringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username='author-test', email='author@example.test')
        cls.variety = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Darja')
        cls.other = Variety.objects.create(code='fr-fr-pilot', language='fr', label='French')
        EditorialGrant.objects.create(user=cls.author, variety=cls.variety, edit=True)

    def basic(self, **extra):
        return dict(variety=str(self.variety.pk), title='Original fictional activity', kind='vocabulary',
                    response_mode='matching', contrast='Objects in the home', word_a='دار', word_b='باب',
                    is_demo='on', **extra)

    def form(self, data, **extra):
        return ActivityAuthoringForm(data, actor=self.author, **extra)

    def test_original_creation_does_not_require_clone_or_three_translations(self):
        form = self.form(self.basic(instructions_ar='اختاروا الصورة معًا.'))
        self.assertTrue(form.is_valid(), form.errors)
        activity = form.save()
        self.assertEqual(activity.state, 'draft')
        self.assertEqual(activity.version, 1)
        self.assertEqual(activity.instructions['ar'], 'اختاروا الصورة معًا.')
        self.assertEqual(activity.practice_guide, {})
        self.assertFalse(activity.usable)
        self.assertFalse(activity.has_current_reviews())
        self.assertEqual(Review.objects.count(), 0)

    def test_scoped_http_creation_and_audit(self):
        self.client.force_login(self.author)
        with translation.override('ar'):
            response = self.client.post(reverse('editorial_create'), self.basic())
        self.assertEqual(response.status_code, 302)
        activity = Activity.objects.get()
        from core.models import AuditEvent
        self.assertTrue(AuditEvent.objects.filter(actor=self.author, action='catalog.draft_saved').exists())
        self.assertEqual(activity.variety, self.variety)
        detail = self.client.get(response.url)
        self.assertContains(detail, 'دار'); self.assertContains(detail, 'باب')
        response = self.client.post(reverse('editorial_create'), {**self.basic(), 'variety': str(self.other.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Activity.objects.count(), 1)

    def test_reviewer_cannot_open_or_post_creation(self):
        EditorialGrant.objects.filter(user=self.author).update(edit=False, clinical_review=True)
        self.client.force_login(self.author)
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(reverse('editorial_create'), self.basic()).status_code, 403)
        self.assertFalse(Activity.objects.exists())

    def test_all_language_interfaces_expose_guided_fields(self):
        self.client.force_login(self.author)
        for code in ['fr', 'en', 'ar']:
            response = self.client.get(f'/{code}/editorial/new/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'name="instructions_ar"')
            self.assertContains(response, 'name="guide_fr_objective"')
            self.assertContains(response, 'name="source_0_scope"')
            self.assertNotContains(response, 'name="practice_guide"')
            self.assertContains(response, 'Designed by Benabdeloued Mohamed Alias Pitou')

    def test_creation_form_names_every_required_field_in_all_languages(self):
        self.client.force_login(self.author)
        expected = {
            'fr': 'Pour enregistrer le brouillon, le titre, la vari\u00e9t\u00e9 parl\u00e9e, la cible ou le th\u00e8me, ainsi que deux mots ou supports sont obligatoires.',
            'en': 'To save the draft, provide a title, spoken variety, target or theme, and two words or prompts.',
            'ar': '\u0644\u062d\u0641\u0638 \u0627\u0644\u0645\u0633\u0648\u062f\u0629\u060c \u064a\u0644\u0632\u0645 \u0625\u062f\u062e\u0627\u0644 \u0627\u0644\u0639\u0646\u0648\u0627\u0646 \u0648\u0627\u0644\u062a\u0646\u0648\u0639 \u0627\u0644\u0644\u063a\u0648\u064a \u0627\u0644\u0645\u0646\u0637\u0648\u0642 \u0648\u0627\u0644\u0647\u062f\u0641 \u0623\u0648 \u0627\u0644\u0645\u0648\u0636\u0648\u0639 \u0648\u0643\u0644\u0645\u062a\u064a\u0646 \u0623\u0648 \u0645\u062d\u0641\u0632\u064a\u0646.',
        }
        for code, sentence in expected.items():
            with self.subTest(language=code):
                response = self.client.get(f'/{code}/editorial/new/')
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, sentence)
                self.assertTrue(response.context['form'].fields['contrast'].required)

    def test_partial_guide_produces_field_errors_without_silent_save(self):
        form = self.form(self.basic(guide_ar_objective='تعلم مفردتين'))
        self.assertFalse(form.is_valid())
        self.assertIn('guide_ar_audience', form.errors)
        self.client.force_login(self.author)
        response = self.client.post('/fr/editorial/new/', self.basic(guide_ar_objective='تعلم مفردتين'))
        self.assertContains(response, 'class="author-language" open><summary>Arabe</summary>')
        self.assertFalse(Activity.objects.exists())

    def test_complete_guide_and_explicit_source_scope_are_stored(self):
        data = self.basic()
        for key in GUIDE_LABELS: data['guide_ar_' + key] = 'محتوى توضيحي للمراجعة'
        data.update(source_0_title='ASHA', source_0_url='https://www.asha.org/practice-portal/',
                    source_0_scope='Approach reference only; not application validation.')
        form = self.form(data)
        self.assertTrue(form.is_valid(), form.errors)
        activity = form.save()
        self.assertEqual(activity.practice_guide['ar']['discover'], ['محتوى توضيحي للمراجعة'])
        self.assertIn('not application validation', activity.evidence_sources[0]['scope'])

    def test_missing_or_insecure_source_is_rejected(self):
        for data in [self.basic(source_0_title='Incomplete'), self.basic(source_0_title='Source', source_0_url='http://example.test/', source_0_scope='Description')]:
            form = self.form(data)
            self.assertFalse(form.is_valid())
        self.assertFalse(Activity.objects.exists())

    def test_structural_minimal_pair_guard_remains_active(self):
        data = self.basic(segments_a='k a t', segments_b='s a t', targets_a='0', targets_b='0', meaning_a='First meaning', meaning_b='Second meaning')
        data['kind'] = 'phonological_contrast'
        form = self.form(data)
        self.assertTrue(form.is_valid(), form.errors)
        activity = form.save()
        self.assertEqual(activity.item_metadata['a']['target_occurrences'][0]['phoneme'], 'k')
        for changes in [{'segments_b': 's u t'}, {'targets_a': '-1'}, {'targets_a': '0, 0'}, {'targets_b': '99'}]:
            invalid = self.form({**data, **changes})
            self.assertFalse(invalid.is_valid(), changes)

    def test_draft_updates_preserve_variants_and_extra_linguistic_metadata(self):
        data = self.basic(meaning_a='Home', meaning_b='Door', segments_a='d a r', segments_b='b a b')
        form = self.form(data); self.assertTrue(form.is_valid(), form.errors)
        activity = form.save()
        activity.item_metadata['a']['accepted_variants'] = [{'ipa': 'daːr', 'reason': 'Fictional variant for review'}]
        activity.item_metadata['a']['local_review'] = {'status': 'pending'}
        activity.save()
        form = self.form(data, instance=activity)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.item_metadata['a']['local_review'], {'status': 'pending'})
        self.assertEqual(saved.item_metadata['a']['accepted_variants'][0]['ipa'], 'daːr')

    def test_original_draft_cannot_publish_by_save_or_transition(self):
        form = self.form(self.basic()); self.assertTrue(form.is_valid(), form.errors)
        activity = form.save()
        with self.assertRaises(PermissionDenied): transition(self.author, activity.pk, 'published')
        activity.state = 'published'
        with self.assertRaises(ValidationError): activity.save()
        activity.refresh_from_db(); self.assertEqual(activity.state, 'draft')

    def test_upload_selector_excludes_other_authors_unshared_media(self):
        from django.core.files.base import ContentFile
        from tempfile import TemporaryDirectory
        from PIL import Image
        foreign = User.objects.create_user(username='foreign-media', email='foreign@example.test')
        buffer = io.BytesIO(); Image.new('RGB', (32, 32), 'white').save(buffer, 'PNG')
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            asset = MediaAsset.objects.create(uploaded_by=foreign, file=ContentFile(buffer.getvalue(), name='fixture.png'), kind='image', rights='Fictional fixture only')
            form = self.form(self.basic(choose_image_a=str(asset.pk)))
            self.assertFalse(form.is_valid())
            self.assertIn('choose_image_a', form.errors)

    def test_selecting_uploaded_audio_binds_reference_without_approving_it(self):
        import wave
        from tempfile import TemporaryDirectory
        from django.core.files.base import ContentFile
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as file:
            file.setnchannels(1); file.setsampwidth(2); file.setframerate(8000)
            file.writeframes(__import__('core.testing',fromlist=['pcm_fixture']).pcm_fixture()[44:])
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory, PUBLIC_ORIGIN='https://demo.example'):
            asset = MediaAsset.objects.create(uploaded_by=self.author, file=ContentFile(buffer.getvalue(), name='synthetic-tone-test.wav'), kind='audio', rights='Synthetic software fixture, not a speech model')
            form = self.form(self.basic(choose_audio_a=str(asset.pk)))
            self.assertTrue(form.is_valid(), form.errors)
            activity = form.save()
            self.assertIn('/media/' + str(asset.pk) + '/', activity.audio_a)
            self.assertFalse(asset.documented)
            self.assertEqual(activity.state, 'draft')
            self.assertEqual(Review.objects.count(), 0)


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PitouDraftAccessTests(TestCase):
    def setUp(self):
        Organization.objects.create(pk=ROLE_PRACTICE_ID, name=ROLE_PRACTICE_NAME)
        for code, language in [('fr-fr-pilot','fr'), ('en-us-general-pilot','en'), ('ar-dz-pilot','ar'), ('ar-msa-pilot','ar')]:
            Variety.objects.create(code=code, language=language, label=code)

    def seed(self):
        with patch.dict(os.environ, {'DEMO_PASSWORD_PITOU': 'Synthetic-Pitou-test-only-2026'}):
            call_command('seed_pitou_demo', stdout=io.StringIO())

    def test_pitou_has_draft_creation_and_clinician_access_without_elevation(self):
        self.seed(); user = User.objects.get(username='pitou')
        self.assertFalse(user.is_superuser); self.assertFalse(user.is_staff)
        self.assertEqual(Membership.objects.get(user=user).role, 'clinician')
        self.assertEqual(EditorialGrant.objects.filter(user=user, edit=True).count(), 4)
        self.assertFalse(EditorialGrant.objects.filter(user=user, publish=True).exists())
        self.assertFalse(EditorialGrant.objects.filter(user=user, clinical_review=True).exists())
        self.assertFalse(EditorialGrant.objects.filter(user=user, linguistic_review=True).exists())
        self.client.force_login(user)
        self.assertEqual(self.client.get('/fr/editorial/new/').status_code, 200)

    def test_seed_preserves_password_and_revoked_capabilities(self):
        self.seed(); user = User.objects.get(username='pitou')
        user.set_password('Changed-synthetic-private-test'); user.save()
        password = user.password
        EditorialGrant.objects.filter(user=user).update(edit=False)
        Membership.objects.filter(user=user).update(active=False)
        self.seed(); user.refresh_from_db()
        self.assertEqual(user.password, password)
        self.assertFalse(EditorialGrant.objects.filter(user=user, edit=True).exists())
        self.assertFalse(Membership.objects.filter(user=user, active=True).exists())

    def test_real_account_collision_is_untouched(self):
        user = User.objects.create_user(username='pitou', email='real@example.test', password='Synthetic-real-collision')
        password = user.password
        with self.assertRaises(CommandError): self.seed()
        user.refresh_from_db(); self.assertEqual(user.password, password)
        self.assertFalse(EditorialGrant.objects.exists()); self.assertFalse(Membership.objects.exists())

    def test_real_mode_and_missing_separate_secret_are_rejected(self):
        with override_settings(DEMO_MODE=False):
            with self.assertRaises(CommandError): self.seed()
        with patch.dict(os.environ, {'DEMO_PASSWORD_PITOU': ''}):
            with self.assertRaises(CommandError): call_command('seed_pitou_demo', stdout=io.StringIO())
        self.assertFalse(User.objects.filter(username='pitou').exists())
