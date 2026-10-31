"""Real form contexts prevent retained tabs from changing a different practice."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading
import time
from unittest import skipUnless
from unittest.mock import patch

from django.core import signing
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from care.models import Child, FamilyLink
from catalog.models import Variety
from .form_scope import ERROR, MAX_AGE, SALT
from .models import AuditEvent, Entitlement, Invitation, Membership, NoticeAcknowledgement, Organization, User
from .testing import practice_form_data


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PracticeFormScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_user('scope-owner', 'scope-owner@example.test')
        cls.other = User.objects.create_user('scope-other', 'scope-other@example.test')
        cls.org_a = Organization.objects.create(name='Fictional scope A', retention_days=100)
        cls.org_b = Organization.objects.create(name='Fictional scope B', retention_days=200)
        cls.member_a = Membership.objects.create(user=cls.actor, organization=cls.org_a, role='owner')
        cls.member_b = Membership.objects.create(user=cls.actor, organization=cls.org_b, role='owner')
        Membership.objects.create(user=cls.other, organization=cls.org_a, role='owner')
        cls.variety = Variety.objects.create(code='scope-fr', language='fr', label='French')
        for org in (cls.org_a, cls.org_b):
            Entitlement.objects.create(organization=org, expires_at=timezone.now()+timedelta(days=2), practitioner_quota=8)

    def setUp(self):
        translation.activate('en')
        self.client.force_login(self.actor)
        self.select(self.member_a)

    def select(self, member, client=None):
        response = (client or self.client).post(reverse('switch_practice'), {'membership': str(member.pk)})
        self.assertEqual(response.status_code, 302)

    def data(self, name):
        return {'child_create': {'code':'Retained profile', 'age_years':5, 'varieties':[str(self.variety.pk)]},
                'members': {'email':'scope-invite@example.test'},
                'organization_settings': {'name':'Retained name', 'country':'DZ', 'retention_days':987},
                'data_notice': {}}[name].copy()

    names = ('child_create', 'members', 'organization_settings', 'data_notice')

    def snapshot(self):
        return (tuple(Child.objects.values_list('pk', flat=True)),
                tuple(Invitation.objects.values_list('pk', 'token_hash', 'revoked', 'used_at', 'delivery')),
                tuple(Organization.objects.order_by('pk').values_list('pk', 'name', 'retention_days')),
                tuple(NoticeAcknowledgement.objects.values_list('pk', flat=True)),
                tuple(AuditEvent.objects.values_list('pk', flat=True)))

    def assert_refused(self, name, data, original=None):
        before = self.snapshot()
        with patch('core.views.issue_and_deliver_invitation') as send:
            response = self.client.post(reverse(name), data)
            send.assert_not_called()
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, str(ERROR), status_code=409)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(response.context['practice_scope'], data.get('practice_scope', ''))
        if original:
            for field, value in original.items():
                if name != 'data_notice':
                    self.assertEqual(response.context['form'][field].value(), value if isinstance(value, list) else str(value))
        return response

    def test_all_implicit_forms_render_the_signed_context_exactly_once(self):
        for name in self.names:
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'name="practice_scope"', count=1)
                payload = signing.loads(response.context['practice_scope'], salt=SALT)
                self.assertEqual(payload['actor'], str(self.actor.pk))
                self.assertEqual(payload['organization'], str(self.org_a.pk))

    def test_retained_forms_after_other_tab_switch_refuse_without_mutation_or_token_rebinding(self):
        forms = {name: practice_form_data(self.client, reverse(name), self.data(name)) for name in self.names}
        pending, _ = Invitation.issue(self.org_b, None, 'existing-scope@example.test', self.actor, kind='clinician')
        self.select(self.member_b)
        for name in self.names:
            with self.subTest(name=name):
                response = self.assert_refused(name, forms[name], self.data(name))
                # Re-submitting the conflict response must not acquire B's scope.
                self.assert_refused(name, {**forms[name], 'practice_scope': response.context['practice_scope']})
        pending.refresh_from_db()
        self.assertFalse(pending.revoked)
        self.assertEqual(self.client.session['organization'], str(self.org_b.pk))

    def test_explicit_b_selection_and_new_b_forms_allow_only_b_mutations(self):
        self.select(self.member_b)
        for name in self.names:
            with self.subTest(name=name):
                response = self.client.post(reverse(name), practice_form_data(self.client, reverse(name), self.data(name)))
                self.assertEqual(response.status_code, 302)
        self.assertEqual(Child.objects.get(code='Retained profile').organization_id, self.org_b.pk)
        self.assertEqual(Invitation.objects.get(email='scope-invite@example.test').organization_id, self.org_b.pk)
        self.org_a.refresh_from_db(); self.org_b.refresh_from_db()
        self.assertEqual((self.org_a.name, self.org_a.retention_days), ('Fictional scope A', 100))
        self.assertEqual((self.org_b.name, self.org_b.retention_days), ('Retained name', 987))
        self.assertEqual(list(NoticeAcknowledgement.objects.values_list('organization_id', flat=True)), [self.org_b.pk])

    def test_missing_malformed_and_tampered_contexts_fail_closed(self):
        for name in self.names:
            valid = practice_form_data(self.client, reverse(name), self.data(name))['practice_scope']
            for token in (None, '', 'invalid', valid+'tampered', 'x'*4097):
                with self.subTest(name=name, token_kind=type(token).__name__):
                    data = self.data(name)
                    if token is not None:
                        data['practice_scope'] = token
                    self.assert_refused(name, data)
        self.assertEqual(self.client.post(reverse('child_create'), {}).status_code, 409)

    def test_signed_actor_organization_and_operation_cannot_be_permuted(self):
        forms = {name: practice_form_data(self.client, reverse(name), self.data(name)) for name in self.names}
        for name in self.names:
            token = forms[name]['practice_scope']
            payload = signing.loads(token, salt=SALT)
            for field, value in (('actor', str(self.other.pk)), ('organization', str(self.org_b.pk)),
                                 ('organization', 'not-a-uuid'), ('operation', 'unrelated'), ('version', 2)):
                with self.subTest(name=name, field=field, value=value):
                    altered = signing.dumps({**payload, field:value}, salt=SALT)
                    self.assert_refused(name, {**forms[name], 'practice_scope':altered})
            other_name = next(key for key in self.names if key != name)
            self.assert_refused(name, {**forms[name], 'practice_scope':forms[other_name]['practice_scope']})

    def test_actual_other_account_cannot_reuse_actor_context(self):
        form = practice_form_data(self.client, reverse('child_create'), self.data('child_create'))
        self.client.force_login(self.other)
        self.assert_refused('child_create', form)

    def test_expired_context_requires_a_new_form(self):
        with patch('django.core.signing.time.time', return_value=time.time()-MAX_AGE-10):
            form = practice_form_data(self.client, reverse('child_create'), self.data('child_create'))
        self.assert_refused('child_create', form)
        fresh = practice_form_data(self.client, reverse('child_create'), self.data('child_create'))
        self.assertEqual(self.client.post(reverse('child_create'), fresh).status_code, 302)

    def test_current_roles_and_revocation_still_override_a_valid_context(self):
        forms = {name: practice_form_data(self.client, reverse(name), self.data(name)) for name in self.names}
        self.member_a.role = 'clinician'; self.member_a.save()
        before = self.snapshot()
        for name in ('members', 'organization_settings'):
            self.assertEqual(self.client.post(reverse(name), forms[name]).status_code, 404)
        self.member_a.active = False; self.member_a.save()
        self.assertEqual(self.client.post(reverse('child_create'), forms['child_create']).status_code, 404)
        self.assertEqual(self.client.post(reverse('data_notice'), forms['data_notice']).status_code, 409)
        self.assertEqual(self.snapshot(), before)

    def test_valid_scope_does_not_replace_csrf_protection(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        for name in self.names:
            with self.subTest(name=name):
                form = practice_form_data(client, reverse(name), self.data(name))
                before = self.snapshot()
                self.assertEqual(client.post(reverse(name), form).status_code, 403)
                self.assertEqual(self.snapshot(), before)
        form = practice_form_data(client, reverse('child_create'), self.data('child_create'))
        form['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
        self.assertEqual(client.post(reverse('child_create'), form).status_code, 302)

    def test_single_membership_still_requires_a_real_form_and_preserves_quota_checks(self):
        self.member_b.active = False; self.member_b.save()
        for name in self.names:
            self.assert_refused(name, self.data(name))
        entitlement = self.org_a.entitlement
        entitlement.child_quota = 0; entitlement.save()
        response = self.client.post(reverse('child_create'), practice_form_data(self.client, reverse('child_create'), self.data('child_create')))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Child.objects.exists())
        entitlement.child_quota = 2; entitlement.save()
        self.assertEqual(self.client.post(reverse('child_create'), practice_form_data(self.client, reverse('child_create'), self.data('child_create'))).status_code, 302)

    def test_family_workspace_does_not_use_professional_scope_to_create_or_invite(self):
        family_child = Child.objects.create(organization=self.org_b, responsible=self.actor, code='Linked fictional family', age_years=5)
        FamilyLink.objects.create(user=self.actor, child=family_child)
        forms = {name: practice_form_data(self.client, reverse(name), self.data(name)) for name in ('child_create','members','organization_settings')}
        self.assertEqual(self.client.post(reverse('switch_practice'), {'space':'family'}).status_code, 302)
        before = self.snapshot()
        for name, data in forms.items():
            self.assertEqual(self.client.post(reverse(name), data).status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_object_scoped_child_mutation_keeps_its_explicit_cabinet_after_switch(self):
        child = Child.objects.create(organization=self.org_a, responsible=self.actor, code='Explicit A child', age_years=5)
        child.varieties.add(self.variety)
        self.client.get(reverse('child_edit', args=[child.pk]))
        self.select(self.member_b)
        response = self.client.post(reverse('child_edit', args=[child.pk]), {'code':'Edited explicit A child','age_years':6,'varieties':[str(self.variety.pk)]})
        self.assertEqual(response.status_code, 302)
        child.refresh_from_db()
        self.assertEqual((child.organization_id, child.code), (self.org_a.pk, 'Edited explicit A child'))


@override_settings(DEMO_MODE=True, MFA_REQUIRED=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
@skipUnless(connection.vendor == 'postgresql', 'Concurrent requests require PostgreSQL')
class PracticeFormScopeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        PracticeFormScopeTests.setUpTestData.__func__(type(self))
        self.client.force_login(self.actor)
        self.client.post(reverse('switch_practice'), {'membership':str(self.member_a.pk)})

    def test_inflight_a_post_cannot_be_retargeted_by_a_concurrent_b_switch(self):
        from .services import check_entitlement
        form = practice_form_data(self.client, reverse('child_create'), {'code':'Concurrent A profile', 'age_years':5, 'varieties':[str(self.variety.pk)]})
        entered = threading.Event(); release = threading.Event()
        def hold(org, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError('Concurrent switch did not finish')
            return check_entitlement(org, **kwargs)
        def worker():
            client = Client(); client.cookies = self.client.cookies.copy()
            try:
                return client.post(reverse('child_create'), form).status_code
            finally:
                connections.close_all()
        with patch('core.views.check_entitlement', side_effect=hold), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            try:
                self.assertTrue(entered.wait(10))
                self.assertEqual(self.client.post(reverse('switch_practice'), {'membership':str(self.member_b.pk)}).status_code, 302)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=10), 302)
        self.assertEqual(Child.objects.get(code='Concurrent A profile').organization_id, self.org_a.pk)
        self.assertEqual(self.client.session['organization'], str(self.org_b.pk))
        self.assertFalse(Child.objects.filter(organization=self.org_b).exists())