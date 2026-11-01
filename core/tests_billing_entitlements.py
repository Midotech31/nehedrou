"""Fictional access rights and manual bookkeeping; no production billing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import threading
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone

from core.admin import EntitlementAdmin
from core.complete_views import billing
from core.models import AuditEvent, Entitlement, Invoice, Organization, User
from core.billing import transition_invoice


def entitlement_data(**overrides):
    data = {
        'plan': 'Fictional manual plan', 'status': 'active',
        'expires_at': (timezone.now() + timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S'),
        'child_quota': '15', 'practitioner_quota': '2', 'amount': '1250.00',
        'currency': 'DZD', 'billing_reference': 'fictional-external-reference',
    }
    data.update(overrides)
    return data


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ManualEntitlementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = User.objects.create_user(username='fictional-entitlement-operator', email='entitlement@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.other = User.objects.create_user(username='fictional-no-billing', email='no-billing@example.test')
        cls.organization = Organization.objects.create(name='Fictional access practice')

    def setUp(self):
        self.client.force_login(self.operator)
        self.url = reverse('billing_detail', args=[self.organization.pk])

    def test_get_displays_unsaved_defaults_and_never_creates_rights_or_events(self):
        for path in [reverse('billing_index'), self.url, self.url]:
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertFalse(Entitlement.objects.filter(organization=self.organization).exists())
        self.assertFalse(AuditEvent.objects.filter(organization=self.organization).exists())
        form = self.client.get(self.url).context['form']
        self.assertTrue(form.instance._state.adding)
        self.assertEqual(form.instance.currency, 'EUR')
        self.assertEqual(form.instance.amount, 0)
        self.assertFalse(form.is_bound)

    def test_post_creates_then_updates_one_record_and_audits_each_success(self):
        self.assertRedirects(self.client.post(self.url, entitlement_data()), self.url)
        entitlement = Entitlement.objects.get(organization=self.organization)
        initial_pk = entitlement.pk
        self.assertEqual((entitlement.amount, entitlement.currency), (Decimal('1250.00'), 'DZD'))
        self.assertRedirects(self.client.post(self.url, entitlement_data(amount='0.00', currency='EUR', status='cancelled')), self.url)
        entitlement.refresh_from_db()
        self.assertEqual((entitlement.pk, entitlement.amount, entitlement.currency, entitlement.status),
            (initial_pk, Decimal('0.00'), 'EUR', 'cancelled'))
        self.assertEqual(Entitlement.objects.filter(organization=self.organization).count(), 1)
        events = AuditEvent.objects.filter(organization=self.organization).order_by('created_at', 'pk')
        self.assertEqual(list(events.values_list('action', flat=True)), ['entitlement.created', 'entitlement.updated'])
        self.assertTrue(all(event.actor_id == self.operator.pk and event.object_id == str(initial_pk)
            and event.purpose_code == 'billing_admin' for event in events))
        snapshot = Entitlement.objects.values().get(pk=initial_pk)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(Entitlement.objects.values().get(pk=initial_pk), snapshot)
        self.assertEqual(events.count(), 2)

    def test_invalid_post_and_unsupported_methods_do_not_write(self):
        for values, field in [(entitlement_data(amount='-0.01'), 'amount'),
                (entitlement_data(currency='dzd'), 'currency'), (entitlement_data(currency='D1D'), 'currency')]:
            with self.subTest(field=field, value=values[field]):
                response = self.client.post(self.url, values)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
        self.assertEqual(self.client.put(self.url, entitlement_data()).status_code, 405)
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.assertFalse(Entitlement.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(organization=self.organization).exists())

    def test_permission_and_csrf_checks_prevent_creation(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, entitlement_data()).status_code, 403)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.operator)
        self.assertEqual(protected.post(self.url, entitlement_data()).status_code, 403)
        self.assertFalse(Entitlement.objects.exists())

    def test_failed_audit_rolls_back_creation_and_update(self):
        with patch('core.complete_views.audit', side_effect=RuntimeError('Fictional audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, entitlement_data())
        self.assertFalse(Entitlement.objects.exists())
        entitlement = Entitlement.objects.create(organization=self.organization, amount='50.00', currency='DZD')
        with patch('core.complete_views.audit', side_effect=RuntimeError('Fictional audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, entitlement_data(amount='75.00'))
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.amount, Decimal('50.00'))
        self.assertFalse(AuditEvent.objects.filter(organization=self.organization).exists())

    def test_models_reject_negative_amounts_and_invalid_currency_format(self):
        for amount in ['-0.01', '-100', 'invalid']:
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                Entitlement.objects.create(organization=self.organization, amount=amount)
        for currency in ['dzd', 'DZ', 'DZDZ', 'D1D', '€UR', 'دجج', 'DZD\n']:
            with self.subTest(currency=currency):
                with self.assertRaises(ValidationError):
                    Entitlement.objects.create(organization=self.organization, currency=currency)
                with self.assertRaises(ValidationError):
                    Invoice.objects.create(organization=self.organization, number='INVALID-CURRENCY', amount=0, currency=currency)
        entitlement = Entitlement.objects.create(organization=self.organization, amount=0, currency='ZZZ')
        # Format validation intentionally makes no ISO membership claim.
        self.assertEqual(entitlement.currency, 'ZZZ')
        entitlement.amount = Decimal('-1.00')
        with self.assertRaises(ValidationError):
            entitlement.save()
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.amount, Decimal('0.00'))
        invoice = Invoice.objects.create(organization=self.organization, number='FICTIONAL-LEGACY', amount=0)
        Invoice.objects.filter(pk=invoice.pk).update(currency='old')  # Simulate an existing legacy record.
        transition_invoice(self.operator, invoice.pk, 'paid')
        invoice.refresh_from_db()
        self.assertEqual((invoice.status, invoice.currency), ('paid', 'old'))

    def test_admin_save_is_atomic_with_its_billing_audit(self):
        request = RequestFactory().post('/admin/core/entitlement/add/')
        request.user = self.operator
        model_admin = EntitlementAdmin(Entitlement, admin.site)
        entitlement = Entitlement(organization=self.organization, amount='150.00', currency='DZD')
        with patch('core.services.audit', side_effect=RuntimeError('Fictional audit unavailable')):
            with self.assertRaises(RuntimeError):
                model_admin.save_model(request, entitlement, None, False)
        self.assertFalse(Entitlement.objects.exists())
        model_admin.save_model(request, entitlement, None, False)
        self.assertEqual(AuditEvent.objects.get().action, 'entitlement.created')
        entitlement.amount = Decimal('200.00')
        model_admin.save_model(request, entitlement, None, True)
        self.assertEqual(AuditEvent.objects.filter(action='entitlement.updated').count(), 1)


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ConcurrentEntitlementTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_initial_posts_create_one_record_and_two_audited_saves(self):
        operator = User.objects.create_user(username='fictional-concurrent-access', email='concurrent-access@example.test')
        operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        organization = Organization.objects.create(name='Fictional concurrent access practice')
        barrier = threading.Barrier(2)

        def attempt(amount):
            close_old_connections()
            try:
                request = RequestFactory().post('/', entitlement_data(amount=amount))
                request.user = User.objects.get(pk=operator.pk)
                barrier.wait(timeout=10)
                return billing(request, pk=organization.pk).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, ['100.00', '200.00']))
        self.assertEqual(results, [302, 302])
        entitlement = Entitlement.objects.get(organization=organization)
        self.assertIn(entitlement.amount, [Decimal('100.00'), Decimal('200.00')])
        events = AuditEvent.objects.filter(organization=organization, object_id=str(entitlement.pk))
        self.assertEqual(events.filter(action='entitlement.created').count(), 1)
        self.assertEqual(events.filter(action='entitlement.updated').count(), 1)
