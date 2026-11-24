from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth.models import Permission
from django.core import signing
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.form_scope import SALT as PRACTICE_SCOPE_SALT
from core.models import AuditEvent, Entitlement, Invoice, Membership, Organization, PracticeAccessRequest, User


SETTINGS = {
    'DEMO_MODE': False,
    'MFA_REQUIRED': False,
    'SECURE_SSL_REDIRECT': False,
    'EMAIL_BACKEND': 'core.email_backends.DisabledEmailBackend',
    'PASSWORD_HASHERS': ['django.contrib.auth.hashers.MD5PasswordHasher'],
}
PLAN = '/en/subscription/'
REQUEST = '/en/subscription/request-access/'
BILLING = '/en/billing/'


def acknowledge(pk):
    return f'/en/billing/access-requests/{pk}/acknowledge/'


def select(client, organization):
    session = client.session
    session['workspace'] = 'professional'
    session['organization'] = str(organization.pk)
    session.save()


def request_form(client, plan=PLAN):
    response = client.get(plan)
    if response.status_code != 200 or not response.context.get('access_request_scope'):
        raise AssertionError('A valid selected-practice request form is required.')
    return {'practice_scope': response.context['access_request_scope']}


@override_settings(**SETTINGS)
class PracticeAccessRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alpha = Organization.objects.create(name='Fictional request alpha')
        cls.beta = Organization.objects.create(name='Fictional request beta')
        cls.alpha_owner = User.objects.create_user('request-alpha-owner', 'alpha-owner@example.test')
        cls.beta_owner = User.objects.create_user('request-beta-owner', 'beta-owner@example.test')
        cls.clinician = User.objects.create_user('request-clinician', 'clinician@example.test')
        cls.operator = User.objects.create_user('request-operator', 'operator@example.test')
        cls.register_operator = User.objects.create_user('request-register', 'register@example.test')
        cls.operator.user_permissions.add(Permission.objects.get(codename='manage_entitlements'))
        cls.register_operator.user_permissions.add(Permission.objects.get(codename='manage_processing_register'))
        Membership.objects.create(user=cls.alpha_owner, organization=cls.alpha, role='owner')
        Membership.objects.create(user=cls.alpha_owner, organization=cls.beta, role='owner')
        Membership.objects.create(user=cls.beta_owner, organization=cls.beta, role='owner')
        Membership.objects.create(user=cls.clinician, organization=cls.alpha, role='clinician')
        Entitlement.objects.create(organization=cls.alpha, status='expired', expires_at=timezone.now())
        Entitlement.objects.create(organization=cls.beta, status='cancelled', expires_at=timezone.now())

    def account(self, user, organization=None, **options):
        client = Client(**options)
        client.force_login(user)
        if organization is not None:
            select(client, organization)
        return client

    def submit(self, client):
        self.assertRedirects(client.post(REQUEST, request_form(client)), PLAN, fetch_redirect_response=False)

    def test_round_trip_two_cabinets_acknowledgement_and_fresh_request(self):
        owner = self.account(self.alpha_owner, self.alpha)
        other = self.account(self.beta_owner, self.beta)
        operator = self.account(self.operator)
        before = list(Entitlement.objects.order_by('pk').values())

        initial = request_form(owner)
        self.assertRedirects(owner.post(REQUEST, {**initial, 'reason': 'ignored browser value'}), PLAN)
        first = PracticeAccessRequest.objects.get(organization=self.alpha)
        self.assertEqual(first.requested_by, self.alpha_owner)
        self.assertContains(owner.get(PLAN), 'data-request-state="pending"')
        self.assertNotContains(other.get(PLAN), 'data-request-state="pending"')
        self.assertRedirects(owner.post(REQUEST, initial), PLAN)
        self.assertEqual(PracticeAccessRequest.objects.filter(organization=self.alpha).count(), 1)

        self.submit(other)
        foreign = PracticeAccessRequest.objects.get(organization=self.beta)
        select(owner, self.beta)
        self.assertContains(owner.get(PLAN), 'data-request-state="pending"')
        select(owner, self.alpha)
        inbox = operator.get(BILLING)
        self.assertContains(inbox, 'data-request-state="pending"', count=2)
        self.assertContains(inbox, acknowledge(first.pk))
        self.assertContains(inbox, acknowledge(foreign.pk))
        self.assertNotContains(inbox, self.alpha_owner.email)
        self.assertIn('no-store', inbox['Cache-Control'])

        self.assertRedirects(operator.post(acknowledge(first.pk)), BILLING)
        self.assertRedirects(operator.post(acknowledge(first.pk)), BILLING)
        first.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(first.acknowledged_by, self.operator)
        self.assertIsNotNone(first.acknowledged_at)
        self.assertIsNone(foreign.acknowledged_at)
        self.assertNotContains(operator.get(BILLING), acknowledge(first.pk))
        self.assertContains(owner.get(PLAN), 'data-request-state="acknowledged"')
        self.assertContains(other.get(PLAN), 'data-request-state="pending"')

        self.assertEqual(owner.post(REQUEST, initial).status_code, 409)
        self.assertEqual(PracticeAccessRequest.objects.filter(organization=self.alpha).count(), 1)
        self.submit(owner)
        self.assertEqual(PracticeAccessRequest.objects.filter(organization=self.alpha).count(), 2)
        self.assertEqual(PracticeAccessRequest.objects.filter(organization=self.alpha, acknowledged_at__isnull=True).count(), 1)
        self.assertEqual(list(Entitlement.objects.order_by('pk').values()), before)
        self.assertFalse(Invoice.objects.exists())

        actions = list(AuditEvent.objects.filter(organization=self.alpha).order_by('pk')
                       .values_list('action', 'purpose_code'))
        self.assertEqual(actions.count(('entitlement.review_requested', 'billing_admin')), 2)
        self.assertEqual(actions.count(('entitlement.review_acknowledged', 'billing_admin')), 1)

    def test_selected_scope_and_actor_are_checked_before_writing(self):
        owner = self.account(self.alpha_owner, self.alpha)
        other = self.account(self.beta_owner, self.beta)
        alpha_form = request_form(owner)
        select(owner, self.beta)
        self.assertEqual(owner.post(REQUEST, alpha_form).status_code, 409)
        beta_form = request_form(owner)
        self.assertEqual(other.post(REQUEST, beta_form).status_code, 409)
        self.assertEqual(owner.post(REQUEST).status_code, 409)
        self.assertFalse(PracticeAccessRequest.objects.exists())

        session = owner.session
        session['organization'] = 'previous-selection'
        session.save()
        self.assertNotContains(owner.get(PLAN), 'id="practice-access-request"')
        self.assertEqual(owner.post(REQUEST, beta_form).status_code, 404)
        self.assertEqual(self.account(self.clinician, self.alpha).post(REQUEST, alpha_form).status_code, 404)
        self.assertFalse(PracticeAccessRequest.objects.exists())

    def test_confirmation_is_operator_only_and_requires_post_and_csrf(self):
        strict_owner = self.account(self.alpha_owner, self.alpha, enforce_csrf_checks=True)
        form = request_form(strict_owner)
        self.assertEqual(strict_owner.get(REQUEST).status_code, 405)
        self.assertEqual(strict_owner.post(REQUEST, form).status_code, 403)
        self.assertFalse(PracticeAccessRequest.objects.exists())

        owner = self.account(self.alpha_owner, self.alpha)
        self.submit(owner)
        review = PracticeAccessRequest.objects.get(organization=self.alpha)
        endpoint = acknowledge(review.pk)
        for user in (self.alpha_owner, self.register_operator, self.clinician):
            with self.subTest(user=user.username):
                non_operator = self.account(user)
                self.assertEqual(non_operator.get(BILLING).status_code, 403)
                self.assertEqual(non_operator.post(endpoint).status_code, 403)
        operator = self.account(self.operator, enforce_csrf_checks=True)
        self.assertEqual(operator.get(endpoint).status_code, 405)
        self.assertEqual(operator.post(endpoint).status_code, 403)
        review.refresh_from_db()
        self.assertIsNone(review.acknowledged_at)

    @override_settings(MFA_REQUIRED=True)
    def test_mfa_gate_covers_owner_and_operator_routes(self):
        owner = self.account(self.alpha_owner, self.alpha)
        operator = self.account(self.operator)
        self.assertRedirects(owner.get(PLAN), '/en/security/setup/', fetch_redirect_response=False)
        self.assertRedirects(operator.get(BILLING), '/en/security/setup/', fetch_redirect_response=False)

    def test_activation_after_opening_form_and_demonstration_mode_prevent_new_requests(self):
        owner = self.account(self.alpha_owner, self.alpha)
        payload = request_form(owner)
        Entitlement.objects.filter(organization=self.alpha).update(
            status='active', expires_at=timezone.now() + timedelta(days=2),
        )
        self.assertRedirects(owner.post(REQUEST, payload), PLAN)
        self.assertNotContains(owner.get(PLAN), 'id="practice-access-request"')
        with override_settings(DEMO_MODE=True):
            demo = self.account(self.beta_owner, self.beta)
            operator = self.account(self.operator)
            self.assertNotContains(demo.get(PLAN), 'id="practice-access-request"')
            self.assertEqual(demo.post(REQUEST, payload).status_code, 404)
            self.assertNotContains(operator.get(BILLING), 'id="practice-access-requests"')
        self.assertFalse(PracticeAccessRequest.objects.exists())

    def test_new_practice_signup_can_request_access_and_receipt_remains_localized(self):
        response = self.client.post('/fr/signup/', {
            'username': 'fictional-first-owner', 'email': 'fictional-first@example.test',
            'password1': 'Fresh-Garage-42-water!', 'password2': 'Fresh-Garage-42-water!',
            'practice_name': 'Fictional first request', 'instruction_language': 'fr',
        })
        if response.status_code != 302:
            self.fail(response.context['form'].errors.as_text())
        self.assertRedirects(response, '/fr/app/')
        clinic = Organization.objects.get(name='Fictional first request')
        self.assertEqual(Entitlement.objects.get(organization=clinic).status, 'expired')
        for language, request_label in (
            ('fr', 'Demander un examen de l’accès'),
            ('en', 'Request an access review'),
            ('ar', 'طلب مراجعة الوصول'),
        ):
            with self.subTest(language=language):
                plan = f'/{language}/subscription/'
                self.assertContains(self.client.get(plan), request_label)
        self.assertRedirects(self.client.post(REQUEST, request_form(self.client)), PLAN)
        for language, direction, pending_label in (
            ('fr', 'ltr', 'Votre demande est en attente d’examen'),
            ('en', 'ltr', 'Your request is awaiting review'),
            ('ar', 'rtl', 'طلبكم في انتظار مراجعة'),
        ):
            with self.subTest(language=language):
                receipt = self.client.get(f'/{language}/subscription/')
                self.assertContains(receipt, f'<html lang="{language}" dir="{direction}">')
                self.assertContains(receipt, pending_label)
                self.assertContains(receipt, 'data-request-state="pending"')


