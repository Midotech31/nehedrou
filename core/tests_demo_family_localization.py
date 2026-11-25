"""Language regression for the assigned cat/dog activity in the family demo."""

import uuid
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.core import signing
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from care.models import Child, FamilyLink, PracticeSession, ProgramItem
from catalog.content_catalog import public_example
from catalog.models import Activity
from core.management.commands.seed_demo_roles import MSA_CODE, ROLE_PRACTICE_ID
from core.models import User
from core.tests_demo_roles import seed
from core.tests_practice_guidance import DOMTree


@override_settings(
    DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class DemoFamilyLocalizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed()
        cls.caregiver = User.objects.get(username='accompagnant')
        cls.program = Child.objects.get(
            organization_id=ROLE_PRACTICE_ID, code='Sami · fictif',
        ).programs.get(variety__code=MSA_CODE)
        cls.source = public_example('ar', MSA_CODE)
        cls.activity = Activity.objects.get(
            series=uuid.uuid5(uuid.NAMESPACE_URL, 'demo:' + cls.source['series']),
            version=cls.source['version'], is_demo=True, state='published',
        )
        cls.item = ProgramItem.objects.create(program=cls.program, activity=cls.activity, position=2)

    def setUp(self):
        self.client.force_login(self.caregiver)

    @staticmethod
    def route(language, name, pk=None):
        with translation.override(language):
            return reverse(name, args=[pk] if pk is not None else None)

    @staticmethod
    def normalize(text):
        return ' '.join(text.split())

    def assert_document_language(self, response, language):
        self.assertEqual(response.status_code, 200)
        dom = DOMTree(response)
        root = next(node for node in dom.nodes if node['tag'] == 'html')
        self.assertEqual(root['attrs']['lang'], language)
        self.assertEqual(root['attrs']['dir'], 'rtl' if language == 'ar' else 'ltr')
        return dom

    def assert_guide_fields(self, dom, language, fields):
        guide = self.source['practice_guide'][language]
        direction = 'rtl' if language == 'ar' else 'ltr'
        passages = {
            self.normalize(dom.text(node))
            for node in dom.nodes
            if node['attrs'].get('lang') == language and node['attrs'].get('dir') == direction
        }
        document = self.normalize(dom.text(dom.root))
        for field in fields:
            with self.subTest(guide_language=language, field=field):
                values = guide[field] if isinstance(guide[field], list) else [guide[field]]
                for value in values:
                    self.assertIn(self.normalize(value), passages)
                for other_language, other_guide in self.source['practice_guide'].items():
                    if other_language == language:
                        continue
                    other_values = other_guide[field] if isinstance(other_guide[field], list) else [other_guide[field]]
                    for value in other_values:
                        if value not in values:
                            self.assertNotIn(self.normalize(value), document)

    def test_exact_activity_body_and_caregiver_routes_follow_the_interface(self):
        self.assertEqual((self.activity.word_a, self.activity.word_b), ('قط', 'كلب'))
        self.assertTrue(self.caregiver.instruction_language_follows_interface)
        full_guide = ('objective', 'audience', 'discover', 'listen', 'exchange', 'support', 'limits', 'review_notes')
        for language in ('fr', 'en', 'ar'):
            for route, pk, fields in (
                ('practice', self.item.pk, full_guide),
                ('program_detail', self.program.pk, full_guide),
                ('activity_detail', self.activity.pk, full_guide),
                ('print_program', self.program.pk, ('objective', 'listen', 'exchange', 'support')),
            ):
                with self.subTest(language=language, route=route):
                    page = self.client.get(self.route(language, route, pk))
                    dom = self.assert_document_language(page, language)
                    self.assert_guide_fields(dom, language, fields)
                    if route == 'practice':
                        with translation.override(language):
                            self.assertEqual(dom.find('data-guided-activity')['attrs']['data-report-label'],
                                             translation.gettext('Parent report'))
                            self.assertEqual(dom.find('data-activity-step', '2')['attrs']['data-title'],
                                             translation.gettext('Listen and choose'))
        self.caregiver.refresh_from_db()
        self.assertTrue(self.caregiver.instruction_language_follows_interface)
        self.assertEqual(self.caregiver.instruction_language, 'fr')

    def test_fixed_french_is_respected_until_following_interface_is_reenabled(self):
        settings_page = self.route('ar', 'preferences')
        exercise = self.route('ar', 'practice', self.item.pk)
        choose_french = self.client.post(settings_page, {
            'instruction_language': 'fr', 'next': 'https://outside.example/ignore',
        })
        self.assertRedirects(choose_french, settings_page, fetch_redirect_response=False)
        self.caregiver.refresh_from_db()
        self.assertFalse(self.caregiver.instruction_language_follows_interface)
        self.assertEqual(self.caregiver.instruction_language, 'fr')
        dom = self.assert_document_language(self.client.get(exercise), 'ar')
        self.assert_guide_fields(dom, 'fr', ('objective', 'audience', 'discover', 'listen'))

        follow_interface = self.client.post(settings_page, {
            'instruction_language': 'fr', 'instruction_language_follows_interface': 'on', 'next': exercise,
        })
        self.assertRedirects(follow_interface, exercise, fetch_redirect_response=False)
        self.caregiver.refresh_from_db()
        self.assertTrue(self.caregiver.instruction_language_follows_interface)
        self.assertEqual(self.caregiver.instruction_language, 'fr')
        dom = self.assert_document_language(self.client.get(exercise), 'ar')
        self.assert_guide_fields(dom, 'ar', ('objective', 'audience', 'discover', 'listen'))

    def test_switching_languages_during_a_run_preserves_task_and_report(self):
        start = self.client.post(self.route('fr', 'practice_run_start', self.program.pk), follow=True)
        self.assertEqual(start.status_code, 200)
        first_path = start.context['resume_url']
        first_page = self.client.get(first_path)
        first_ticket = first_page.context['form'].initial['ticket']
        first_report = self.client.post(first_path, {
            'ticket': first_ticket, 'answer': signing.loads(first_ticket, salt='practice')['target'],
            'completion': 'completed', 'parent_report': 'easy',
        }, follow=True)
        self.assertEqual(first_report.status_code, 200)
        french_path = first_report.context['next_task_url']
        self.assertTrue(french_path.startswith(self.route('fr', 'practice', self.item.pk) + '?task='))
        active_task_url = self.client.post(reverse('set_language'), {'language': 'ar', 'next': french_path})
        arabic_path = self.route('ar', 'practice', self.item.pk) + '?' + french_path.split('?', 1)[1]
        self.assertRedirects(active_task_url, arabic_path, fetch_redirect_response=False)

        french_ticket = self.client.get(french_path).context['form'].initial['ticket']
        arabic_page = self.client.get(arabic_path)
        dom = self.assert_document_language(arabic_page, 'ar')
        self.assert_guide_fields(dom, 'ar', ('objective', 'audience', 'listen', 'support'))
        arabic_ticket = arabic_page.context['form'].initial['ticket']
        self.assertEqual(signing.loads(arabic_ticket, salt='practice'), signing.loads(french_ticket, salt='practice'))
        answer = signing.loads(arabic_ticket, salt='practice')['target']
        result = self.client.post(arabic_path, {
            'ticket': arabic_ticket, 'answer': answer, 'completion': 'completed', 'parent_report': 'easy',
        }, follow=True)
        self.assert_document_language(result, 'ar')
        with translation.override('ar'):
            self.assertContains(result, translation.gettext('Thank you for practicing together'))
        report = PracticeSession.objects.get(user=self.caregiver, item=self.item)
        self.assertEqual(report.item.activity_id, self.activity.pk)
        self.assertEqual(report.run_task.run.state, 'completed')

    def test_missing_selected_instructions_explain_the_problem_in_arabic(self):
        Activity.objects.filter(pk=self.activity.pk).update(instructions={
            'fr': self.source['instructions']['fr'], 'en': self.source['instructions']['en'],
        })
        response = self.client.get(self.route('ar', 'practice', self.item.pk))
        with translation.override('ar'):
            self.assertContains(response, translation.gettext('Instructions unavailable'), status_code=409)
        self.assertNotContains(response, self.source['instructions']['fr'], status_code=409)
        self.assertNotContains(response, 'data-guided-activity', status_code=409)

    def test_known_demo_program_notes_are_localized_without_changing_stored_text(self):
        fields = ('title', 'goal', 'guidance', 'schedule')
        stored = {field: getattr(self.program, field) for field in fields}
        for language in ('en', 'ar'):
            with self.subTest(language=language):
                page = self.client.get(self.route(language, 'program_detail', self.program.pk))
                dom = self.assert_document_language(page, language)
                for content in stored.values():
                    self.assertNotIn(self.normalize(content), self.normalize(dom.text(dom.root)))
        self.program.refresh_from_db()
        self.assertEqual(stored, {field: getattr(self.program, field) for field in fields})
        self.program.guidance = 'Relire les indications avant la prochaine séance fictive.'
        self.program.save(update_fields=['guidance'])
        page = self.client.get(self.route('ar', 'program_detail', self.program.pk))
        self.assertContains(page, self.program.guidance)

    def test_upgrade_only_enables_eligible_demo_caregivers(self):
        migration = import_module('core.migrations.0014_instruction_language_follows_interface')
        editor = SimpleNamespace(connection=connection)
        legacy = User.objects.get(username='famille')
        users = User.objects.filter(pk__in=(self.caregiver.pk, legacy.pk))
        self.assertTrue(legacy.instruction_language_follows_interface)
        users.update(instruction_language_follows_interface=False)

        with override_settings(DEMO_MODE=False):
            migration.follow_interface_for_demo_families(apps, editor)
        self.assertFalse(users.filter(instruction_language_follows_interface=True).exists())

        User.objects.filter(pk=self.caregiver.pk).update(instruction_language='en')
        outside_practice = Child.objects.get(code='Profil B · fictif')
        outside_link = FamilyLink.objects.create(child=outside_practice, user=legacy)
        migration.follow_interface_for_demo_families(apps, editor)
        self.assertFalse(users.filter(instruction_language_follows_interface=True).exists())

        outside_link.delete()
        migration.follow_interface_for_demo_families(apps, editor)
        self.assertEqual(list(users.filter(instruction_language_follows_interface=True)), [legacy])
        self.caregiver.refresh_from_db()
        self.assertEqual(self.caregiver.instruction_language, 'en')
