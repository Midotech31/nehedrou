"""Private rehearsal checks with fictional phrases and technical-only media."""
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

from django.core import signing
from django.core.files.base import ContentFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone, translation
from PIL import Image

from care.models import Child, FamilyLink, Program, ProgramItem, PracticeSession
from catalog.guided_audio import media_reference
from catalog.models import Activity, DraftWorkingCopy, EditorialGrant, MediaAsset, Review, Variety
from core.form_scope import MAX_AGE
from core.models import AuditEvent, Membership, Organization, User
from core.testing import pcm_fixture
from qualification.models import AvailabilityDecision


@override_settings(
    DEMO_MODE=False,
    MFA_REQUIRED=False,
    PUBLIC_ORIGIN='https://fictional-rehearsal.example.test',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class EditorialRehearsalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.darja = Variety.objects.create(code='ar-dz-pilot', language='ar', label='Fictional Darja')
        cls.msa = Variety.objects.create(code='ar-msa-pilot', language='ar', label='Fictional MSA')
        cls.editor = cls.account('rehearsal-editor', instruction_language='en')
        cls.reviewer = cls.account('rehearsal-reviewer')
        cls.other_editor = cls.account('rehearsal-other-editor')
        cls.clinician = cls.account('rehearsal-clinician')
        cls.family = cls.account('rehearsal-family')
        cls.superuser = cls.account('rehearsal-platform', is_superuser=True, is_staff=True)
        EditorialGrant.objects.create(user=cls.editor, variety=cls.darja, edit=True)
        EditorialGrant.objects.create(user=cls.reviewer, variety=cls.darja, linguistic_review=True)
        EditorialGrant.objects.create(user=cls.other_editor, variety=cls.msa, edit=True)
        cabinet = Organization.objects.create(name='Fictional rehearsal cabinet')
        Membership.objects.create(organization=cabinet, user=cls.clinician, role='clinician')
        child = Child.objects.create(organization=cabinet, responsible=cls.clinician,
                                     code='FICTIONAL-REHEARSAL-PATIENT', age_years=5)
        FamilyLink.objects.create(child=child, user=cls.family)
        cls.activity = Activity.objects.create(
            variety=cls.darja, series=uuid4(), kind='vocabulary', title='Fictional rehearsal version one',
            contrast='Fictional technical prompts', word_a='دار', word_b='باب', requested_target='b',
            instructions={'fr': 'CONSIGNE-FICTIVE-FR', 'en': 'FICTIONAL-INSTRUCTION-EN', 'ar': 'تعليمة عربية للتجربة'},
            practice_guide={language: {
                'objective': marker, 'audience': marker, 'review_notes': marker, 'discover': [marker],
                'listen': [marker], 'exchange': [marker], 'support': [marker], 'limits': [marker],
            } for language, marker in [('en', 'FICTIONAL-GUIDE-EN'), ('ar', 'مساعدة عربية للتجربة')]},
            is_demo=False,
        )
        cls.newer = Activity.objects.create(
            variety=cls.darja, series=cls.activity.series, version=2, kind='vocabulary',
            title='FICTIONAL-NEWER-VERSION', contrast='Fictional technical prompts',
            word_a='قلم', word_b='كتاب', instructions={'en': 'FICTIONAL-INSTRUCTION-2'}, is_demo=False,
        )

    @staticmethod
    def account(name, **fields):
        return User.objects.create_user(username=name, email=name + '@example.test', **fields)

    def setUp(self):
        language = translation.override('en')
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)
        self.client.force_login(self.editor)
        self.url = reverse('editorial_rehearsal', args=[self.activity.pk])

    def open_page(self, *, client=None, url=None, **query):
        response = (client or self.client).get(url or self.url, query, secure=True)
        self.assertEqual(response.status_code, 200)
        return response

    @staticmethod
    def choices(page, **values):
        return {
            'guide_language': page.context['instruction_language'],
            'rehearsal_snapshot': page.context['rehearsal_snapshot'],
            'answer': 'a', 'completion': 'completed', 'parent_report': 'help', 'support_used': 'gesture',
            **values,
        }

    def test_exact_version_and_guide_language_are_independent_of_interface_and_preferences(self):
        context = self.open_page()
        self.assertEqual(context.context['activity'].pk, self.activity.pk)
        self.assertEqual(context.context['instruction_language'], 'en')
        self.assertEqual(context.context['target_side'], 'b')
        self.assertContains(context, 'lang="ar-DZ" dir="rtl"')
        self.assertContains(context, 'FICTIONAL-GUIDE-EN')
        self.assertNotContains(context, 'FICTIONAL-NEWER-VERSION')
        self.assertNotContains(context, 'FICTIONAL-REHEARSAL-PATIENT')
        self.assertNotContains(context, 'name="comment"')
        self.assertNotContains(context, 'name="ticket"')
        self.assertContains(context, 'data-rehearsal-notice')
        self.assertContains(context, self.activity.get_state_display())
        self.assertIn('no-store', context.headers['Cache-Control'])
        self.assertIn('private', context.headers['Cache-Control'])
        self.assertIn('noindex', context.headers['X-Robots-Tag'])
        self.assertIn('microphone=()', context.headers['Permissions-Policy'])

        arabic_guide = self.open_page(guide_language='ar')
        self.assertContains(arabic_guide, '<ol lang="ar" dir="rtl">')
        self.assertContains(arabic_guide, 'مساعدة عربية للتجربة')
        self.assertNotContains(arabic_guide, 'FICTIONAL-GUIDE-EN')
        with translation.override('ar'):
            arabic_url = reverse('editorial_rehearsal', args=[self.activity.pk])
        french_guide = self.open_page(url=arabic_url, guide_language='fr')
        self.assertContains(french_guide, '<p lang="fr" dir="ltr">CONSIGNE-FICTIVE-FR</p>')
        self.assertContains(french_guide, '<html lang="ar" dir="rtl">')
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.instruction_language, 'en')
        unrestricted_target = self.open_page(url=reverse('editorial_rehearsal', args=[self.newer.pk]))
        self.assertEqual(unrestricted_target.context['target_side'], 'a')
        self.assertEqual(unrestricted_target.context['target'], self.newer.word_a)

    def test_missing_and_unknown_guide_language_never_select_another_language(self):
        self.activity.instructions = {'fr': 'ONLY-FRENCH-INSTRUCTION'}
        self.activity.practice_guide = {}
        self.activity.save(update_fields=['instructions', 'practice_guide'])
        page = self.open_page(guide_language='ar')
        self.assertNotContains(page, 'ONLY-FRENCH-INSTRUCTION')
        self.assertNotContains(page, 'data-guided-activity')
        self.assertEqual(page.context['instruction'], '')
        for query in ['?guide_language=ar-DZ', '?guide_language=fr&guide_language=en', '?patient=fictional']:
            with self.subTest(query=query):
                self.assertEqual(self.client.get(self.url + query, secure=True).status_code, 400)

    def test_only_actors_with_exact_editorial_scope_can_rehearse(self):
        self.assertEqual(Client().get(self.url, secure=True).status_code, 302)
        for user in [self.family, self.clinician, self.other_editor]:
            with self.subTest(user=user.username):
                outsider = Client()
                outsider.force_login(user)
                self.assertEqual(outsider.get(self.url, secure=True).status_code, 404)
        for user in [self.reviewer, self.superuser]:
            with self.subTest(user=user.username):
                scoped = Client()
                scoped.force_login(user)
                self.open_page(client=scoped)
        self.assertEqual(self.client.put(self.url, secure=True).status_code, 405)

    def test_matching_rehearsal_describes_choice_and_never_writes_business_data(self):
        models = (Activity, AuditEvent, AvailabilityDecision, Child, DraftWorkingCopy, Program,
                  ProgramItem, PracticeSession, Review)
        before = {model: list(model.objects.order_by('pk').values()) for model in models}
        with CaptureQueriesContext(connection) as queries:
            page = self.open_page(guide_language='fr')
            response = self.client.post(self.url, self.choices(page), secure=True)
        writes = [query['sql'] for query in queries if query['sql'].lstrip().split(None, 1)[0].upper()
                  in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'MERGE'}]
        self.assertEqual(writes, [])
        self.assertEqual(before, {model: list(model.objects.order_by('pk').values()) for model in models})
        self.assertContains(response, 'data-rehearsal-summary')
        self.assertNotContains(response, 'data-guided-activity')
        self.assertIn('no-store', response.headers['Cache-Control'])
        summary = response.context['summary']
        self.assertEqual(set(summary), {'answer', 'completion', 'parent_report', 'support_used', 'stop_reason'})
        self.assertEqual(summary['answer'], self.activity.word_a)
        self.assertIn('do not measure pronunciation or clinical progress', response.content.decode())
        self.editor.refresh_from_db()
        self.assertEqual(self.editor.instruction_language, 'en')
        self.assertEqual(self.client.post(self.url, self.choices(page, comment='Fictional text'), secure=True).status_code, 400)
        self.assertEqual(self.client.post(self.url, self.choices(page, ticket='Fictional ticket'), secure=True).status_code, 400)

    def test_hybrid_editor_rehearsal_does_not_select_a_practice_or_save_the_session(self):
        cabinet = Organization.objects.create(name='Fictional hybrid rehearsal cabinet')
        Membership.objects.create(organization=cabinet, user=self.editor, role='owner')
        before = dict(self.client.session)
        self.assertNotIn('organization', before)
        with CaptureQueriesContext(connection) as queries:
            page = self.open_page(guide_language='ar')
            response = self.client.post(self.url, self.choices(page), secure=True)
        self.assertContains(response, 'data-rehearsal-summary')
        self.assertEqual(dict(self.client.session), before)
        writes = [query['sql'] for query in queries if query['sql'].lstrip().split(None, 1)[0].upper()
                  in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'MERGE'}]
        self.assertEqual(writes, [])

    def test_free_and_observation_rehearsals_use_the_corresponding_structured_choices(self):
        self.activity.requested_target = ''
        self.activity.response_mode = 'free'
        self.activity.save(update_fields=['response_mode', 'requested_target'])
        free = self.open_page()
        self.assertContains(free, 'data-response-mode="free"')
        self.assertNotContains(free, 'class="target"')
        result = self.client.post(self.url, self.choices(free, answer='b'), secure=True)
        self.assertEqual(result.context['summary']['answer'], self.activity.word_b)

        self.activity.response_mode = 'observation'
        self.activity.save(update_fields=['response_mode'])
        observation = self.open_page()
        self.assertContains(observation, 'data-response-mode="observation"')
        self.assertNotContains(observation, 'name="answer"')
        payload = self.choices(observation)
        del payload['answer']
        result = self.client.post(self.url, payload, secure=True)
        self.assertContains(result, 'data-rehearsal-summary')
        self.assertEqual(result.context['summary']['answer'], '—')

    def assert_stale_snapshot(self, response):
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'data-rehearsal-summary', status_code=409)
        self.assertNotContains(response, 'name="rehearsal_snapshot"', status_code=409)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_replay_fails_on_actor_version_language_change_expiry_or_edited_content(self):
        page = self.open_page(guide_language='en')
        another_actor = Client()
        another_actor.force_login(self.reviewer)
        self.assert_stale_snapshot(another_actor.post(self.url, self.choices(page), secure=True))
        self.assert_stale_snapshot(self.client.post(
            reverse('editorial_rehearsal', args=[self.newer.pk]), self.choices(page), secure=True))
        self.assert_stale_snapshot(self.client.post(self.url, self.choices(page, guide_language='fr'), secure=True))
        with patch.object(signing.time, 'time', return_value=(timezone.now() + timedelta(seconds=MAX_AGE + 1)).timestamp()):
            self.assert_stale_snapshot(self.client.post(self.url, self.choices(page), secure=True))
        self.activity.instructions = {**self.activity.instructions, 'en': 'UPDATED-FICTIONAL-INSTRUCTIONS'}
        self.activity.save(update_fields=['instructions'])
        self.assert_stale_snapshot(self.client.post(self.url, self.choices(page), secure=True))
        fresh_page = self.open_page(guide_language='en')
        self.assertContains(self.client.post(self.url, self.choices(fresh_page), secure=True), 'data-rehearsal-summary')

    def test_only_exact_available_recordings_and_images_enter_rehearsal(self):
        image = BytesIO()
        Image.new('RGB', (32, 32), 'teal').save(image, 'PNG')
        illustration = MediaAsset.objects.create(
            uploaded_by=self.editor, kind='image', rights='Fictional unapproved image',
            file=ContentFile(image.getvalue(), name='rehearsal.png'))
        exact = self.audio_asset('exact.wav', self.activity.word_a, self.darja.code)
        wrong_scope = self.audio_asset('wrong-scope.wav', self.activity.word_b, self.msa.code)
        wrong_text = self.audio_asset('wrong-text.wav', self.activity.word_a, self.darja.code)
        self.activity.image_a = media_reference(illustration)
        self.activity.audio_a = media_reference(exact)
        for rejected in [wrong_scope, wrong_text]:
            with self.subTest(asset=rejected.file.name):
                self.activity.audio_b = media_reference(rejected)
                self.activity.save(update_fields=['image_a', 'audio_a', 'audio_b'])
                page = self.open_page()
                self.assertContains(page, reverse('editorial_media', args=[illustration.pk]))
                self.assertContains(page, reverse('editorial_media', args=[exact.pk]))
                self.assertNotContains(page, reverse('editorial_media', args=[rejected.pk]))
                self.assertEqual(page.context['audio'], '')
        signed_media = reverse('editorial_media', args=[exact.pk])
        media = self.client.get(signed_media, secure=True, HTTP_RANGE='bytes=0-43')
        self.assertEqual(media.status_code, 206)
        self.assertEqual(media.content, pcm_fixture()[:44])
        self.assertIn('no-store', media.headers['Cache-Control'])
        denied = Client()
        denied.force_login(self.other_editor)
        self.assertEqual(denied.get(signed_media, secure=True).status_code, 404)

        self.assertFalse(self.activity.media_manifest)
        original_digest = self.activity.fingerprint()
        exact.file.storage.delete(exact.file.name)
        self.assertEqual(self.activity.fingerprint(), original_digest)
        self.assert_stale_snapshot(self.client.post(self.url, self.choices(page), secure=True))

        illustration.revoked = True
        illustration.revocation_reason = 'Technical fixture for withdrawal'
        illustration.save(update_fields=['revoked', 'revocation_reason'])
        page = self.open_page()
        self.assertNotContains(page, reverse('editorial_media', args=[illustration.pk]))
        self.assertNotContains(page, signed_media)
        self.assertContains(page, 'Illustration unavailable')

    def audio_asset(self, name, text, variety):
        return MediaAsset.objects.create(uploaded_by=self.editor, kind='audio',
            rights='Technical fixture without a speech model', file=ContentFile(pcm_fixture(), name=name),
            provenance={'audio': {'source': 'synthetic', 'text': text, 'variety': variety}})
