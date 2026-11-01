"""Actual private operations views, fictional configuration, no external traffic."""
import io
import json
import os
from unittest.mock import patch
from django.contrib.auth.models import Permission
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from unittest import skipUnless
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from core.models import User
from core.ops_readiness import execution_context, database_probe

@override_settings(MFA_REQUIRED=False, DEMO_MODE=True)
class PrivateOperationsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = User.objects.create_user('ops-fixture', 'ops-fixture@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.ordinary = User.objects.create_user('ordinary-fixture', 'ordinary-fixture@example.test')
        cls.staff = User.objects.create_user('staff-fixture', 'staff-fixture@example.test', is_staff=True)

    def test_authentication_and_explicit_platform_permission_required(self):
        self.assertEqual(self.client.get('/fr/operations/').status_code, 302)
        for user in [self.ordinary, self.staff]:
            self.client.force_login(user)
            for method in ['get', 'post']:
                with patch('core.operations_views.operations_report') as report:
                    response = getattr(self.client, method)('/fr/operations/', {'action': 'database'})
                self.assertEqual(response.status_code, 403)
                report.assert_not_called()

    def test_runtime_configuration_get_does_not_send_or_probe_and_is_private(self):
        self.client.force_login(self.operator)
        with patch('core.ops_readiness.database_probe') as db, patch('core.ops_readiness.storage_probe') as storage, patch('smtplib.SMTP') as smtp:
            response = self.client.get('/fr/operations/?format=json')
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report['execution']['delivery'], 'authenticated_private_web_view')
        self.assertFalse(report['database']['requested'])
        self.assertFalse(report['storage']['requested'])
        self.assertFalse(report['smtp']['network_attempted'])
        self.assertFalse(report['smtp']['delivery_verified'])
        db.assert_not_called(); storage.assert_not_called(); smtp.assert_not_called()
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_launch_readiness_dashboard_is_private_readable_and_uses_the_shared_command(self):
        self.client.force_login(self.operator)
        report = {
            'technical_gates_passed': False,
            'checks': {'current_available_nondemo_content_in_each_offered_variety': False},
            'manual_gates_required': ['professional_content_and_audio_validation', 'reviewer_identity_and_variety_competence_independently_verified'],
            'scope': 'Technical report only.',
            'offered_content_varieties': ['ar-dz-pilot'],
            'published_nondemo_counts_by_variety': {'ar-dz-pilot': 2},
            'current_available_nondemo_counts_by_variety': {'ar-dz-pilot': 0},
            'editorial_pipeline_by_variety': {'ar-dz-pilot': {
                'latest_versions': 4, 'draft': 3, 'review': 1, 'approved': 0,
                'published': 0, 'withdrawn': 0,
                'missing_one_or_more_audio_references': 3,
            }},
            'editorial_pipeline_scope': 'Fictional pipeline report scope.',
            'processing_register': {'active_platform_records': 0, 'populated_platform_records': 0},
            'production_followup': {'original_drafts': 3, 'published_versions': 2, 'available_versions': 0},
        }
        def write_report(command, *, json, stdout):
            self.assertEqual(command, 'check_readiness')
            self.assertTrue(json)
            stdout.write(__import__('json').dumps(report))
        with patch('core.operations_views.call_command', side_effect=write_report) as run:
            response = self.client.get('/fr/operations/readiness/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'].split(';')[0], 'text/html')
        self.assertContains(response, 'ar-dz-pilot')
        self.assertContains(response, 'Suivi éditorial par variété parlée')
        self.assertContains(response, '<td>4</td><td>3</td><td>1</td><td>0</td><td>0</td><td>0</td><td>3</td>', html=False)
        self.assertContains(response, 'Des blocages techniques empêchent le lancement')
        self.assertContains(response, 'Relecture professionnelle des activités et des fichiers audio exacts')
        self.assertContains(response, 'Identité des relecteurs, expertise déclarée et compétence dans la variété parlée vérifiées indépendamment')
        self.assertContains(response, 'Couverture du registre des traitements de la plateforme')
        self.assertContains(response, 'Module de sondes professionnelles')
        self.assertContains(response, '3')
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        run.assert_called_once()

    def test_technical_pass_still_displays_manual_review_gates(self):
        self.client.force_login(self.operator)
        report = {'technical_gates_passed': True, 'checks': {'debug_disabled': True},
                  'manual_gates_required': ['professional_content_and_audio_validation', 'reviewer_identity_and_variety_competence_independently_verified'],
                  'scope': 'Technical report only.'}
        with patch('core.operations_views.call_command', side_effect=lambda command, *, json, stdout: stdout.write(__import__('json').dumps(report))):
            response = self.client.get('/en/operations/readiness/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Technical checks passed')
        self.assertContains(response, 'Human review and acceptance still required')
        self.assertContains(response, 'Professional review of activity content and exact audio')
        self.assertContains(response, 'Reviewer identity, declared expertise and spoken-variety competence independently verified')
        self.assertContains(response, 'does not approve clinical content, legal compliance or commercial release')

    def test_invalid_configuration_has_a_safe_localized_html_state(self):
        self.client.force_login(self.operator)
        with patch('core.operations_views.call_command', side_effect=CommandError('private config detail')):
            response = self.client.get('/ar/operations/readiness/')
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, 'تقرير الجاهزية التقنية غير متاح', status_code=503)
        self.assertNotContains(response, 'private config detail', status_code=503)
        self.assertIn('no-store', response['Cache-Control'])

    def test_launch_readiness_dashboard_localizes_and_sets_arabic_direction(self):
        self.client.force_login(self.operator)
        report = {
            'technical_gates_passed': False, 'checks': {}, 'scope': 'Technical report only.',
            'manual_gates_required': ['reviewer_identity_and_variety_competence_independently_verified'],
            'offered_content_varieties': ['ar-dz-pilot'],
            'editorial_pipeline_by_variety': {'ar-dz-pilot': {'latest_versions': 1}},
        }
        with patch('core.operations_views.call_command', side_effect=lambda command, *, json, stdout: stdout.write(__import__('json').dumps(report))):
            french = self.client.get('/fr/operations/readiness/')
            english = self.client.get('/en/operations/readiness/')
            arabic = self.client.get('/ar/operations/readiness/')
        self.assertContains(french, 'Préparation au lancement')
        self.assertContains(english, 'Launch readiness')
        self.assertContains(english, 'Editorial queue by spoken variety')
        self.assertContains(arabic, 'الجاهزية للإطلاق')
        self.assertContains(arabic, 'قائمة التحرير حسب التنوع اللغوي المنطوق')
        self.assertContains(arabic, 'التحقق المستقل من هوية المراجعين وخبرتهم المعلنة وكفاءتهم في التنوع اللغوي المنطوق')
        self.assertIn('dir="rtl"', arabic.content.decode())
        self.assertIn('Observed at', english.content.decode())

    def test_launch_readiness_json_download_preserves_shared_report(self):
        self.client.force_login(self.operator)
        report = {'technical_gates_passed': False, 'checks': {}, 'scope': 'Technical report only.'}
        with patch('core.operations_views.call_command', side_effect=lambda command, *, json, stdout: stdout.write(__import__('json').dumps(report))):
            response = self.client.get('/en/operations/readiness/?format=json')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual({key: payload[key] for key in report}, report)
        self.assertTrue(payload['generated_at'])
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn('no-store', response['Cache-Control'])

    def test_launch_readiness_report_requires_platform_permission(self):
        for user in [self.ordinary, self.staff]:
            self.client.force_login(user)
            with patch('core.operations_views.call_command') as run:
                response = self.client.get('/en/operations/readiness/')
            self.assertEqual(response.status_code, 403)
            run.assert_not_called()

    def test_invalid_readiness_configuration_returns_a_noncommercial_blocker(self):
        self.client.force_login(self.operator)
        with patch('core.operations_views.call_command', side_effect=CommandError('private config detail')):
            response = self.client.get('/ar/operations/readiness/?format=json')
        self.assertEqual(response.status_code, 503)
        report = response.json()
        self.assertFalse(report['report_available'])
        self.assertFalse(report['technical_gates_passed'])
        self.assertNotIn('private config detail', response.content.decode())
        self.assertIn('no-store', response['Cache-Control'])

    def test_database_sample_is_explicit_post_and_does_not_accept_arbitrary_destinations(self):
        self.client.force_login(self.operator)
        with patch('core.ops_readiness.database_probe', return_value={'requested': True, 'ok': True, 'elapsed_ms': 2.5}) as probe, patch('core.ops_readiness.storage_probe') as storage, patch('smtplib.SMTP') as smtp:
            invalid = self.client.post('/en/operations/', {'action': 'storage', 'key': '../private-file'})
            self.assertEqual(invalid.status_code, 400)
            probe.assert_not_called()
            response = self.client.post('/en/operations/?format=json', {'action': 'database', 'url': 'https://untrusted.example', 'recipient': 'other@example.test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['database']['elapsed_ms'], 2.5)
        self.assertTrue(response.json()['database']['requested'])
        probe.assert_called_once_with(); storage.assert_not_called(); smtp.assert_not_called()
        self.assertEqual(self.client.put('/en/operations/').status_code, 405)

    def test_post_requires_csrf_and_existing_privileged_mfa(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.operator)
        with patch('core.operations_views.operations_report') as report:
            self.assertEqual(client.post('/fr/operations/', {'action': 'database'}).status_code, 403)
            report.assert_not_called()
        self.client.force_login(self.operator)
        with override_settings(MFA_REQUIRED=True), patch('core.operations_views.operations_report') as report:
            response = self.client.get('/fr/operations/')
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response['Location'], '/fr/security/setup/')
            report.assert_not_called()

    def test_actual_configuration_values_and_database_exception_never_exposed(self):
        self.client.force_login(self.operator)
        private = 'SECRET-MARKER-NOT-A-REAL-CREDENTIAL'
        def unavailable_probe():
            # Fail only the diagnostic query, after normal session/MFA middleware.
            with patch('core.ops_readiness.connection.cursor', side_effect=DatabaseError(private)):
                return database_probe()
        with override_settings(EMAIL_HOST=private, EMAIL_HOST_USER=private, EMAIL_HOST_PASSWORD=private, DEFAULT_FROM_EMAIL='private@actual-operator.tld'), patch('core.ops_readiness.database_probe', side_effect=unavailable_probe):
            response = self.client.post('/en/operations/?format=json', {'action': 'database'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['database']['ok'])
        for secret in [private, 'actual-operator.tld', 'private@']:
            self.assertNotIn(secret, response.content.decode())

    def test_view_renders_all_interface_languages_without_exposing_clinical_data(self):
        self.client.force_login(self.operator)
        for code in ['fr', 'en', 'ar']:
            response = self.client.get('/'+code+'/operations/')
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'name="action" value="database"')
            self.assertEqual(response.context['nav_section'], 'operations')
            self.assertContains(response, 'Designed by Benabdeloued Mohamed Alias Pitou')
            self.assertNotIn('children', response.context)

class RuntimeProvenanceTests(SimpleTestCase):
    def test_local_process_never_claims_a_render_commit_from_inherited_environment(self):
        with override_settings(IS_RENDER=False), patch.dict(os.environ, {'RENDER_GIT_COMMIT': 'a'*40}):
            report = execution_context()
        self.assertEqual(report['process'], 'operator_or_local_process')
        self.assertIsNone(report['build_commit'])
        self.assertIn('observed_at', report)

    def test_render_commit_is_strictly_validated_without_echoing_bad_values(self):
        with override_settings(IS_RENDER=True), patch.dict(os.environ, {'RENDER_GIT_COMMIT': 'A'*40}):
            self.assertEqual(execution_context()['build_commit'], 'a'*40)
        with override_settings(IS_RENDER=True), patch.dict(os.environ, {'RENDER_GIT_COMMIT': 'unexpected-secret-environment-value'}):
            report = execution_context()
        self.assertIsNone(report['build_commit'])
        self.assertNotIn('unexpected-secret', json.dumps(report))


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL transaction-local statement settings')
class DatabaseProbeTimeoutTests(TransactionTestCase):
    def test_probe_timeout_is_transaction_local_and_does_not_change_next_queries(self):
        from django.test.utils import CaptureQueriesContext
        with connection.cursor() as cursor:
            cursor.execute('SHOW statement_timeout')
            before = cursor.fetchone()[0]
        with CaptureQueriesContext(connection) as queries:
            result = database_probe()
        self.assertTrue(result['ok'])
        self.assertEqual(result['statement_timeout_ms'], 2000)
        self.assertTrue(any("SET LOCAL statement_timeout" in query['sql'] for query in queries))
        with connection.cursor() as cursor:
            cursor.execute('SHOW statement_timeout')
            after = cursor.fetchone()[0]
        self.assertEqual(after, before)

    def test_nested_probe_restores_the_callers_statement_timeout(self):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '6500ms'")
            self.assertTrue(database_probe()['ok'])
            cursor.execute('SHOW statement_timeout')
            self.assertEqual(cursor.fetchone()[0], '6500ms')
