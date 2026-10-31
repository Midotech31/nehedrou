import json
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from core.models import AuditEvent, ProcessingActivity, ProcessingActivityRevision, User


class ProcessingRegisterAdminTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_user(
            username='processing-register-operator', email='operator@fictional.example', password='Fictional-Test-Only-123!', is_staff=True)
        self.operator.user_permissions.add(Permission.objects.get(codename='manage_processing_register'))
        self.client.force_login(self.operator)

    def payload(self):
        return {
            'organization': '',
            'register_capacity': 'controller',
            'name': 'Fictional service processing',
            'controller_name': 'Fictional operator',
            'controller_contact': 'privacy@fictional.example',
            'data_protection_contact': '',
            'purposes': 'Fictional purposes pending legal review',
            'legal_basis': 'To be confirmed by qualified counsel',
            'data_subject_categories': 'Fictional users and child profiles',
            'personal_data_categories': 'Fictional account and service records',
            'recipient_categories': 'Fictional hosting provider in Germany',
            'international_transfers': 'None identified in the fictional fixture; verify before use',
            'retention_periods': 'To be set by the operator after legal review',
            'security_measures': 'Fictional access control and encryption summary',
            'operations': 'Collection, storage, consultation, correction, restriction and deletion',
            'active': 'on',
        }

    def test_authorized_operator_can_create_and_update_register_with_audit_events(self):
        add_url = reverse('processing_register')
        response = self.client.post(add_url, self.payload())
        self.assertEqual(response.status_code, 302)
        record = ProcessingActivity.objects.get(name='Fictional service processing')
        self.assertEqual(record.created_by_id, self.operator.pk)
        self.assertEqual(record.updated_by_id, self.operator.pk)
        created = AuditEvent.objects.get(action='privacy.register_activity_created', object_id=str(record.pk))
        self.assertEqual(created.actor_id, self.operator.pk)
        self.assertEqual(created.purpose_code, 'data_rights')
        self.assertIsNone(created.organization_id)

        edit_url = reverse('processing_register_edit', args=[record.pk])
        payload = self.payload()
        payload['name'] = 'Fictional service processing v2'
        response = self.client.post(edit_url, payload)
        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.name, 'Fictional service processing v2')
        self.assertEqual(AuditEvent.objects.filter(action='privacy.register_activity_updated', object_id=str(record.pk)).count(), 1)
        revisions = list(record.revisions.order_by('revision'))
        self.assertEqual([revision.revision for revision in revisions], [1, 2])
        self.assertEqual(revisions[0].snapshot['name'], 'Fictional service processing')
        self.assertEqual(revisions[1].snapshot['name'], 'Fictional service processing v2')
        self.assertEqual(revisions[1].changed_by_id, self.operator.pk)
        with self.assertRaises(ValidationError):
            revisions[0].delete()

    def test_authorized_operator_can_read_and_download_register_with_access_audit(self):
        payload = self.payload()
        payload['organization'] = None
        payload.pop('active')
        record = ProcessingActivity.objects.create(**payload)

        page = self.client.get(reverse('processing_register'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Registre des traitements')
        event = AuditEvent.objects.get(action='privacy.register_activity_consulted', object_id=str(record.pk))
        self.assertEqual(event.actor_id, self.operator.pk)
        self.assertEqual(event.purpose_code, 'data_rights')

        response = self.client.get(reverse('processing_register') + '?format=json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        data = json.loads(response.content)
        self.assertEqual(data['entries'][0]['id'], str(record.pk))
        self.assertEqual(data['entries'][0]['controller_contact'], 'privacy@fictional.example')

    def test_user_without_explicit_permission_cannot_access_register(self):
        self.client.force_login(User.objects.create_user(
            username='unprivileged-register-user', email='unprivileged@fictional.example', password='Fictional-Test-Only-123!'))
        response = self.client.get(reverse('processing_register'))
        self.assertEqual(response.status_code, 403)

    def test_register_only_operator_gets_the_scoped_link_without_clinical_or_billing_links(self):
        operator = User.objects.create_user(username='register-nav-only', email='register-nav-only@fictional.example')
        operator.user_permissions.add(Permission.objects.get(codename='manage_processing_register'))
        self.client.force_login(operator)
        response = self.client.get(reverse('processing_register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('processing_register'))
        self.assertNotRegex(response.content.decode(), r'href="/fr/operations/"')
        self.assertNotContains(response, reverse('children'))
        self.assertNotContains(response, reverse('billing_index'))

    def test_register_interface_renders_in_all_languages_and_arabic_rtl(self):
        for code, label in [('fr', 'Registre des traitements'), ('en', 'Processing register'), ('ar', 'سجل المعالجة')]:
            with translation.override(code):
                response = self.client.get(f'/{code}/operations/register/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, f'<html lang="{code}"')
            self.assertContains(response, label)
            if code == 'ar':
                self.assertContains(response, 'dir="rtl"')

    @override_settings(MFA_REQUIRED=True)
    def test_processing_register_privilege_alone_requires_mfa(self):
        operator = User.objects.create_user(
            username='register-only-operator', email='register-only@fictional.example')
        operator.user_permissions.add(Permission.objects.get(codename='manage_processing_register'))
        self.client.force_login(operator)
        response = self.client.get(reverse('processing_register'))
        self.assertRedirects(response, reverse('mfa_setup'), fetch_redirect_response=False)

    def test_register_entries_cannot_be_deleted_from_admin(self):
        payload = self.payload()
        payload['organization'] = None
        payload.pop('active')
        record = ProcessingActivity.objects.create(**payload)
        response = self.client.get(reverse('admin:core_processingactivity_delete', args=[record.pk]))
        self.assertEqual(response.status_code, 403)

