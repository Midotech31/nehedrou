"""Private operator observation history with fictional metadata only."""
import io
import json
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.models import AuditEvent, OperatorAcceptanceObservation, User
from core.ops_readiness import OPERATOR_ACCEPTANCE_REQUIRED, operator_acceptance_report


REGISTER = '/en/operations/readiness/evidence/'
REPORT = '/en/operations/readiness/'


@override_settings(MFA_REQUIRED=False, DEMO_MODE=True, SECURE_SSL_REDIRECT=False)
class OperatorEvidenceRegisterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = User.objects.create_user('ops-evidence-operator', 'ops-operator@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.register_manager = User.objects.create_user('register-evidence-manager', 'register-manager@example.test')
        cls.register_manager.user_permissions.add(Permission.objects.get(codename='manage_processing_register'))
        cls.ordinary = User.objects.create_user('ops-evidence-ordinary', 'ordinary@example.test')
        cls.staff = User.objects.create_user('ops-evidence-staff', 'staff@example.test', is_staff=True)

    def data(self, **kwargs):
        return {
            'check': 'recent_restore_and_dossier_access',
            'scope': 'local_fictional',
            'outcome': 'completed',
            'observed_on': timezone.localdate().isoformat(),
            'evidence_sha256': 'A' * 64,
            **kwargs,
        }

    def record(self, **kwargs):
        response = self.client.post(REGISTER, self.data(**kwargs))
        self.assertRedirects(response, REGISTER, fetch_redirect_response=False)
        self.assertIn('no-store', response['Cache-Control'])

    def test_permission_post_only_and_csrf(self):
        self.assertRedirects(self.client.get(REGISTER), '/en/login/?next=/en/operations/readiness/evidence/',
                             fetch_redirect_response=False)
        for actor in (self.register_manager, self.ordinary, self.staff):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                self.assertEqual(self.client.get(REGISTER).status_code, 403)
                self.assertEqual(self.client.post(REGISTER, self.data()).status_code, 403)
        self.client.force_login(self.operator)
        response = self.client.get(REGISTER)
        self.assertContains(response, 'id="operator-evidence-form"')
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(self.client.put(REGISTER, self.data()).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.operator)
        self.assertEqual(strict.post(REGISTER, self.data()).status_code, 403)
        self.assertFalse(OperatorAcceptanceObservation.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    @override_settings(MFA_REQUIRED=True)
    def test_existing_mfa_gate_covers_read_and_write(self):
        self.client.force_login(self.operator)
        self.assertRedirects(self.client.get(REGISTER), '/en/security/setup/', fetch_redirect_response=False)
        self.assertRedirects(self.client.post(REGISTER, self.data()), '/en/security/setup/',
                             fetch_redirect_response=False)
        self.assertFalse(OperatorAcceptanceObservation.objects.exists())

    def test_invalid_and_unlisted_inputs_never_record_or_audit(self):
        self.client.force_login(self.operator)
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        cases = (
            ('check', 'clinical_approval'), ('scope', 'https://private.example/'),
            ('outcome', ''), ('observed_on', tomorrow), ('observed_on', '24.11.2026'),
            ('evidence_sha256', '4' * 63), ('evidence_sha256', 'Z' * 64),
            ('note', 'unsupported unstructured fields'),
            ('file', SimpleUploadedFile('fictional.txt', b'fictional only')),
        )
        for field, value in cases:
            with self.subTest(field=field):
                response = self.client.post(REGISTER, self.data(**{field: value}))
                self.assertEqual(response.status_code, 400)
                self.assertIn(field if field in self.data() else '__all__', response.context['form'].errors)
        self.assertFalse(OperatorAcceptanceObservation.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_append_only_history_audit_and_latest_by_observed_date_and_scope(self):
        self.client.force_login(self.operator)
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.record(observed_on=yesterday)
        self.record(evidence_sha256='B' * 64, outcome='gap_found')
        self.record(observed_on=yesterday, evidence_sha256='C' * 64)
        self.record(scope='hosted_demo', evidence_sha256='D' * 64)
        self.record(scope='target_service', check='live_email_delivery', outcome='gap_found', evidence_sha256='E' * 64)
        observations = OperatorAcceptanceObservation.objects.all()
        self.assertEqual(observations.count(), 5)
        normalized = observations.get(evidence_sha256='a' * 64)
        self.assertEqual(normalized.recorded_by, self.operator)
        normalized.outcome = 'gap_found'
        with self.assertRaises(ValidationError):
            normalized.save()
        with self.assertRaises(ValidationError):
            normalized.delete()
        normalized.refresh_from_db()
        self.assertEqual(normalized.outcome, 'completed')

        actions = AuditEvent.objects.filter(action='operations.acceptance_observation_recorded')
        self.assertEqual(actions.count(), 5)
        self.assertEqual(set(actions.values_list('object_id', flat=True)), {str(row.pk) for row in observations})
        self.assertEqual(set(actions.values_list('actor_id', 'organization_id', 'purpose_code')),
                         {(self.operator.pk, None, 'other')})

        history = self.client.get(REGISTER)
        self.assertContains(history, 'id="operator-evidence-history"')
        for expected in 'abcde':
            self.assertContains(history, expected * 64)
        summary = self.client.get(REPORT)
        self.assertContains(summary, 'Operator acceptance still required')
        self.assertContains(summary, 'id="operator-evidence-register-link"')
        self.assertContains(summary, 'id="recorded-operator-observations"')
        for superseded in 'ac':
            self.assertNotContains(summary, superseded * 64)
        for expected in 'bde':
            self.assertContains(summary, expected * 64)

        response = self.client.get(REPORT + '?format=json')
        self.assertIn('no-store', response['Cache-Control'])
        payload = response.json()
        self.assertEqual(payload['operator_acceptance'], operator_acceptance_report())
        records = payload['operator_acceptance_observations']
        self.assertCountEqual(
            [(row['check'], row['scope'], row['outcome'], row['evidence_sha256']) for row in records], [
                ('recent_restore_and_dossier_access', 'local_fictional', 'gap_found', 'b' * 64),
                ('recent_restore_and_dossier_access', 'hosted_demo', 'completed', 'd' * 64),
                ('live_email_delivery', 'target_service', 'gap_found', 'e' * 64),
            ],
        )
        self.assertTrue(all(set(row) == {'check', 'scope', 'outcome', 'observed_on', 'evidence_sha256', 'recorded_at'}
                            for row in records))
        self.assertNotContains(response, self.operator.email)
        self.assertNotContains(response, self.operator.username)

    def test_recording_reported_success_for_all_eight_checks_cannot_approve_launch(self):
        def readiness():
            out = io.StringIO()
            with self.assertRaisesMessage(CommandError, 'Technical launch gates are not met.'):
                call_command('check_readiness', json=True, strict=True, stdout=out)
            return json.loads(out.getvalue())

        self.client.force_login(self.operator)
        before = readiness()
        page = self.client.get(REGISTER)
        self.assertEqual([value for value, _label in page.context['form'].fields['check'].choices if value],
                         list(OPERATOR_ACCEPTANCE_REQUIRED))
        for check_code in OPERATOR_ACCEPTANCE_REQUIRED:
            self.record(check=check_code, scope='target_service')
        after = readiness()
        for key in ('technical_gates_passed', 'checks', 'manual_gates_required', 'operator_acceptance'):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after['operator_acceptance']['status'], 'not_evaluated')
        self.assertFalse(after['technical_gates_passed'])
        self.assertFalse(after['email']['delivery_verified'])

    def test_register_and_summary_are_localized(self):
        self.client.force_login(self.operator)
        self.record(scope='hosted_demo')
        for language, direction, title, scope in (
            ('fr', 'ltr', 'Registre des preuves d’exploitation', 'Démonstration hébergée'),
            ('en', 'ltr', 'Operator evidence register', 'Hosted demonstration'),
            ('ar', 'rtl', 'سجل الأدلة التشغيلية', 'العرض التجريبي المستضاف'),
        ):
            with self.subTest(language=language):
                page = self.client.get(f'/{language}/operations/readiness/evidence/')
                self.assertContains(page, title)
                self.assertContains(page, f'<html lang="{language}" dir="{direction}">')
                report = self.client.get(f'/{language}/operations/readiness/')
                self.assertContains(report, scope)
                self.assertContains(report, 'dir="ltr">' + 'a' * 64 + '</bdi>')
