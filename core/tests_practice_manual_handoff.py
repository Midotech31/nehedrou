"""Fictional practice handoff links: scopes, disclosure, acceptance and replay."""
import hashlib
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from html.parser import HTMLParser
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from care.models import Child, FamilyLink
from core import services
from core.access import CURRENT_NOTICE_VERSION
from core.models import AuditEvent, Entitlement, Invitation, Membership, NoticeAcknowledgement, Organization, User
from core.testing import practice_form_data

SETTINGS = dict(DEMO_MODE=False, DEBUG=False, MFA_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND='core.email_backends.DisabledEmailBackend', PUBLIC_ORIGIN='https://practice.example',
    LANGUAGE_CODE='en', PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def fixture(case):
    case.owner = User.objects.create_user('handoff-owner', 'owner@example.test')
    case.clinician = User.objects.create_user('handoff-clinician', 'clinician@example.test')
    case.family = User.objects.create_user('handoff-family', 'family@example.test')
    case.outsider = User.objects.create_user('handoff-outsider', 'outsider@example.test')
    case.organization = Organization.objects.create(name='Fictional handoff A')
    case.other_organization = Organization.objects.create(name='Fictional handoff B')
    case.owner_member = Membership.objects.create(user=case.owner, organization=case.organization, role='owner')
    case.other_owner_member = Membership.objects.create(user=case.owner, organization=case.other_organization, role='owner')
    Membership.objects.create(user=case.clinician, organization=case.organization, role='clinician')
    Membership.objects.create(user=case.outsider, organization=case.other_organization, role='owner')
    for org in (case.organization, case.other_organization):
        Entitlement.objects.create(organization=org, expires_at=timezone.now()+timedelta(days=10),
            practitioner_quota=10, child_quota=10)
    case.child = Child.objects.create(organization=case.organization, responsible=case.clinician,
        code='Fictional handoff A', age_years=5)
    case.sibling = Child.objects.create(organization=case.organization, responsible=case.clinician,
        code='Fictional second handoff A', age_years=6)
    case.foreign_child = Child.objects.create(organization=case.other_organization, responsible=case.outsider,
        code='Fictional handoff B', age_years=5)
    FamilyLink.objects.create(child=case.child, user=case.family)
    for user, org in ((case.owner, case.organization), (case.owner, case.other_organization),
                      (case.clinician, case.organization), (case.outsider, case.other_organization)):
        NoticeAcknowledgement.objects.create(user=user, organization=org,
            version=CURRENT_NOTICE_VERSION, language='en')


class Fixture:
    @classmethod
    def setUpTestData(cls):
        fixture(cls)

    def issue(self, kind='family', **extra):
        data = dict(actor=self.clinician if kind == 'family' else self.owner,
            organization=self.organization, child=self.child if kind == 'family' else None,
            email='manual-'+kind+'@example.test', kind=kind, creation_id=uuid.uuid4())
        data.update(extra)
        return services.issue_manual_practice_invitation(**data)

    def snapshot(self):
        return (tuple(Invitation.objects.order_by('pk').values_list('pk', 'organization_id',
                    'child_id', 'kind', 'email', 'token_hash', 'revoked', 'used_at', 'expires_at', 'delivery')),
                tuple(AuditEvent.objects.order_by('pk').values_list('pk', 'action', 'object_id')),
                tuple(Membership.objects.order_by('pk').values_list('pk', 'user_id', 'organization_id', 'role', 'active')),
                tuple(FamilyLink.objects.order_by('pk').values_list('pk', 'user_id', 'child_id', 'active')),
                tuple(User.objects.order_by('pk').values_list('pk', 'email', 'is_active', 'is_staff', 'is_superuser')))


@override_settings(**SETTINGS)
class PracticeManualHandoffServiceTests(Fixture, TestCase):
    def test_each_kind_discloses_once_without_mail_account_or_access_creation(self):
        counts = (User.objects.count(), Membership.objects.count(), FamilyLink.objects.count())
        with patch('django.core.mail.send_mail') as mail, patch('smtplib.SMTP') as smtp, \
                patch('http.client.HTTPSConnection') as https:
            for kind in ('family', 'clinician'):
                with self.subTest(kind=kind):
                    creation_id = uuid.uuid4()
                    invitation, raw = self.issue(kind, email='  MANUAL-'+kind.upper()+'@EXAMPLE.TEST  ', creation_id=creation_id)
                    self.assertEqual(invitation.pk, creation_id)
                    self.assertEqual(invitation.email, 'manual-'+kind+'@example.test')
                    self.assertEqual(invitation.organization_id, self.organization.pk)
                    self.assertEqual(invitation.child_id, self.child.pk if kind == 'family' else None)
                    self.assertEqual((invitation.kind, invitation.delivery), (kind, 'manual'))
                    self.assertTrue(invitation.available)
                    self.assertTrue(raw)
                    self.assertEqual(invitation.token_hash, hashlib.sha256(raw.encode()).hexdigest())
                    self.assertNotIn(raw, json.dumps(list(Invitation.objects.values()), default=str))
                    self.assertNotIn(raw, json.dumps(list(AuditEvent.objects.values()), default=str))
                    before = self.snapshot()
                    replay, disclosed = self.issue(kind, creation_id=creation_id)
                    self.assertEqual(replay.pk, invitation.pk)
                    self.assertIsNone(disclosed)
                    self.assertEqual(self.snapshot(), before)
            mail.assert_not_called(); smtp.assert_not_called(); https.assert_not_called()
        self.assertEqual((User.objects.count(), Membership.objects.count(), FamilyLink.objects.count()), counts)

    def test_creation_id_cannot_change_recipient_scope_kind_or_sender(self):
        creation_id = uuid.uuid4()
        self.issue(creation_id=creation_id)
        before = self.snapshot()
        changes = [dict(email='different@example.test'), dict(child=self.sibling),
            dict(organization=self.other_organization, child=self.foreign_child, actor=self.outsider),
            dict(kind='clinician', child=None, actor=self.owner), dict(actor=self.owner)]
        for change in changes:
            with self.subTest(fields=sorted(change)):
                with self.assertRaises((ValidationError, PermissionDenied)):
                    self.issue(creation_id=creation_id, **change)
                self.assertEqual(self.snapshot(), before)

    def test_replacement_only_revokes_unused_live_same_recipient_and_scope(self):
        email = 'same@example.test'
        target, _ = Invitation.issue(self.organization, self.child, email, self.clinician)
        untouched = []
        for org, child, recipient, actor, kind in (
                (self.organization, self.sibling, email, self.clinician, 'family'),
                (self.organization, None, email, self.owner, 'clinician'),
                (self.other_organization, self.foreign_child, email, self.outsider, 'family'),
                (self.organization, self.child, 'another@example.test', self.clinician, 'family')):
            invite, _ = Invitation.issue(org, child, recipient, actor, kind=kind)
            untouched.append(invite)
        for state in ('expired', 'used', 'revoked'):
            invite, _ = Invitation.issue(self.organization, self.child, email, self.clinician)
            if state == 'expired':
                invite.expires_at = timezone.now()-timedelta(seconds=1)
            elif state == 'used':
                invite.used_at = timezone.now()
            else:
                invite.revoked = True
            invite.save()
            untouched.append(invite)
        states = {i.pk:(i.token_hash, i.revoked, i.used_at, i.expires_at) for i in untouched}
        replacement, raw = self.issue(email=email)
        target.refresh_from_db()
        self.assertTrue(target.revoked)
        self.assertTrue(replacement.available and raw)
        for invite in untouched:
            invite.refresh_from_db()
            self.assertEqual((invite.token_hash, invite.revoked, invite.used_at, invite.expires_at), states[invite.pk])

    def test_unauthorized_or_mismatched_requests_do_not_issue_or_rotate(self):
        self.issue(email='preserve@example.test')
        before = self.snapshot()
        attempts = [dict(actor=self.family), dict(actor=self.outsider), dict(actor=self.owner),
            dict(kind='clinician', actor=self.clinician, child=None), dict(organization=self.other_organization),
            dict(kind='owner', child=None), dict(creation_id=None), dict(creation_id=''),
            dict(creation_id='invalid-uuid')]
        for values in attempts:
            with self.subTest(fields=sorted(values)):
                with self.assertRaises((ValidationError, PermissionDenied)):
                    self.issue(email='preserve@example.test', **values)
                self.assertEqual(self.snapshot(), before)

    def test_sender_and_recipient_state_is_rechecked_without_partial_rotation(self):
        invite, _ = self.issue(email='inactive@example.test')
        recipient = User.objects.create_user('inactive-recipient', invite.email, is_active=False)
        before = self.snapshot()
        with self.assertRaises((ValidationError, PermissionDenied)):
            self.issue(email=recipient.email)
        self.assertEqual(self.snapshot(), before)
        self.child.active = False
        self.child.save()
        before = self.snapshot()
        with self.assertRaises((ValidationError, PermissionDenied)):
            self.issue()
        self.assertEqual(self.snapshot(), before)
        self.child.active = True
        self.child.save()
        Membership.objects.filter(user=self.clinician, organization=self.organization).update(active=False)
        before = self.snapshot()
        with self.assertRaises((ValidationError, PermissionDenied)):
            self.issue()
        self.assertEqual(self.snapshot(), before)
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        before = self.snapshot()
        with self.assertRaises((ValidationError, PermissionDenied)):
            self.issue('clinician')
        self.assertEqual(self.snapshot(), before)

    def test_acceptance_is_email_bound_single_use_and_keeps_role_limits(self):
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind):
                invite, token = self.issue(kind)
                recipient = User.objects.create_user('accept-'+kind, invite.email)
                with self.assertRaises(ValidationError):
                    services.accept_invitation(self.family, token)
                self.assertIsNone(Invitation.objects.get(pk=invite.pk).used_at)
                services.accept_invitation(recipient, token)
                self.assertIsNotNone(Invitation.objects.get(pk=invite.pk).used_at)
                if kind == 'family':
                    self.assertEqual(list(FamilyLink.objects.filter(user=recipient).values_list('child_id', flat=True)), [self.child.pk])
                    self.assertFalse(Membership.objects.filter(user=recipient).exists())
                else:
                    member = Membership.objects.get(user=recipient)
                    self.assertEqual((member.organization_id, member.role), (self.organization.pk, 'clinician'))
                    self.assertFalse(FamilyLink.objects.filter(user=recipient).exists())
                self.assertFalse(recipient.is_staff or recipient.is_superuser or recipient.user_permissions.exists())
                before = self.snapshot()
                with self.assertRaises(ValidationError):
                    services.accept_invitation(recipient, token)
                self.assertEqual(self.snapshot(), before)
                replay, disclosed = self.issue(kind, creation_id=invite.pk)
                self.assertEqual(replay.pk, invite.pk)
                self.assertIsNone(disclosed)
                self.assertEqual(self.snapshot(), before)

    def test_manual_acceptance_refuses_archived_child_or_newly_disabled_recipient(self):
        invite, token = self.issue()
        recipient = User.objects.create_user('archived-recipient', invite.email)
        self.child.active = False
        self.child.save()
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            services.accept_invitation(recipient, token)
        self.assertEqual(self.snapshot(), before)
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind):
                invite, token = self.issue(kind, child=self.sibling if kind == 'family' else None,
                    email='disabled-'+kind+'@example.test')
                recipient = User.objects.create_user('disabled-'+kind, invite.email)
                User.objects.filter(pk=recipient.pk).update(is_active=False)
                before = self.snapshot()
                with self.assertRaises(ValidationError):
                    services.accept_invitation(recipient, token)
                self.assertEqual(self.snapshot(), before)

    def test_manual_acceptance_does_not_bypass_practitioner_quota(self):
        invite, token = self.issue('clinician')
        recipient = User.objects.create_user('quota-recipient', invite.email)
        entitlement = Entitlement.objects.get(organization=self.organization)
        entitlement.practitioner_quota = Membership.objects.filter(organization=self.organization, active=True).count()
        entitlement.save()
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            services.accept_invitation(recipient, token)
        self.assertEqual(self.snapshot(), before)


