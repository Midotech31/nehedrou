"""Private fixed-object diagnostics: no cloud, child data, email or file mutation."""
import json
import tempfile
from unittest.mock import patch
from django.contrib.auth.models import Permission
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import Client, TestCase, override_settings
from core.models import User
from core.technical_storage_probe import PROBE_KEY, PROBE_BODY, PROBE_SHA256


@override_settings(MFA_REQUIRED=False, DEMO_MODE=True, MEDIA_STORAGE_BACKEND='filesystem')
class TechnicalStorageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = User.objects.create_user('storage-operator', 'storage-operator@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.ordinary = User.objects.create_user('storage-ordinary', 'storage-ordinary@example.test')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        configured = override_settings(MEDIA_ROOT=temporary.name, STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        configured.enable()
        self.addCleanup(configured.disable)
        self.client.force_login(self.operator)

    def put_fixture(self, body=PROBE_BODY):
        self.assertEqual(default_storage.save(PROBE_KEY, ContentFile(body)), PROBE_KEY)

    def test_post_reads_only_expected_technical_content_and_never_writes_or_sends(self):
        self.put_fixture()
        with patch.object(default_storage, 'save') as save, patch.object(default_storage, 'delete') as delete, patch('django.core.mail.send_mail') as send:
            response = self.client.post('/fr/operations/?format=json', {'action': 'storage'})
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertTrue(report['storage']['ok'])
        self.assertTrue(report['storage']['expected_content_verified'])
        self.assertEqual(report['storage']['bytes_read'], len(PROBE_BODY))
        self.assertFalse(report['database']['requested'])
        self.assertFalse(report['email']['network_attempted'])
        self.assertEqual(report['execution']['delivery'], 'authenticated_private_web_view')
        for value in [PROBE_KEY, PROBE_BODY.decode(), PROBE_SHA256]:
            self.assertNotIn(value, response.content.decode())
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        save.assert_not_called(); delete.assert_not_called(); send.assert_not_called()

    def test_missing_or_changed_object_is_not_a_success_or_an_echo_of_its_content(self):
        absent = self.client.post('/en/operations/?format=json', {'action': 'storage'})
        self.assertEqual(absent.status_code, 200)
        self.assertFalse(absent.json()['storage']['ok'])
        self.assertFalse(absent.json()['storage']['expected_content_verified'])
        private_content = b'NOT-THE-EXPECTED-OBJECT-CONTENT'
        self.put_fixture(private_content)
        changed = self.client.post('/en/operations/?format=json', {'action': 'storage'})
        self.assertFalse(changed.json()['storage']['ok'])
        self.assertFalse(changed.json()['storage']['expected_content_verified'])
        for value in [private_content.decode(), PROBE_KEY]:
            self.assertNotIn(value, changed.content.decode())

    def test_get_head_and_query_actions_do_not_read_or_create_the_probe(self):
        with patch('core.ops_readiness.storage_probe') as storage, patch('core.ops_readiness.database_probe') as database, patch.object(default_storage, 'save') as save:
            for method in ('get', 'head'):
                response = getattr(self.client, method)('/ar/operations/?format=json&action=storage&key=private/anything')
                self.assertEqual(response.status_code, 200)
                if method == 'get': self.assertFalse(response.json()['storage']['requested'])
            storage.assert_not_called(); database.assert_not_called(); save.assert_not_called()

    def test_client_cannot_choose_storage_key_url_hash_or_recipient(self):
        with patch('core.ops_readiness.storage_probe') as storage:
            for name, value in [('key', 'private_evidence/patient-file'), ('storage_object', '../private'),
                                ('url', 'https://untrusted.example'), ('expected_sha256', '0'*64),
                                ('recipient', 'other@example.test')]:
                with self.subTest(field=name):
                    response = self.client.post('/fr/operations/?format=json', {'action': 'storage', name: value})
                    self.assertEqual(response.status_code, 400)
            storage.assert_not_called()

    def test_fixed_key_and_expected_hash_are_server_selected(self):
        sample = {'requested': True, 'ok': True, 'expected_content_verified': True,
                  'bytes_read': len(PROBE_BODY), 'elapsed_ms': 4.25, 'backend': 'filesystem'}
        with patch('core.ops_readiness.storage_probe', return_value=sample) as storage:
            response = self.client.post('/en/operations/?format=json', {'action': 'storage'})
        self.assertEqual(response.status_code, 200)
        storage.assert_called_once_with(PROBE_KEY, expected_sha256=PROBE_SHA256)

    def test_storage_post_keeps_role_csrf_and_real_privileged_mfa_requirements(self):
        with patch('core.ops_readiness.storage_probe') as storage:
            self.client.force_login(self.ordinary)
            self.assertEqual(self.client.post('/fr/operations/', {'action': 'storage'}).status_code, 403)
            protected = Client(enforce_csrf_checks=True)
            protected.force_login(self.operator)
            self.assertEqual(protected.post('/fr/operations/', {'action': 'storage'}).status_code, 403)
            self.client.force_login(self.operator)
            with override_settings(MFA_REQUIRED=True):
                response = self.client.post('/fr/operations/', {'action': 'storage'})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Location'], '/fr/security/setup/')
            storage.assert_not_called()

    def test_sample_ui_in_each_language_does_not_claim_durability_or_email_delivery(self):
        self.put_fixture()
        for language in ('fr', 'en', 'ar'):
            with self.subTest(language=language):
                response = self.client.post('/'+language+'/operations/', {'action': 'storage'})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="action" value="storage"')
                self.assertTrue(response.context['report']['storage']['expected_content_verified'])
                self.assertFalse(response.context['report']['email']['delivery_verified'])
                self.assertContains(response, 'Designed by Benabdeloued Mohamed Alias Pitou')
                self.assertNotContains(response, PROBE_KEY)
                self.assertNotIn('children', response.context)
