"""Exact spoken-variety launch coverage, using fictional software fixtures only."""
import io
import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from catalog.models import Activity, Variety
from catalog.services import transition
from core.models import User
from core.management.commands.check_readiness import DEFAULT_OFFERED_CONTENT_VARIETIES
from qualification.test_support import prepare_activity_fixture, availability_fixture


@override_settings(DEMO_MODE=False, DEBUG=False, DEMO_EPHEMERAL=False,
    MFA_REQUIRED=True, MEDIA_STORAGE_DURABLE=True, MEDIA_STORAGE_BACKEND='filesystem',
    MEDIA_ROOT='E:/LocalCoderWorkspace/Nehdrou/work/oct30-media-tmp/readiness-media',
    PUBLIC_ORIGIN='https://fictional.example',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class SpokenVarietyReadinessTests(TestCase):
    def setUp(self):
        self.varieties = {code: Variety.objects.create(code=code, language=code[:2], label='Fictional '+code)
            for code in DEFAULT_OFFERED_CONTENT_VARIETIES}
        self.editor = User.objects.create_user(username='coverage-clinical', email='coverage-clinical@example.test')
        self.linguist = User.objects.create_user(username='coverage-linguist', email='coverage-linguist@example.test')

    def content(self, code, *, available=True):
        activity = Activity.objects.create(variety=self.varieties[code], series=uuid.uuid4(),
            title='Fictional coverage fixture', word_a='pa', word_b='ba', contrast='p/b',
            instructions={'fr':'Fictif', 'en':'Fictional', 'ar':'مثال'},
            population='Fictional software fixture', rights='Fictional rights only', is_demo=False)
        prepare_activity_fixture(activity, self.editor, self.linguist)
        transition(self.editor, activity.pk, 'approved')
        activity = transition(self.editor, activity.pk, 'published')
        if available:
            availability_fixture('practice', activity.variety, activity.fingerprint(), self.editor)
        return activity

    def report(self, *, strict=False, offered=None):
        output = io.StringIO()
        with patch('core.management.commands.check_readiness.connection', SimpleNamespace(vendor='postgresql')), patch('core.management.commands.check_readiness.smtp_configuration', return_value={'configured':True}), patch('core.management.commands.check_readiness.email_configuration', return_value={'configured':True}), patch('core.management.commands.check_readiness.offered_content_varieties', return_value=tuple(DEFAULT_OFFERED_CONTENT_VARIETIES if offered is None else offered)):
            call_command('check_readiness', json=True, strict=strict, stdout=output)
        return json.loads(output.getvalue())

    def test_msa_never_covers_missing_darja_despite_complete_interface_counts(self):
        for code in ('fr-fr-pilot','en-us-general-pilot','ar-msa-pilot'):
            self.content(code)
        report = self.report()
        self.assertEqual(report['published_nondemo_counts'], {'fr':1,'en':1,'ar':1})
        self.assertEqual(report['published_nondemo_counts_by_variety']['ar-dz-pilot'], 0)
        self.assertEqual(report['current_available_nondemo_counts_by_variety']['ar-dz-pilot'], 0)
        self.assertFalse(report['checks']['current_available_nondemo_content_in_each_offered_variety'])
        self.assertFalse(report['technical_gates_passed'])
        with self.assertRaises(CommandError):
            self.report(strict=True)

    def test_publication_without_authorised_availability_does_not_cover_a_variety(self):
        self.content('ar-dz-pilot', available=False)
        report = self.report(offered=('ar-dz-pilot',))
        self.assertEqual(report['published_nondemo_counts_by_variety']['ar-dz-pilot'], 1)
        self.assertEqual(report['current_available_nondemo_counts_by_variety']['ar-dz-pilot'], 0)
        self.assertFalse(report['technical_gates_passed'])

    def test_four_distinct_available_varieties_pass_with_all_other_fixture_gates(self):
        for code in DEFAULT_OFFERED_CONTENT_VARIETIES:
            self.content(code)
        report = self.report(strict=True, offered=DEFAULT_OFFERED_CONTENT_VARIETIES)
        self.assertTrue(report['technical_gates_passed'])
        self.assertEqual(report['published_nondemo_counts']['ar'], 2)
        self.assertEqual(report['current_available_nondemo_counts_by_variety'], {code:1 for code in DEFAULT_OFFERED_CONTENT_VARIETIES})

    def test_explicit_offering_can_be_narrower_than_three_interface_languages(self):
        self.content('fr-fr-pilot')
        report = self.report(strict=True, offered=('fr-fr-pilot',))
        self.assertEqual(report['offered_content_varieties'], ['fr-fr-pilot'])
        self.assertEqual(report['published_nondemo_counts'], {'fr':1,'en':0,'ar':0})
        self.assertTrue(report['technical_gates_passed'])

    def test_unknown_empty_duplicate_or_string_configuration_is_rejected(self):
        for configured in [('ar-missing',), (), ('ar-dz-pilot','ar-dz-pilot'), 'ar-dz-pilot', (None,)]:
            with self.subTest(configured=configured), override_settings(OFFERED_CONTENT_VARIETIES=configured):
                with patch('core.management.commands.check_readiness.offered_content_varieties', wraps=__import__('core.management.commands.check_readiness', fromlist=['offered_content_varieties']).offered_content_varieties):
                    with self.assertRaises(CommandError):
                        call_command('check_readiness', json=True, stdout=io.StringIO())
        self.varieties['ar-dz-pilot'].delete()
        with patch('core.management.commands.check_readiness.offered_content_varieties', wraps=__import__('core.management.commands.check_readiness', fromlist=['offered_content_varieties']).offered_content_varieties):
            with self.assertRaisesMessage(CommandError, 'ar-dz-pilot'):
                call_command('check_readiness', json=True, stdout=io.StringIO())

    def test_historical_published_version_cannot_cover_newer_unavailable_version(self):
        old = self.content('ar-dz-pilot')
        newer = Activity.objects.create(variety=old.variety, series=old.series, version=2,
            title='Fictional incomplete newer version', word_a='pa', word_b='ba', contrast='p/b', instructions={'fr':'Fictif'}, is_demo=False)
        Activity.objects.filter(pk=newer.pk).update(state='published')
        report = self.report(offered=('ar-dz-pilot',))
        self.assertEqual(report['published_nondemo_counts_by_variety']['ar-dz-pilot'], 2)
        self.assertEqual(report['current_available_nondemo_counts_by_variety']['ar-dz-pilot'], 0)
        self.assertFalse(report['checks']['current_available_nondemo_content_in_each_offered_variety'])
        old.refresh_from_db()
        self.assertEqual(old.state, 'published')

    def test_published_demo_never_counts_as_offered_real_content(self):
        demo = Activity.objects.create(variety=self.varieties['ar-dz-pilot'], series=uuid.uuid4(),
            title='Fictional demo only', word_a='pa', word_b='ba', contrast='p/b',
            instructions={'fr':'Fictif'}, is_demo=True)
        Activity.objects.filter(pk=demo.pk).update(state='published')
        report = self.report(offered=('ar-dz-pilot',))
        self.assertEqual(report['published_nondemo_counts']['ar'], 0)
        self.assertEqual(report['published_nondemo_counts_by_variety']['ar-dz-pilot'], 0)
        self.assertEqual(report['current_available_nondemo_counts_by_variety']['ar-dz-pilot'], 0)
        self.assertFalse(report['technical_gates_passed'])