@override_settings(**SETTINGS)
@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL practice row locks.')
class PracticeAccessRequestPostgreSQLTests(TransactionTestCase):
    def test_parallel_owners_and_parallel_acknowledgements_are_each_idempotent(self):
        clinic = Organization.objects.create(name='Fictional parallel request')
        owners = [User.objects.create_user(f'parallel-owner-{i}', f'owner-{i}@example.test') for i in range(2)]
        operators = [User.objects.create_user(f'parallel-operator-{i}', f'operator-{i}@example.test') for i in range(2)]
        for owner in owners:
            Membership.objects.create(user=owner, organization=clinic, role='owner')
        permission = Permission.objects.get(codename='manage_entitlements')
        for operator in operators:
            operator.user_permissions.add(permission)

        def parallel_post(accounts, path, owner_submission=False):
            # Django's test client captures template contexts through a process-wide signal.
            # Render each actor's form first, then run only the mutations concurrently.
            submissions = []
            for user in accounts:
                client = Client()
                client.force_login(user)
                data = {}
                if owner_submission:
                    select(client, clinic)
                    data = request_form(client)
                    scope = signing.loads(data['practice_scope'], salt=PRACTICE_SCOPE_SALT)
                    self.assertEqual(scope['actor'], str(user.pk))
                    self.assertEqual(scope['organization'], str(clinic.pk))
                submissions.append((client, data))
            barrier = Barrier(len(submissions))

            def attempt(submission):
                client, data = submission
                try:
                    barrier.wait(timeout=15)
                    return client.post(path, data).status_code
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=len(submissions)) as executor:
                return list(executor.map(attempt, submissions))

        self.assertEqual(parallel_post(owners, REQUEST, owner_submission=True), [302, 302])
        request = PracticeAccessRequest.objects.get(organization=clinic)
        self.assertEqual(parallel_post(operators, acknowledge(request.pk)), [302, 302])
        request.refresh_from_db()
        self.assertIsNotNone(request.acknowledged_at)
        self.assertIn(request.requested_by, owners)
        self.assertIn(request.acknowledged_by, operators)
        actions = AuditEvent.objects.filter(organization=clinic).values_list('action', flat=True)
        self.assertCountEqual(actions, ['entitlement.review_requested', 'entitlement.review_acknowledged'])
