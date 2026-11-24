"""Fictional manual invoice records; no payment provider or money movement."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import threading
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone, translation

from core.billing import transition_invoice
from core.complete_views import InvoiceForm
from core.models import AuditEvent, Entitlement, Invoice, Membership, Organization, User
from core.services import audit


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ManualInvoiceLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = User.objects.create_user(username='fictional-billing', email='billing@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.owner = User.objects.create_user(username='fictional-owner', email='owner@example.test')
        cls.organization = Organization.objects.create(name='Fictional billing practice')
        Membership.objects.create(user=cls.owner, organization=cls.organization, role='owner')
        cls.entitlement = Entitlement.objects.create(organization=cls.organization, amount=Decimal('100.00'),
            currency='DZD', status='active', expires_at=timezone.now()+timedelta(days=5))

    def invoice(self, **extra):
        values = dict(organization=self.organization, number='FICTIONAL-INV-1', amount=Decimal('1500.00'), currency='DZD')
        values.update(extra)
        return Invoice.objects.create(**values)

    def test_payment_is_recorded_once_without_changing_access_or_commercial_details(self):
        invoice = self.invoice(reference='initial-reference')
        entitlement_before = Entitlement.objects.values().get(pk=self.entitlement.pk)
        issued_at = invoice.issued_at
        result = transition_invoice(self.operator, invoice.pk, 'paid', ' receipt-fictional ')
        self.assertEqual(result.status, 'paid')
        self.assertIsNotNone(result.paid_at)
        self.assertLessEqual(result.paid_at, timezone.now())
        self.assertEqual((result.number,result.amount,result.currency,result.issued_at),
            ('FICTIONAL-INV-1',Decimal('1500.00'),'DZD',issued_at))
        self.assertEqual(result.reference, 'receipt-fictional')
        event = AuditEvent.objects.get(action='invoice.paid')
        self.assertEqual((event.actor_id,event.organization_id,event.object_id,event.purpose_code),
            (self.operator.pk,self.organization.pk,str(invoice.pk),'billing_admin'))
        for target in ('paid','cancelled'):
            with self.assertRaises(ValidationError):
                transition_invoice(self.operator, invoice.pk, target, 'second-reference')
        invoice.refresh_from_db()
        self.assertEqual(invoice.paid_at,result.paid_at)
        self.assertEqual(invoice.reference,'receipt-fictional')
        self.assertEqual(AuditEvent.objects.filter(object_id=str(invoice.pk)).count(),1)
        self.assertEqual(Entitlement.objects.values().get(pk=self.entitlement.pk),entitlement_before)

    def test_cancellation_is_final_and_does_not_create_a_payment_date(self):
        invoice = self.invoice(reference='existing-reference')
        result = transition_invoice(self.operator, invoice.pk, 'cancelled', '')
        self.assertEqual(result.status,'cancelled')
        self.assertIsNone(result.paid_at)
        self.assertEqual(result.reference,'existing-reference')
        for target in ('cancelled','paid'):
            with self.assertRaises(ValidationError):
                transition_invoice(self.operator, invoice.pk, target)
        self.assertEqual(AuditEvent.objects.filter(action='invoice.cancelled',object_id=str(invoice.pk)).count(),1)

    def test_service_rejects_permission_missing_inactive_and_invalid_target(self):
        invoice = self.invoice()
        with self.assertRaises(PermissionDenied):
            transition_invoice(self.owner,invoice.pk,'paid')
        self.operator.is_active=False
        with self.assertRaises(PermissionDenied):
            transition_invoice(self.operator,invoice.pk,'paid')
        self.operator.is_active=True
        with self.assertRaises(ValidationError):
            transition_invoice(self.operator,invoice.pk,'issued')
        invoice.refresh_from_db()
        self.assertEqual(invoice.status,'issued')
        self.assertFalse(AuditEvent.objects.filter(object_id=str(invoice.pk)).exists())

    def test_status_and_audit_are_rolled_back_together(self):
        invoice = self.invoice()
        with patch('core.billing.audit',side_effect=RuntimeError('Fictional audit failure')):
            with self.assertRaises(RuntimeError):
                transition_invoice(self.operator,invoice.pk,'paid')
        invoice.refresh_from_db()
        self.assertEqual(invoice.status,'issued')
        self.assertIsNone(invoice.paid_at)
        self.assertFalse(AuditEvent.objects.filter(object_id=str(invoice.pk)).exists())

    def test_recorded_invoice_identity_and_terminal_details_are_immutable(self):
        invoice = self.invoice()
        other = Organization.objects.create(name='Fictional other practice')
        for field,value in [('number','REPLACED'),('amount',Decimal('1.00')),('currency','EUR'),
                ('organization',other),('issued_at',invoice.issued_at-timedelta(days=1))]:
            with self.subTest(field=field):
                setattr(invoice,field,value)
                with self.assertRaises(ValidationError): invoice.save()
                invoice.refresh_from_db()
        transition_invoice(self.operator,invoice.pk,'paid','fixed-reference')
        for field,value in [('status','issued'),('paid_at',None),('reference','changed-reference')]:
            with self.subTest(field=field):
                invoice.refresh_from_db()
                setattr(invoice,field,value)
                with self.assertRaises(ValidationError): invoice.save()

    def test_payment_date_must_agree_with_status_and_existing_paid_creation_still_works(self):
        with self.assertRaises(ValidationError): self.invoice(status='paid')
        with self.assertRaises(ValidationError): self.invoice(status='issued',paid_at=timezone.now())
        self.client.force_login(self.operator)
        response = self.client.post(reverse('invoice_create',args=[self.organization.pk]),
            {'number':'FICTIONAL-PAID-AT-CREATION','amount':'2300.00','currency':'DZD','status':'paid','reference':'external-receipt'})
        self.assertEqual(response.status_code,302)
        created=Invoice.objects.get(number='FICTIONAL-PAID-AT-CREATION')
        self.assertEqual(created.status,'paid')
        self.assertIsNotNone(created.paid_at)
        self.assertTrue(AuditEvent.objects.filter(action='invoice.recorded',object_id=str(created.pk)).exists())

    def test_creation_rolls_back_invoice_and_partial_audit_then_allows_retry(self):
        self.client.force_login(self.operator)
        url = reverse('invoice_create', args=[self.organization.pk])
        entitlement_before = Entitlement.objects.values().get(pk=self.entitlement.pk)

        def failing_audit(*args, **kwargs):
            audit(*args, **kwargs)
            raise RuntimeError('Fictional invoice audit failure')

        for status in ('issued', 'paid'):
            with self.subTest(status=status):
                number = f'FICTIONAL-AUDIT-{status}'
                data = {
                    'number': number, 'amount': '2300.00', 'currency': 'DZD',
                    'status': status, 'reference': 'fictional-external-receipt',
                }
                events_before = AuditEvent.objects.count()
                with patch('core.complete_views.audit', side_effect=failing_audit):
                    with self.assertRaisesMessage(RuntimeError, 'Fictional invoice audit failure'):
                        self.client.post(url, data)
                self.assertFalse(Invoice.objects.filter(number=number).exists())
                self.assertEqual(AuditEvent.objects.count(), events_before)

                self.assertRedirects(
                    self.client.post(url, data),
                    reverse('billing_detail', args=[self.organization.pk]),
                    fetch_redirect_response=False,
                )
                invoice = Invoice.objects.get(number=number)
                self.assertEqual(invoice.status, status)
                self.assertEqual(invoice.paid_at is not None, status == 'paid')
                event = AuditEvent.objects.get(action='invoice.recorded', object_id=str(invoice.pk))
                self.assertEqual(
                    (event.actor_id, event.organization_id, event.purpose_code),
                    (self.operator.pk, self.organization.pk, 'billing_admin'),
                )
                self.assertEqual(AuditEvent.objects.count(), events_before + 1)
                self.assertEqual(Entitlement.objects.values().get(pk=self.entitlement.pk), entitlement_before)

    def test_number_recorded_between_form_and_model_validation_is_a_field_error(self):
        self.client.force_login(self.operator)
        number = 'FICTIONAL-POST-FORM-COLLISION'
        other = Organization.objects.create(name='Fictional competing practice')
        real_is_valid = InvoiceForm.is_valid

        def validate_then_simulate_other_request(form):
            valid = real_is_valid(form)
            if valid and not Invoice.objects.filter(number=number).exists():
                self.invoice(number=number, organization=other)
            return valid

        data = {'number': number, 'amount': '2300.00', 'currency': 'DZD', 'status': 'paid'}
        with patch.object(InvoiceForm, 'is_valid', validate_then_simulate_other_request):
            response = self.client.post(reverse('invoice_create', args=[self.organization.pk]), data)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].has_error('number', 'unique'))
        invoice = Invoice.objects.get(number=number)
        self.assertEqual((invoice.organization_id, invoice.amount, invoice.status), (other.pk, Decimal('1500.00'), 'issued'))
        self.assertFalse(AuditEvent.objects.filter(action='invoice.recorded').exists())

    def test_http_permissions_methods_replay_and_uneditable_amounts(self):
        invoice=self.invoice()
        detail=reverse('invoice_detail',args=[invoice.pk])
        status=reverse('invoice_status',args=[invoice.pk])
        self.assertEqual(self.client.get(detail).status_code,302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(detail).status_code,403)
        self.assertEqual(self.client.post(status,{'status':'paid'}).status_code,403)
        self.client.force_login(self.operator)
        response=self.client.get(detail)
        self.assertEqual(response['Cache-Control'],'private, no-store')
        self.assertNotContains(response,'name="amount"')
        self.assertNotContains(response,'name="currency"')
        self.assertNotContains(response,'name="number"')
        self.assertEqual(self.client.get(status).status_code,405)
        self.assertEqual(self.client.post(detail).status_code,405)
        data={'status':'paid','reference':'external-receipt','amount':'0','number':'FORGED','currency':'EUR'}
        self.assertRedirects(self.client.post(status,data),detail)
        self.assertRedirects(self.client.post(status,data),detail)
        invoice.refresh_from_db()
        self.assertEqual((invoice.number,invoice.amount,invoice.currency),('FICTIONAL-INV-1',Decimal('1500.00'),'DZD'))
        self.assertEqual(AuditEvent.objects.filter(action='invoice.paid',object_id=str(invoice.pk)).count(),1)
        self.assertNotContains(self.client.get(detail),'name="status"')

    def test_csrf_and_three_language_detail_links(self):
        invoice=self.invoice()
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.operator)
        self.assertEqual(client.post(reverse('invoice_status',args=[invoice.pk]),{'status':'paid'}).status_code,403)
        self.client.force_login(self.operator)
        for language in ('fr','en','ar'):
            with self.subTest(language=language),translation.override(language):
                response=self.client.get(reverse('invoice_detail',args=[invoice.pk]))
                self.assertEqual(response.status_code,200)
                self.assertContains(response,translation.gettext('Record invoice status'))
                self.assertContains(response,'lang="'+language+'"')
                self.assertContains(response,'dir="rtl"' if language=='ar' else 'dir="ltr"')
                billing=self.client.get(reverse('billing_detail',args=[self.organization.pk]))
                self.assertContains(billing,reverse('invoice_detail',args=[invoice.pk]))


@override_settings(DEMO_MODE=True,MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ConcurrentManualInvoiceTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_two_finalisations_produce_one_final_status_and_one_event(self):
        operator=User.objects.create_user(username='fictional-concurrent-billing',email='concurrent@example.test')
        operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        organization=Organization.objects.create(name='Fictional concurrent practice')
        invoice=Invoice.objects.create(organization=organization,number='FICTIONAL-CONCURRENT',amount='1500.00',currency='DZD')
        barrier=threading.Barrier(2)
        def attempt(status):
            close_old_connections()
            try:
                actor=User.objects.get(pk=operator.pk)
                barrier.wait(timeout=10)
                try:
                    transition_invoice(actor,invoice.pk,status)
                    return True
                except ValidationError:
                    return False
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes=list(executor.map(attempt,['paid','cancelled']))
        self.assertEqual(outcomes.count(True),1)
        invoice.refresh_from_db()
        self.assertIn(invoice.status,('paid','cancelled'))
        self.assertEqual(AuditEvent.objects.filter(object_id=str(invoice.pk)).count(),1)

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_creation_returns_one_success_and_one_field_error(self):
        operator = User.objects.create_user(username='fictional-concurrent-invoice', email='invoices@example.test')
        operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        practices = [Organization.objects.create(name=f'Fictional practice {i}') for i in (1, 2)]
        number = 'FICTIONAL-CONCURRENT-CREATE'
        barrier = threading.Barrier(2)
        validate_unique = Invoice.validate_unique

        def validate_before_insert(invoice, exclude=None):
            validate_unique(invoice, exclude=exclude)
            # The form excludes organization. Wait only after model validation
            # so both threads reach the real PostgreSQL uniqueness constraint.
            if 'organization' not in (exclude or ()):
                barrier.wait(timeout=10)

        def attempt(practice):
            close_old_connections()
            try:
                client = Client()
                client.force_login(User.objects.get(pk=operator.pk))
                response = client.post(reverse('invoice_create', args=[practice.pk]), {
                    'number': number, 'amount': '1500.00', 'currency': 'DZD', 'status': 'issued',
                })
                if response.status_code == 200:
                    return response.status_code, response.context['form'].has_error('number', 'unique')
                return response.status_code, None
            finally:
                connections.close_all()

        with patch.object(Invoice, 'validate_unique', validate_before_insert):
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(attempt, practices))

        self.assertCountEqual(outcomes, [(302, None), (200, True)])
        invoice = Invoice.objects.get(number=number)
        event = AuditEvent.objects.get(action='invoice.recorded')
        self.assertEqual(
            (event.actor_id, event.organization_id, event.object_id),
            (operator.pk, invoice.organization_id, str(invoice.pk)),
        )
