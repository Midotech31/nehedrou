"""Explicit, reversible disclosure of safe fictional billing summary fields."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import AuditEvent, Entitlement, Invoice, Membership, Organization, User


PLAN = '/en/subscription/'
SUMMARY = PLAN + 'billing/'
SETTINGS = {
    'DEMO_MODE': False, 'MFA_REQUIRED': False, 'SECURE_SSL_REDIRECT': False,
    'EMAIL_BACKEND': 'core.email_backends.DisabledEmailBackend',
}


def select(client, organization):
    session = client.session
    session['workspace'] = 'professional'
    session['organization'] = str(organization.pk)
    session.save()


def detail(invoice, language='en'):
    return f'/{language}/billing/invoices/{invoice.pk}/'


def sharing_data(client, invoice, action='share', language='en'):
    response = client.get(detail(invoice, language))
    if response.status_code != 200:
        raise AssertionError('Platform billing detail must be available.')
    return {'visibility': action, 'invoice_sharing_snapshot': response.context['invoice_sharing_snapshot']}


@override_settings(**SETTINGS)
class PracticeBillingSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alpha = Organization.objects.create(name='Fictional billing summary alpha')
        cls.beta = Organization.objects.create(name='Fictional billing summary beta')
        cls.owner = User.objects.create_user('summary-owner', 'summary-owner@example.test')
        cls.other_owner = User.objects.create_user('summary-other-owner', 'summary-other-owner@example.test')
        cls.operator = User.objects.create_user('summary-billing-operator', 'summary-operator@example.test')
        cls.clinician = User.objects.create_user('summary-clinician', 'summary-clinician@example.test')
        cls.family = User.objects.create_user('summary-caregiver', 'summary-caregiver@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        Membership.objects.create(organization=cls.alpha, user=cls.owner, role='owner')
        Membership.objects.create(organization=cls.beta, user=cls.owner, role='owner')
        Membership.objects.create(organization=cls.beta, user=cls.other_owner, role='owner')
        Membership.objects.create(organization=cls.alpha, user=cls.clinician, role='clinician')
        cls.entitlement = Entitlement.objects.create(organization=cls.alpha, status='expired',
            expires_at=timezone.now() - timedelta(days=1), amount=Decimal('2450.00'), currency='DZD')
        cls.invoice = Invoice.objects.create(organization=cls.alpha, number='FICTIONAL-ALPHA-BILL',
            amount=Decimal('2450.00'), currency='DZD', reference='private issue reference')
        cls.foreign = Invoice.objects.create(organization=cls.beta, number='FICTIONAL-BETA-BILL',
            amount=Decimal('760.00'), currency='DZD', reference='private foreign reference')

    def account(self, user, organization=None, **options):
        client = Client(**options)
        client.force_login(user)
        if organization is not None:
            select(client, organization)
        return client

    def test_opt_in_paid_read_only_summary_then_withdrawal_and_old_replay_refusal(self):
        operator = self.account(self.operator)
        owner = self.account(self.owner, self.alpha)
        other = self.account(self.other_owner, self.beta)
        baseline = Entitlement.objects.values().get(pk=self.entitlement.pk)
        self.assertContains(owner.get(PLAN), 'id="practice-billing-summary-link"')
        hidden = owner.get(SUMMARY)
        self.assertContains(hidden, 'No billing summaries have been shared')
        self.assertNotContains(hidden, self.invoice.number)
        self.assertEqual(owner.get(detail(self.invoice)).status_code, 403)
        self.assertIsNone(Invoice.objects.get(pk=self.invoice.pk).shared_with_practice_at)

        endpoint = detail(self.invoice) + 'sharing/'
        original = sharing_data(operator, self.invoice)
        self.assertRedirects(operator.post(endpoint, original), detail(self.invoice))
        self.assertContains(operator.get(detail(self.invoice)), 'data-sharing-state="shared"')
        self.assertContains(owner.get(SUMMARY), self.invoice.number)
        self.assertNotContains(other.get(SUMMARY), self.invoice.number)
        self.assertRedirects(operator.post(detail(self.invoice) + 'status/', {
            'status': 'paid', 'reference': 'private bank reconciliation',
        }), detail(self.invoice))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')
        for language, direction, paid, title in (
            ('fr', 'ltr', 'Payée', 'Récapitulatif de facturation du cabinet'),
            ('en', 'ltr', 'Paid', 'Practice billing summary'),
            ('ar', 'rtl', 'مدفوعة', 'ملخّص فواتير العيادة'),
        ):
            with self.subTest(language=language):
                receipt = owner.get(f'/{language}/subscription/billing/')
                self.assertContains(receipt, f'<html lang="{language}" dir="{direction}">')
                self.assertContains(receipt, title)
                self.assertContains(receipt, paid)
                self.assertContains(receipt, self.invoice.number)
                self.assertContains(receipt, 'DZD')
                self.assertIn('private', receipt['Cache-Control'])
                self.assertIn('no-store', receipt['Cache-Control'])
                for protected in ('private bank reconciliation', 'private issue reference', self.operator.username,
                                  str(self.invoice.pk), 'record invoice status', self.foreign.number):
                    self.assertNotContains(receipt, protected)
                self.assertEqual(set(receipt.context['invoices'][0]),
                                 {'number', 'amount', 'currency', 'status', 'issued_at', 'paid_at', 'status_label'})

        self.assertRedirects(operator.post(endpoint, sharing_data(operator, self.invoice, 'unshare')),
                             detail(self.invoice))
        self.assertContains(operator.get(detail(self.invoice)), 'data-sharing-state="private"')
        self.assertEqual(operator.post(endpoint, original).status_code, 409)
        self.assertNotContains(owner.get(SUMMARY), self.invoice.number)
        self.assertEqual(Entitlement.objects.values().get(pk=self.entitlement.pk), baseline)
        self.assertEqual(list(AuditEvent.objects.filter(organization=self.alpha, object_id=self.invoice.pk)
                              .order_by('pk').values_list('action', 'purpose_code')), [
            ('invoice.summary_shared', 'billing_admin'), ('invoice.paid', 'billing_admin'),
            ('invoice.summary_unshared', 'billing_admin'),
        ])

    def test_scope_is_selected_active_owner_and_platform_control_is_post_with_csrf(self):
        owner = self.account(self.owner, self.alpha)
        other = self.account(self.other_owner, self.beta)
        operator = self.account(self.operator)
        for invoice in (self.invoice, self.foreign):
            self.assertRedirects(operator.post(detail(invoice) + 'sharing/', sharing_data(operator, invoice)),
                                 detail(invoice))
        self.assertNotContains(owner.get(SUMMARY + '?organization=' + str(self.beta.pk)), self.foreign.number)
        self.assertNotContains(other.get(SUMMARY), self.invoice.number)
        select(owner, self.beta)
        self.assertContains(owner.get(SUMMARY), self.foreign.number)
        self.assertNotContains(owner.get(SUMMARY), self.invoice.number)
        Membership.objects.filter(organization=self.beta, user=self.owner).update(active=False)
        self.assertEqual(owner.get(SUMMARY).status_code, 404)
        for actor in (self.clinician, self.family, self.operator):
            with self.subTest(actor=actor.username):
                self.assertEqual(self.account(actor).get(SUMMARY).status_code, 404)
        self.assertEqual(other.post(SUMMARY).status_code, 405)
        endpoint = detail(self.foreign) + 'sharing/'
        self.assertEqual(other.post(endpoint).status_code, 403)
        self.assertEqual(operator.get(endpoint).status_code, 405)
        strict = self.account(self.operator, enforce_csrf_checks=True)
        self.assertEqual(strict.post(endpoint, sharing_data(strict, self.foreign, 'unshare')).status_code, 403)

    def test_pending_draft_or_unknown_legacy_state_cannot_be_disclosed(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(status='draft')
        operator = self.account(self.operator)
        owner = self.account(self.owner, self.alpha)
        self.assertNotContains(operator.get(detail(self.invoice)), 'id="invoice-summary-sharing-form"')
        self.assertEqual(operator.post(detail(self.invoice) + 'sharing/',
                                       sharing_data(operator, self.invoice)).status_code, 400)
        self.assertFalse(AuditEvent.objects.filter(action='invoice.summary_shared').exists())
        self.assertNotContains(owner.get(SUMMARY), self.invoice.number)

    def test_sharing_is_bound_to_invoice_and_current_operator_and_atomic_with_audit(self):
        operator = self.account(self.operator)
        another = User.objects.create_user('summary-second-billing', 'summary-second@example.test')
        another.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        second = self.account(another)
        payload = sharing_data(operator, self.invoice)
        self.assertEqual(second.post(detail(self.invoice) + 'sharing/', payload).status_code, 409)
        self.assertEqual(operator.post(detail(self.foreign) + 'sharing/', payload).status_code, 409)
        with patch('core.billing_views.audit', side_effect=RuntimeError('fictional audit failure')):
            with self.assertRaisesMessage(RuntimeError, 'fictional audit failure'):
                operator.post(detail(self.invoice) + 'sharing/', payload)
        self.assertIsNone(Invoice.objects.get(pk=self.invoice.pk).shared_with_practice_at)
        self.assertFalse(AuditEvent.objects.exists())

    @override_settings(MFA_REQUIRED=True)
    def test_owner_and_operator_routes_reuse_mfa(self):
        owner = self.account(self.owner, self.alpha)
        operator = self.account(self.operator)
        self.assertRedirects(owner.get(SUMMARY), '/en/security/setup/', fetch_redirect_response=False)
        self.assertRedirects(operator.post(detail(self.invoice) + 'sharing/', {'visibility': 'share'}),
                             '/en/security/setup/', fetch_redirect_response=False)

    def test_cabinet_summary_uses_bounded_pages(self):
        Invoice.objects.bulk_create([
            Invoice(organization=self.alpha, number=f'FICTIONAL-PAGED-{i:02}', amount=Decimal('1.00'),
                    currency='DZD', shared_with_practice_at=timezone.now()) for i in range(26)
        ])
        owner = self.account(self.owner, self.alpha)
        first = owner.get(SUMMARY)
        second = owner.get(SUMMARY + '?page=2')
        self.assertEqual(len(first.context['invoices']), 25)
        self.assertEqual(len(second.context['invoices']), 1)
        self.assertEqual(first.context['page'].paginator.count, 26)


@override_settings(**SETTINGS)
@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks.')
class PracticeBillingSharingConcurrencyTests(TransactionTestCase):
    def test_simultaneous_share_forms_commit_one_visibility_event(self):
        organization = Organization.objects.create(name='Fictional parallel sharing')
        invoice = Invoice.objects.create(organization=organization, number='FICTIONAL-PARALLEL',
                                         amount=Decimal('200.00'), currency='DZD')
        permission = Permission.objects.get(codename='manage_entitlements')
        submissions = []
        for i in range(2):
            operator = User.objects.create_user(f'summary-parallel-operator-{i}', f'operator-{i}@example.test')
            operator.user_permissions.add(permission)
            client = Client()
            client.force_login(operator)
            submissions.append((client, sharing_data(client, invoice)))
        barrier = Barrier(2)

        def attempt(submission):
            client, payload = submission
            try:
                barrier.wait(timeout=15)
                return client.post(detail(invoice) + 'sharing/', payload).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(list(executor.map(attempt, submissions)), [302, 409])
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.shared_with_practice_at)
        self.assertEqual(AuditEvent.objects.filter(object_id=invoice.pk, action='invoice.summary_shared').count(), 1)
