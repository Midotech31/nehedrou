"""Demo child creation requires an explicit fictional-data acknowledgement."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.conf import settings
from care.models import Child
from . import tests as workflow_tests
from .models import AuditEvent
from .testing import practice_form_data


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False)
class DemoFictionalProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        workflow_tests.WorkflowTests.setUpTestData.__func__(cls)

    def setUp(self):
        translation.activate('en')
        self.client.force_login(self.pro)
        self.url = reverse('child_create')
        self.payload = {
            'code': 'Invented test profile',
            'age_years': '5',
            'varieties': [str(self.program.variety.pk)],
        }

    def test_demo_child_form_warns_in_all_locales(self):
        expected = {
            'en': ('Fictional profile code', 'This demonstration is not approved for real records.'),
            'fr': ('Code fictif du profil', 'Cette démonstration n’est pas approuvée pour des dossiers réels.'),
            'ar': ('رمز ملف تجريبي خيالي', 'هذا العرض غير معتمد لحفظ ملفات حقيقية.'),
        }
        for language, phrases in expected.items():
            self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = language
            with translation.override(language):
                localized_url = reverse('child_create')
                response = self.client.get(localized_url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'demo_data_ack')
                for phrase in phrases:
                    self.assertContains(response, phrase)

    def test_server_requires_ack_and_audits_ack_before_creating_demo_profile(self):
        before = Child.objects.count()
        payload = practice_form_data(self.client, self.url, self.payload)
        payload.pop('demo_data_ack')
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Child.objects.count(), before)
        self.assertIn('demo_data_ack', response.context['form'].errors)

        payload = practice_form_data(self.client, self.url, {**self.payload, 'demo_data_ack': 'on'})
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 302)
        child = Child.objects.get(code='Invented test profile')
        event = AuditEvent.objects.get(action='child.demo_fictional_profile_confirmed', object_id=str(child.pk))
        self.assertEqual(event.actor_id, self.pro.pk)
        self.assertEqual(event.organization_id, self.org.pk)

    def test_production_child_form_does_not_require_demo_ack(self):
        with override_settings(DEMO_MODE=False):
            payload = practice_form_data(self.client, self.url, self.payload)
            response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Child.objects.filter(code='Invented test profile').exists())
        self.assertFalse(AuditEvent.objects.filter(action='child.demo_fictional_profile_confirmed').exists())