class HiddenInputs(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.values = {}
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'input' and attributes.get('type') == 'hidden' and attributes.get('name'):
            self.values[attributes['name']] = attributes.get('value', '')


@override_settings(**SETTINGS)
class PracticeManualHandoffViewTests(Fixture, TestCase):
    def setUp(self):
        translation.activate('en')

    def sender(self, kind, client=None):
        client = client or self.client
        client.logout()
        client.force_login(self.clinician if kind == 'family' else self.owner)
        session = client.session
        session['organization'] = str(self.organization.pk)
        session['workspace'] = 'professional'
        session.save()

    def path(self, kind, language='en'):
        return f'/{language}/children/{self.child.pk}/' if kind == 'family' else f'/{language}/members/'

    def form(self, kind, language='en', email=None, client=None):
        client = client or self.client
        path = self.path(kind, language)
        page = client.get(path)
        self.assertEqual(page.status_code, 200)
        hidden = HiddenInputs(page.content.decode()).values
        self.assertIn('creation_id', hidden)
        uuid.UUID(hidden['creation_id'])
        data = {key:hidden[key] for key in ('csrfmiddlewaretoken', 'practice_scope', 'creation_id') if key in hidden}
        data.update(email=email or 'view-'+kind+'@example.test', delivery_method='manual')
        return path, data

    def test_first_links_are_private_and_localized_for_both_sender_roles(self):
        with patch('django.core.mail.send_mail') as mail, patch('smtplib.SMTP') as smtp, \
                patch('http.client.HTTPSConnection') as https:
            for language in ('fr', 'en', 'ar'):
                for kind in ('family', 'clinician'):
                    with self.subTest(language=language, kind=kind):
                        self.sender(kind)
                        path, data = self.form(kind, language, language+'-'+kind+'@example.test')
                        response = self.client.post(path, data)
                        self.assertEqual(response.status_code, 200)
                        invite, link = response.context['manual_invitation'], response.context['manual_link']
                        self.assertFalse(response.context['manual_already_created'])
                        self.assertEqual(invite.pk, uuid.UUID(data['creation_id']))
                        parsed = urlsplit(link)
                        self.assertEqual((parsed.scheme, parsed.netloc), ('https', 'practice.example'))
                        self.assertTrue(parsed.path.startswith('/'+language+'/invite/'))
                        token = parsed.path.rstrip('/').split('/')[-1]
                        self.assertEqual(invite.token_hash, hashlib.sha256(token.encode()).hexdigest())
                        self.assertContains(response, link)
                        self.assertIn('private', response['Cache-Control'])
                        self.assertIn('no-store', response['Cache-Control'])
                        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
                        self.assertContains(response, 'lang="'+language+'"')
                        if language == 'ar':
                            self.assertContains(response, 'dir="rtl"')
            mail.assert_not_called(); smtp.assert_not_called(); https.assert_not_called()

    def test_get_and_replay_do_not_redisclose_or_rotate_original_link(self):
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind):
                self.sender(kind)
                path, data = self.form(kind)
                first = self.client.post(path, data)
                original = first.context['manual_invitation']
                raw = urlsplit(first.context['manual_link']).path.rstrip('/').split('/')[-1]
                shown = self.client.get(path)
                self.assertFalse(shown.context.get('manual_link'))
                self.assertNotContains(shown, raw)
                before = self.snapshot()
                repeated = self.client.post(path, data)
                self.assertEqual(repeated.status_code, 200)
                self.assertTrue(repeated.context['manual_already_created'])
                self.assertFalse(repeated.context.get('manual_link'))
                self.assertNotContains(repeated, raw)
                self.assertEqual(self.snapshot(), before)
                original.refresh_from_db()
                self.assertTrue(original.available)
                self.assertEqual(original.token_hash, hashlib.sha256(raw.encode()).hexdigest())

    def test_distinct_form_replaces_only_previous_matching_unused_link(self):
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind):
                self.sender(kind)
                path, data = self.form(kind)
                first = self.client.post(path, data)
                original, old_link = first.context['manual_invitation'], first.context['manual_link']
                path, replacement = self.form(kind)
                self.assertNotEqual(data['creation_id'], replacement['creation_id'])
                response = self.client.post(path, replacement)
                self.assertEqual(response.status_code, 200)
                original.refresh_from_db()
                self.assertTrue(original.revoked)
                self.assertTrue(response.context['manual_invitation'].available)
                self.assertEqual(self.client.get(urlsplit(old_link).path).status_code, 410)

    def test_current_notice_is_required_before_either_manual_creation(self):
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind):
                self.sender(kind)
                path, data = self.form(kind)
                actor = self.clinician if kind == 'family' else self.owner
                self.issue(kind, email=data['email'])
                NoticeAcknowledgement.objects.filter(user=actor, organization=self.organization).delete()
                before = self.snapshot()
                response = self.client.post(path, data)
                self.assertRedirects(response, '/en/information/', fetch_redirect_response=False)
                self.assertEqual(self.snapshot(), before)

    def test_members_scope_cannot_cross_cabinet_switch_or_rebind_after_conflict(self):
        self.sender('clinician')
        path, data = self.form('clinician')
        preserved, _ = Invitation.issue(self.other_organization, None, data['email'], self.owner, kind='clinician')
        self.client.post('/en/app/switch/', {'membership':str(self.other_owner_member.pk)})
        before = self.snapshot()
        response = self.client.post(path, data)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.context['practice_scope'], data['practice_scope'])
        self.assertEqual(self.snapshot(), before)
        response = self.client.post(path, {**data, 'practice_scope':response.context['practice_scope']})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.snapshot(), before)
        preserved.refresh_from_db()
        self.assertTrue(preserved.available)

    def test_invalid_members_scope_or_creation_id_never_creates_a_link(self):
        self.sender('clinician')
        path, data = self.form('clinician')
        for field, value, status in (('practice_scope', '', 409), ('practice_scope', 'invalid', 409),
                ('creation_id', '', 200), ('creation_id', 'invalid', 200)):
            with self.subTest(field=field, value=value):
                before = self.snapshot()
                response = self.client.post(path, {**data, field:value})
                self.assertEqual(response.status_code, status)
                self.assertFalse(response.context.get('manual_link'))
                self.assertEqual(self.snapshot(), before)
        for kind in ('family', 'clinician'):
            self.sender(kind)
            path, data = self.form(kind)
            data.pop('creation_id')
            before = self.snapshot()
            response = self.client.post(path, data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
            self.assertFalse(response.context.get('manual_link'))
            self.assertEqual(self.snapshot(), before)

    def test_csrf_is_required_and_family_outsider_and_wrong_role_are_denied(self):
        checked = Client(enforce_csrf_checks=True)
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind):
                self.sender(kind, checked)
                path, protected = self.form(kind, client=checked)
                protected.pop('csrfmiddlewaretoken')
                before = self.snapshot()
                self.assertEqual(checked.post(path, protected).status_code, 403)
                self.assertEqual(self.snapshot(), before)
                self.sender(kind)
                path, data = self.form(kind)
                for actor in (self.family, self.outsider, self.owner if kind == 'family' else self.clinician):
                    self.client.force_login(actor)
                    before = self.snapshot()
                    self.assertIn(self.client.post(path, data).status_code, (404, 409))
                    self.assertEqual(self.snapshot(), before)
        self.client.force_login(self.family)
        response = self.client.get(self.path('family'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="creation_id"')

    def test_manual_recipient_uses_normal_acceptance_and_current_notice(self):
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind):
                invite, token = self.issue(kind)
                recipient = User.objects.create_user('notice-recipient-'+kind, invite.email)
                self.client.logout()
                self.client.force_login(recipient)
                response = self.client.post(reverse('invite', args=[token]))
                self.assertRedirects(response, reverse('data_notice'), fetch_redirect_response=False)
                self.assertNotIn('pending_notice_invitation_token', self.client.session)
                self.assertEqual(self.client.session['pending_notice_invitation_digest'], hashlib.sha256(token.encode()).hexdigest())
                self.assertFalse(FamilyLink.objects.filter(user=recipient).exists())
                self.assertFalse(Membership.objects.filter(user=recipient).exists())
                self.assertIsNone(Invitation.objects.get(pk=invite.pk).used_at)
                notice = reverse('data_notice')
                response = self.client.post(notice, practice_form_data(self.client, notice))
                self.assertEqual(response.status_code, 302)
                self.assertIsNotNone(Invitation.objects.get(pk=invite.pk).used_at)
                if kind == 'family':
                    self.assertEqual(list(FamilyLink.objects.filter(user=recipient).values_list('child_id', flat=True)), [self.child.pk])
                    self.assertFalse(Membership.objects.filter(user=recipient).exists())
                else:
                    member = Membership.objects.get(user=recipient)
                    self.assertEqual((member.organization_id, member.role), (self.organization.pk, 'clinician'))
                    self.assertFalse(FamilyLink.objects.filter(user=recipient).exists())

    def test_legacy_pending_session_migrates_to_digest_then_accepts_the_same_invitation(self):
        invitation, token = Invitation.issue(self.organization, self.child,
            'legacy-pending@example.test', self.clinician)
        original_hash = invitation.token_hash
        recipient = User.objects.create_user('legacy-pending-recipient', invitation.email)
        self.client.force_login(recipient)
        session = self.client.session
        session['pending_notice_invitation_token'] = token
        session.save()
        notice = reverse('data_notice')
        page = self.client.get(notice)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('pending_notice_invitation_token', self.client.session)
        self.assertEqual(self.client.session['pending_notice_invitation_digest'], original_hash)
        self.assertFalse(FamilyLink.objects.filter(user=recipient).exists())
        self.assertIsNone(Invitation.objects.get(pk=invitation.pk).used_at)
        response = self.client.post(notice, {'practice_scope':page.context['practice_scope']})
        self.assertEqual(response.status_code, 302)
        invitation.refresh_from_db()
        self.assertEqual(invitation.token_hash, original_hash)
        self.assertIsNotNone(invitation.used_at)
        self.assertEqual(Invitation.objects.count(), 1)
        self.assertEqual(list(FamilyLink.objects.filter(user=recipient).values_list('child_id', flat=True)), [self.child.pk])
        self.assertNotIn('pending_notice_invitation_token', self.client.session)
        self.assertNotIn('pending_notice_invitation_digest', self.client.session)

    def test_revoked_or_expired_links_remain_unusable(self):
        for kind in ('family', 'clinician'):
            for state in ('expired', 'revoked'):
                with self.subTest(kind=kind, state=state):
                    invite, token = self.issue(kind, email=state+'-'+kind+'@example.test')
                    recipient = User.objects.create_user(state+'-'+kind, invite.email)
                    if state == 'expired':
                        invite.expires_at = timezone.now()-timedelta(seconds=1)
                        invite.save()
                    else:
                        self.sender(kind)
                        route = 'revoke_invite' if kind == 'family' else 'revoke_member_invitation'
                        self.assertEqual(self.client.post(reverse(route, args=[invite.pk])).status_code, 302)
                    self.client.force_login(recipient)
                    path = reverse('invite', args=[token])
                    self.assertEqual(self.client.get(path).status_code, 410)
                    self.assertEqual(self.client.post(path).status_code, 410)
                    self.assertFalse(FamilyLink.objects.filter(user=recipient).exists())
                    self.assertFalse(Membership.objects.filter(user=recipient).exists())
                    invite.refresh_from_db()
                    self.assertIsNone(invite.used_at)

    def test_legacy_email_submit_is_not_silently_converted_to_manual(self):
        for kind in ('family', 'clinician'):
            with self.subTest(kind=kind):
                self.sender(kind)
                path, data = self.form(kind, email='legacy-'+kind+'@example.test')
                data.pop('delivery_method')
                response = self.client.post(path, data)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(Invitation.objects.get(email=data['email']).delivery, 'failed')
                self.assertFalse(self.client.get(path).context.get('manual_link'))


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL invitation row locks')
@override_settings(**SETTINGS)
class PracticeManualHandoffConcurrencyTests(Fixture, TransactionTestCase):
    def setUp(self):
        fixture(self)

    def test_duplicate_creation_id_discloses_once_without_rotation_or_extra_audit(self):
        baseline, _ = self.issue(email='baseline@example.test')
        expected = list(AuditEvent.objects.filter(object_id=str(baseline.pk)).order_by('action').values_list('action', flat=True))
        self.assertTrue(expected)
        creation_id = uuid.uuid4()
        barrier = threading.Barrier(2)
        actor_id, org_id, child_id = self.clinician.pk, self.organization.pk, self.child.pk

        def create_once(_worker):
            connections.close_all()
            try:
                actor, org, child = User.objects.get(pk=actor_id), Organization.objects.get(pk=org_id), Child.objects.get(pk=child_id)
                barrier.wait(timeout=10)
                invite, raw = services.issue_manual_practice_invitation(actor, org, child,
                    'race@example.test', 'family', creation_id)
                disclosed_digest = hashlib.sha256(raw.encode()).hexdigest() if raw is not None else None
                return invite.pk, disclosed_digest, invite.token_hash
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create_once, range(2)))
        self.assertEqual([row[0] for row in results], [creation_id, creation_id])
        self.assertEqual(sum(row[1] is not None for row in results), 1)
        self.assertEqual(len({row[2] for row in results}), 1)
        self.assertEqual(Invitation.objects.filter(pk=creation_id).count(), 1)
        self.assertEqual(Invitation.objects.count(), 2)
        invite = Invitation.objects.get(pk=creation_id)
        self.assertTrue(invite.available)
        self.assertEqual(invite.token_hash, results[0][2])
        self.assertEqual([row[1] for row in results if row[1] is not None], [invite.token_hash])
        actual = list(AuditEvent.objects.filter(object_id=str(creation_id)).order_by('action').values_list('action', flat=True))
        self.assertEqual(actual, expected)
